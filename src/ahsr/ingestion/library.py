"""The documents directory as a managed library: validated paths, size limits, atomic writes.

Everything that touches user-supplied file names goes through ``normalize_doc_path`` so that an API
caller can never read or write outside the docs directory.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ahsr.errors import BadRequest, NotFound, PayloadTooLarge

_SEGMENT = re.compile(r"^[\w][\w .\-]*$", re.UNICODE)
_H1 = re.compile(r"^\s{0,3}#\s+(.*\S)\s*$", re.M)
MAX_PATH_CHARS = 180


def normalize_doc_path(raw: str) -> str:
    """Validate a user-supplied document path and return it in canonical POSIX form."""
    if not isinstance(raw, str) or not raw.strip():
        raise BadRequest("A document path is required.", code="invalid_path")
    rel = raw.strip()
    if len(rel) > MAX_PATH_CHARS:
        raise BadRequest("The document path is too long.", code="invalid_path")
    if "\\" in rel or "\x00" in rel or rel.startswith("/"):
        raise BadRequest("Use a relative path with forward slashes, like guides/setup.md.", code="invalid_path")
    parts = rel.split("/")
    for seg in parts:
        if seg in ("", ".", "..") or seg.startswith(".") or seg.endswith((".", " ")) or not _SEGMENT.match(seg):
            raise BadRequest(
                "Paths may use letters, numbers, spaces, dots, dashes and underscores, "
                "and may not start with a dot.", code="invalid_path")
    if not parts[-1].lower().endswith(".md"):
        raise BadRequest("Only Markdown (.md) documents are supported.", code="invalid_path")
    return "/".join(parts)


@dataclass
class DocInfo:
    path: str
    title: str
    bytes: int
    modified: float


class DocumentLibrary:
    def __init__(self, root: str | os.PathLike, max_bytes: int = 512 * 1024, max_docs: int = 500):
        self.root = Path(root)
        self.max_bytes, self.max_docs = max_bytes, max_docs

    def _resolve(self, rel: str) -> Path:
        rel = normalize_doc_path(rel)
        root = self.root.resolve()
        target = (root / rel).resolve()
        if root not in target.parents:                          # blocks symlink and traversal escapes
            raise BadRequest("That path is outside the documents folder.", code="invalid_path")
        return target

    @staticmethod
    def _title(text: str, path: str) -> str:
        m = _H1.search(text)
        return m.group(1).strip() if m else Path(path).stem

    def paths(self) -> list[str]:
        if not self.root.is_dir():
            return []
        root = self.root.resolve()
        out = []
        for p in sorted(self.root.rglob("*.md")):
            if p.is_file() and root in p.resolve().parents:
                out.append(p.relative_to(self.root).as_posix())
        return out

    def list(self) -> list[DocInfo]:
        infos = []
        for rel in self.paths():
            p = self.root / rel
            st = p.stat()
            infos.append(DocInfo(rel, self._title(p.read_text(encoding="utf-8", errors="replace"), rel),
                                 st.st_size, st.st_mtime))
        return infos

    def read(self, rel: str) -> str:
        p = self._resolve(rel)
        if not p.is_file():
            raise NotFound(f"No document named {rel!r}.")
        return p.read_text(encoding="utf-8", errors="replace")

    def stat(self, rel: str) -> DocInfo:
        p = self._resolve(rel)
        if not p.is_file():
            raise NotFound(f"No document named {rel!r}.")
        st = p.stat()
        return DocInfo(normalize_doc_path(rel), self._title(self.read(rel), rel), st.st_size, st.st_mtime)

    def write(self, rel: str, content: str) -> bool:
        """Atomically write a document. Returns True if it was newly created."""
        target = self._resolve(rel)
        if not isinstance(content, str) or not content.strip():
            raise BadRequest("The document is empty.", code="empty_document")
        if "\x00" in content:
            raise BadRequest("The document contains binary data.", code="invalid_content")
        data = content.encode("utf-8")
        if len(data) > self.max_bytes:
            raise PayloadTooLarge(f"Documents can be at most {self.max_bytes // 1024} KB.", code="document_too_large")
        created = not target.exists()
        if created and len(self.paths()) >= self.max_docs:
            raise BadRequest(f"The library is limited to {self.max_docs} documents.", code="library_full")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return created

    def delete(self, rel: str) -> None:
        p = self._resolve(rel)
        if not p.is_file():
            raise NotFound(f"No document named {rel!r}.")
        p.unlink()
        parent = p.parent                                       # tidy up now-empty sub-folders
        while parent != self.root.resolve() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
