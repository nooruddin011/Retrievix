"""Fallback tools the agent calls when static docs don't cover the question."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Protocol

import httpx

from ahsr.config import Settings
from ahsr.types import Hit

log = logging.getLogger(__name__)
STOP = {"the", "and", "for", "with", "how", "why", "what", "does", "this", "that", "from", "into",
        "when", "have", "after", "also", "error", "fails", "failing"}


class Tool(Protocol):
    name: str

    def search(self, query: str, k: int = 3) -> list[Hit]: ...


class GitHubIssuesTool:
    name = "github_issues"

    def __init__(self, repo: str, token: str = ""):
        self.repo, self.token = repo, token

    def search(self, query: str, k: int = 3) -> list[Hit]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = httpx.get("https://api.github.com/search/issues", timeout=10, headers=headers,
                          params={"q": f"{query} repo:{self.repo}", "per_page": k})
            r.raise_for_status()
        except Exception as e:                      # network/rate-limit: degrade, don't crash the agent
            log.warning("github issue search failed: %s", e)
            return []
        return [Hit(id=f"gh:{it['number']}", score=float(it.get("score", 0)),
                    text=f"#{it['number']} {it['title']} [{it['state']}]\n{(it.get('body') or '')[:600]}",
                    payload={"source": it["html_url"], "title": it["title"], "tool": "github_issues"},
                    origin="github") for it in r.json().get("items", [])[:k]]


class CodeSearchTool:
    """Greps a local codebase for the query's identifiers; boosts definition lines."""
    name = "code_search"
    EXTS = {".py", ".js", ".ts", ".go", ".java", ".rs", ".rb", ".cs"}
    DEF = re.compile(r"^\s*(def|class|function|func|fn|public|export)\b")

    def __init__(self, root: str, max_files: int = 3000):
        self.root, self.max_files = Path(root), max_files

    def search(self, query: str, k: int = 3) -> list[Hit]:
        terms = {t.lower() for t in re.findall(r"[A-Za-z_][\w]{2,}", query)} - STOP
        if not terms or not self.root.exists():
            return []
        scored: list[tuple[float, str, int, list[str]]] = []
        for n, path in enumerate(p for p in self.root.rglob("*") if p.suffix in self.EXTS):
            if n >= self.max_files:
                break
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines):
                hit = sum(1 for t in terms if t in ln.lower())
                if hit:
                    score = hit + (1.5 if self.DEF.match(ln) else 0)
                    scored.append((score, str(path.relative_to(self.root)), i + 1,
                                   lines[max(0, i - 2): i + 3]))
        scored.sort(key=lambda x: -x[0])
        return [Hit(id=f"code:{p}:{ln}", score=s, text="\n".join(snip),
                    payload={"source": f"{p}:{ln}", "title": p, "tool": "code_search"}, origin="code")
                for s, p, ln, snip in scored[:k]]


def build_tools(s: Settings) -> list[Tool]:
    tools: list[Tool] = []
    if s.code_root:
        tools.append(CodeSearchTool(s.code_root))
    if s.github_repo:
        tools.append(GitHubIssuesTool(s.github_repo, s.github_token))
    return tools
