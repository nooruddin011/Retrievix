"""Hybrid retrieval: dense + learned-sparse, fused with (router-weighted) Reciprocal Rank Fusion.

    score(d) = sum_i  w_i / (k + rank_i(d))

RRF is rank-based, so no score calibration between the two engines is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Sequence

from ahsr.config import Settings
from ahsr.router.heuristic import RouteDecision, to_decision
from ahsr.types import Hit

if TYPE_CHECKING:                                   # keeps this module importable without qdrant-client
    from ahsr.retrieval.store import HybridStore

MODES = ("hybrid", "hybrid_flat", "hybrid_server", "dense", "sparse")


def rrf_fuse(rankings: Sequence[Sequence[Hit]], weights: Sequence[float], k: int = 60,
             top_n: int = 10, labels: Sequence[str] | None = None) -> list[Hit]:
    labels = labels or [f"list{i}" for i in range(len(rankings))]
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    ranks: dict[str, dict[str, int]] = {}
    for hits, w, label in zip(rankings, weights, labels):
        for rank, h in enumerate(hits, start=1):
            scores[h.id] = scores.get(h.id, 0.0) + w / (k + rank)
            best.setdefault(h.id, h)
            ranks.setdefault(h.id, {})[label] = rank
    ordered = sorted(scores, key=lambda i: -scores[i])[:top_n]
    return [replace(best[i], score=scores[i], origin="hybrid", ranks=ranks[i]) for i in ordered]


@dataclass
class RetrievalResult:
    hits: list[Hit]
    route: RouteDecision
    mode: str
    routed: bool = True             # False when the router was bypassed (single-engine / flat modes)


class HybridRetriever:
    def __init__(self, store: "HybridStore", dense, sparse, router, settings: Settings):
        self.store, self.dense, self.sparse, self.router, self.s = store, dense, sparse, router, settings

    def search(self, query: str, top_k: int | None = None, mode: str = "hybrid") -> RetrievalResult:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        k, pool = top_k or self.s.top_k, max(self.s.candidate_pool, top_k or 0)
        routed = mode == "hybrid"
        route = self.router.route(query) if routed else to_decision(0.5, [f"mode={mode}"])
        # encode only what the mode needs: the sparse transformer forward pass is not free
        qd = self.dense.encode([query], is_query=True)[0] if mode != "sparse" else None
        qs = self.sparse.encode([query], is_query=True)[0] if mode != "dense" else None

        if mode == "dense":
            return RetrievalResult(self.store.dense_search(qd, k), route, mode, routed)
        if mode == "sparse":
            return RetrievalResult(self.store.sparse_search(qs, k), route, mode, routed)
        if mode == "hybrid_server":
            return RetrievalResult(self.store.fusion_search(qd, qs, k, pool), route, mode, routed)

        dense_hits = self.store.dense_search(qd, pool)
        sparse_hits = self.store.sparse_search(qs, pool)
        hits = rrf_fuse([dense_hits, sparse_hits], [route.dense_weight, route.sparse_weight],
                        k=self.s.rrf_k, top_n=k, labels=["dense", "sparse"])
        return RetrievalResult(hits, route, mode, routed)
