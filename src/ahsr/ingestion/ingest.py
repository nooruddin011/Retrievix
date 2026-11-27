"""Chunk Markdown docs, encode with both pipelines, and keep the Qdrant index in sync.

Indexing is incremental and never leaves the index empty: new chunks are upserted first, then chunks
that no longer exist are deleted. Search keeps working while a re-index runs.
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ahsr.ingestion.chunker import chunk_markdown
from ahsr.types import Chunk

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    added: int = 0
    removed: int = 0
    unchanged: int = 0
    documents: int = 0
    chunks: int = 0
    rebuilt: bool = False
    took_ms: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def load_chunks(docs_dir: str | Path) -> list[Chunk]:
    root = Path(docs_dir)
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*.md")):
        chunks += chunk_markdown(path.read_text(encoding="utf-8", errors="replace"),
                                 source=path.relative_to(root).as_posix())
    return chunks


def _embed_upsert(store, dense, sparse, chunks: list[Chunk], batch: int) -> None:
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        texts = [c.text for c in part]
        store.upsert(part, dense.encode(texts), sparse.encode(texts))


def _reconcile(store, dense, sparse, wanted: list[Chunk], existing: set[str], batch: int) -> tuple[int, int]:
    """Make the index hold exactly ``wanted`` (within the scope that ``existing`` was read from)."""
    wanted_ids = {c.id for c in wanted}
    fresh = [c for c in wanted if c.id not in existing]
    stale = existing - wanted_ids
    _embed_upsert(store, dense, sparse, fresh, batch)          # upsert first, delete after: no empty window
    store.delete_ids(sorted(stale))
    return len(fresh), len(stale)


def sync_directory(store, dense, sparse, docs_dir: str | Path, batch: int = 32,
                   full: bool = False) -> SyncReport:
    """Bring the index in line with ``docs_dir``. ``full`` drops and rebuilds from scratch."""
    t0 = time.perf_counter()
    root = Path(docs_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"documents directory not found: {root}")
    chunks = load_chunks(root)
    report = SyncReport(documents=len({c.metadata["source"] for c in chunks}), chunks=len(chunks))
    if store.exists() and (full or not store.compatible(dense.dim)):
        if not full:
            log.warning("index vector size differs from the encoder (%d); rebuilding", dense.dim)
        store.drop()
        report.rebuilt = True
    store.ensure_collection(dense.dim)
    existing = set().union(*store.ids_by_source().values()) if store.count() else set()
    report.added, report.removed = _reconcile(store, dense, sparse, chunks, existing, batch)
    report.unchanged = len(chunks) - report.added
    report.took_ms = int((time.perf_counter() - t0) * 1000)
    return report


def sync_document(store, dense, sparse, docs_dir: str | Path, rel: str, text: str, batch: int = 32) -> tuple[int, int]:
    """Index one document. Returns (chunks added, chunks removed)."""
    wanted = chunk_markdown(text, source=rel)
    store.ensure_collection(dense.dim)
    existing = store.ids_by_source(rel).get(rel, set())
    return _reconcile(store, dense, sparse, wanted, existing, batch)


def remove_document(store, rel: str) -> int:
    if not store.exists():
        return 0
    ids = store.ids_by_source(rel).get(rel, set())
    store.delete_ids(sorted(ids))
    return len(ids)


def ingest_directory(store, dense, sparse, docs_dir: str | Path, batch: int = 32,
                     recreate: bool = True) -> int:
    """Back-compat wrapper: returns the number of chunks now indexed. ``recreate`` forces a full rebuild."""
    return sync_directory(store, dense, sparse, docs_dir, batch=batch, full=recreate).chunks


if __name__ == "__main__":
    from ahsr.container import build_container
    ap = argparse.ArgumentParser(description="Index the documents directory into Qdrant")
    ap.add_argument("--docs", default=None, help="documents directory (default: DOCS_DIR)")
    ap.add_argument("--full", action="store_true", help="drop the collection and rebuild from scratch")
    args = ap.parse_args()
    c = build_container(auto_ingest=False)
    rep = sync_directory(c.store, c.dense, c.sparse, args.docs or c.settings.docs_dir, full=args.full)
    print(f"'{c.settings.collection}': {rep.chunks} chunks from {rep.documents} documents "
          f"(+{rep.added} / -{rep.removed} / {rep.unchanged} unchanged{', rebuilt' if rep.rebuilt else ''}) "
          f"in {rep.took_ms} ms")
