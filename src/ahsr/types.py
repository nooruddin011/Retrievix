from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


@dataclass
class Hit:
    id: str
    score: float
    text: str
    payload: dict[str, Any]
    origin: str = "hybrid"          # dense | sparse | hybrid | github | code
    ranks: dict[str, int] = field(default_factory=dict)   # per-engine rank, for explainability

    @property
    def source(self) -> str:
        return str(self.payload.get("source", ""))

    @property
    def body(self) -> str:
        """Passage text without the heading breadcrumb that the chunker prepends for embedding."""
        section = str(self.payload.get("section") or "")
        if section and self.text.startswith(section):
            return self.text[len(section):].lstrip("\n")
        return self.text

    @property
    def title(self) -> str:
        return str(self.payload.get("section") or self.payload.get("title") or self.source)
