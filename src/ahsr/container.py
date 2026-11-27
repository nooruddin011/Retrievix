"""Wires settings, encoders, store, router, retriever, LLM, tools and agent together."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ahsr.agent.graph import build_agent
from ahsr.agent.llm import build_llm
from ahsr.config import Settings, get_settings
from ahsr.ingestion.ingest import sync_directory
from ahsr.models import build_dense, build_sparse
from ahsr.models.cached import CachedEncoder
from ahsr.retrieval.hybrid import HybridRetriever
from ahsr.retrieval.store import HybridStore
from ahsr.router.classifier import build_router
from ahsr.tools.external import build_tools

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    dense: Any
    sparse: Any
    store: HybridStore
    router: Any
    retriever: HybridRetriever
    llm: Any
    tools: list
    agent: Any


def build_container(settings: Settings | None = None, auto_ingest: bool | None = None) -> Container:
    s = settings or get_settings()
    dense = CachedEncoder(build_dense(s), s.embed_cache_size)
    sparse = CachedEncoder(build_sparse(s), s.embed_cache_size)
    store, router = HybridStore(s), build_router(s)
    store.wait_ready(s.qdrant_wait_s)
    retriever = HybridRetriever(store, dense, sparse, router, s)
    llm, tools = build_llm(s), build_tools(s)
    c = Container(s, dense, sparse, store, router, retriever, llm, tools, build_agent(retriever, llm, tools, s))
    if (s.auto_ingest if auto_ingest is None else auto_ingest) and Path(s.docs_dir).is_dir():
        rep = sync_directory(store, dense, sparse, s.docs_dir)          # incremental: embeds only what changed
        log.info("index synced from %s: %d chunks (+%d new, -%d removed%s)", s.docs_dir, rep.chunks,
                 rep.added, rep.removed, ", rebuilt" if rep.rebuilt else "")
    return c


@lru_cache(maxsize=1)
def get_container() -> Container:
    return build_container()
