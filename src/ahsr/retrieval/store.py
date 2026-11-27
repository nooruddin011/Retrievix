"""Qdrant wrapper: one collection, two named vectors (dense + sparse)."""
from __future__ import annotations

import logging
import time

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ahsr.config import Settings
from ahsr.types import Chunk, Hit, SparseVec

log = logging.getLogger(__name__)
DENSE, SPARSE = "dense", "sparse"


def _qsparse(sv: SparseVec) -> qm.SparseVector:
    return qm.SparseVector(indices=sv.indices, values=sv.values)


class HybridStore:
    def __init__(self, s: Settings):
        self.name = s.collection
        url = s.qdrant_url
        if url == ":memory:":
            self.client = QdrantClient(":memory:")
        elif url.startswith("path:"):
            self.client = QdrantClient(path=url[5:])
        else:
            self.client = QdrantClient(url=url, api_key=s.qdrant_api_key or None)

    # -- lifecycle -------------------------------------------------------------------------------
    def wait_ready(self, timeout_s: float = 30.0) -> None:
        """Block until Qdrant answers (containers often start before their dependency is ready)."""
        deadline, delay = time.monotonic() + timeout_s, 0.5
        while True:
            try:
                self.client.get_collections()
                return
            except Exception as e:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"vector store not reachable: {e}") from e
                log.info("waiting for vector store (%s)", e)
                time.sleep(delay)
                delay = min(delay * 1.6, 4.0)

    def exists(self) -> bool:
        return bool(self.client.collection_exists(self.name))

    def drop(self) -> None:
        if self.exists():
            self.client.delete_collection(self.name)

    def compatible(self, dense_dim: int) -> bool:
        """False if the existing collection was built with a different dense vector size."""
        if not self.exists():
            return True
        try:
            vectors = self.client.get_collection(self.name).config.params.vectors
            return int(vectors[DENSE].size) == int(dense_dim)
        except Exception:                                       # unknown layout: don't guess
            return False

    def ensure_collection(self, dense_dim: int, recreate: bool = False) -> None:
        if recreate:
            self.drop()
        if not self.exists():
            self.client.create_collection(
                self.name,
                vectors_config={DENSE: qm.VectorParams(size=dense_dim, distance=qm.Distance.COSINE)},
                sparse_vectors_config={SPARSE: qm.SparseVectorParams()},
            )

    def count(self) -> int:
        if not self.exists():
            return 0
        return self.client.count(self.name, exact=True).count

    # -- writes ----------------------------------------------------------------------------------
    def upsert(self, chunks: list[Chunk], dense: np.ndarray, sparse: list[SparseVec]) -> None:
        if not chunks:
            return
        points = [
            qm.PointStruct(id=c.id, vector={DENSE: dense[i].tolist(), SPARSE: _qsparse(sparse[i])},
                           payload={**c.metadata, "text": c.text})
            for i, c in enumerate(chunks)
        ]
        self.client.upsert(self.name, points=points, wait=True)

    def delete_ids(self, ids: list[str]) -> None:
        if ids and self.exists():
            self.client.delete(self.name, points_selector=qm.PointIdsList(points=list(ids)), wait=True)

    # -- inventory -------------------------------------------------------------------------------
    def ids_by_source(self, source: str | None = None) -> dict[str, set[str]]:
        """Indexed chunk ids grouped by document, optionally restricted to one document."""
        out: dict[str, set[str]] = {}
        if not self.exists():
            return out
        flt = None if source is None else qm.Filter(must=[
            qm.FieldCondition(key="source", match=qm.MatchValue(value=source))])
        offset = None
        while True:
            points, offset = self.client.scroll(self.name, scroll_filter=flt, limit=256, offset=offset,
                                                with_payload=["source"], with_vectors=False)
            for p in points:
                out.setdefault(str((p.payload or {}).get("source", "")), set()).add(str(p.id))
            if offset is None:
                return out

    # -- reads -----------------------------------------------------------------------------------
    @staticmethod
    def _hits(points, origin: str) -> list[Hit]:
        return [Hit(id=str(p.id), score=float(p.score), text=p.payload.get("text", ""),
                    payload=p.payload, origin=origin) for p in points]

    def _query(self, **kw):
        try:
            return self.client.query_points(self.name, with_payload=True, **kw)
        except Exception:
            if not self.exists():                               # nothing indexed yet: empty, not a 500
                return None
            raise

    def dense_search(self, vec: np.ndarray, limit: int) -> list[Hit]:
        r = self._query(query=vec.tolist(), using=DENSE, limit=limit)
        return self._hits(r.points, "dense") if r else []

    def sparse_search(self, sv: SparseVec, limit: int) -> list[Hit]:
        if not sv.indices:
            return []
        r = self._query(query=_qsparse(sv), using=SPARSE, limit=limit)
        return self._hits(r.points, "sparse") if r else []

    def fusion_search(self, vec: np.ndarray, sv: SparseVec, limit: int, pool: int) -> list[Hit]:
        """Server-side RRF (unweighted) via Qdrant's Query API prefetch."""
        r = self._query(
            prefetch=[qm.Prefetch(query=vec.tolist(), using=DENSE, limit=pool),
                      qm.Prefetch(query=_qsparse(sv), using=SPARSE, limit=pool)],
            query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=limit)
        return self._hits(r.points, "hybrid") if r else []
