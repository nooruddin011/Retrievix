"""Structure-aware Markdown chunking: heading breadcrumbs kept, fenced code blocks never split.

Chunk ids are derived from (source, position, content hash), so re-ingesting an unchanged document
yields identical ids. That is what makes incremental indexing possible: only new ids are embedded
and ids that no longer exist are deleted.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from ahsr.types import Chunk
from ahsr.util import sha1_hex

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _sections(text: str) -> list[tuple[list[str], list[str]]]:
    sections, path, buf, in_fence = [], [], [], False
    for ln in text.splitlines():
        if FENCE.match(ln):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(ln)
        if m:
            if buf:
                sections.append((list(path), buf))
                buf = []
            path = path[: len(m.group(1)) - 1] + [m.group(2).strip()]
        else:
            buf.append(ln)
    if buf:
        sections.append((list(path), buf))
    return sections


def _blocks(lines: list[str]) -> list[str]:
    """Paragraphs and whole fenced code blocks (atomic)."""
    blocks, cur, in_fence = [], [], False
    for ln in lines:
        if FENCE.match(ln):
            if not in_fence:
                if cur:
                    blocks.append("\n".join(cur))
                cur, in_fence = [ln], True
            else:
                cur.append(ln)
                blocks.append("\n".join(cur))
                cur, in_fence = [], False
            continue
        if in_fence:
            cur.append(ln)
        elif not ln.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _split_long(block: str, max_chars: int) -> list[str]:
    """Split an over-long prose block on line, then sentence, then word boundaries. Code is atomic."""
    if len(block) <= max_chars or FENCE.match(block.lstrip().split("\n", 1)[0]):
        return [block]
    lines = block.split("\n")
    sep, units = ("\n", lines) if len(lines) > 1 else (" ", SENTENCE.split(block))
    out, cur = [], ""
    for u in units:
        if len(u) > max_chars:                              # a single unit too long: wrap on words
            if cur:
                out.append(cur)
                cur = ""
            words, piece = u.split(" "), ""
            for w in words:
                if piece and len(piece) + 1 + len(w) > max_chars:
                    out.append(piece)
                    piece = w
                else:
                    piece = f"{piece} {w}".strip()
            cur = piece
            continue
        if cur and len(cur) + len(sep) + len(u) > max_chars:
            out.append(cur)
            cur = u
        else:
            cur = f"{cur}{sep}{u}" if cur else u
    if cur:
        out.append(cur)
    return out


def chunk_markdown(text: str, source: str, max_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    doc_title = ""
    for path, lines in _sections(text):
        doc_title = doc_title or (path[0] if path else Path(source).stem)
        blocks = [piece for b in _blocks(lines) for piece in _split_long(b, max_chars)]
        if not blocks:
            continue
        breadcrumb = " > ".join(path) if path else doc_title
        packs, cur, size = [], [], 0
        for b in blocks:
            if cur and size + len(b) > max_chars:
                packs.append(cur)
                cur, size = [], 0
            cur.append(b)
            size += len(b)
        if cur:
            packs.append(cur)
        for pack in packs:
            i = len(chunks)
            body = "\n\n".join(pack)
            chunks.append(Chunk(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}#{i}#{sha1_hex(body, 12)}")),
                text=f"{breadcrumb}\n\n{body}",
                metadata={"source": source, "title": doc_title, "section": breadcrumb,
                          "chunk_index": i, "chars": len(body)},
            ))
    return chunks
