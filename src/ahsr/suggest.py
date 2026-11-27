"""Example queries derived from the indexed corpus, so the empty state teaches by showing real inputs.

Mixes the three kinds of query the system is built for: an exact identifier, a conceptual question,
and a multi-part question that exercises decomposition.
"""
from __future__ import annotations

import re

from ahsr.router.heuristic import PATTERNS
from ahsr.types import Chunk

_IDENT = {name: pat for name, pat, _ in PATTERNS if name in ("error_code", "cli_flag", "snake_case", "dotted_path")}
_ORDER = ("error_code", "cli_flag", "dotted_path", "snake_case")
_VERBS = {"add", "cancel", "change", "configure", "create", "delete", "disable", "download", "enable", "install",
          "remove", "rotate", "set", "terminate", "update", "upgrade"}
_SKIP_HEADINGS = {"overview", "introduction", "contents", "table of contents", "usage", "notes"}


def _identifier(text: str) -> str | None:
    for name in _ORDER:
        m = _IDENT[name].search(text)
        if m and len(m.group(0)) > 3:
            return m.group(0)
    return None


def _priority(ident: str) -> int:
    """Error codes make the most recognisable examples, then flags, then paths and function names."""
    for i, name in enumerate(_ORDER):
        if _IDENT[name].fullmatch(ident):
            return i
    return len(_ORDER)


def _concept(heading: str) -> str | None:
    h = re.sub(r"^[\w.\-]+:\s*", "", heading).strip()
    if not (3 <= len(h) <= 60) or h.lower() in _SKIP_HEADINGS or _identifier(h):
        return None
    low = h[0].lower() + h[1:]
    return f"how do I {low}" if low.split()[0].lower() in _VERBS else low


def suggest_queries(chunks: list[Chunk], limit: int = 6) -> list[dict]:
    idents: list[tuple[str, str]] = []         # (source, identifier)
    concepts: list[tuple[str, str]] = []       # (source, phrase)
    seen_i, seen_c = set(), set()
    for c in chunks:
        src = c.metadata["source"]
        heading = str(c.metadata.get("section", "")).split(" > ")[-1]
        ident = _identifier(heading) or _identifier(c.text.split("\n\n", 1)[-1])
        if ident and ident not in seen_i:
            seen_i.add(ident)
            idents.append((src, ident))
        phrase = _concept(heading)
        if phrase and phrase not in seen_c:
            seen_c.add(phrase)
            concepts.append((src, phrase))

    idents.sort(key=lambda x: _priority(x[1]))             # stable: keeps document order within a kind
    out: list[dict] = []
    multi = next(((i, c) for i in idents for c in concepts if i[0] != c[0]), None)
    queue = [("identifier", idents[0][1])] if idents else []
    queue += [("concept", concepts[0][1])] if concepts else []
    if multi:
        queue.append(("multi", f"{multi[0][1]} and also {multi[1][1]}"))
    queue += [("identifier", i[1]) for i in idents[1:2]]
    queue += [("concept", c[1]) for c in concepts[1:3]]
    for kind, q in queue:
        if q not in {x["query"] for x in out}:
            out.append({"kind": kind, "query": q})
    return out[:limit]
