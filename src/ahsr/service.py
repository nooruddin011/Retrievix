"""Framework-free application service. The FastAPI layer is a thin adapter over this class.

Keeping request handling here (validation, serialisation, locking, index maintenance) makes it
testable without an HTTP stack and keeps the API module declarative.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from ahsr import __version__
from ahsr.agent.graph import summarize_result
from ahsr.container import Container, get_container
from ahsr.errors import BadRequest, Conflict, Forbidden, NotFound, ServiceError, Unavailable
from ahsr.eval.evaluate import evaluate_detailed
from ahsr.ingestion.chunker import chunk_markdown
from ahsr.ingestion.ingest import load_chunks, remove_document, sync_directory, sync_document
from ahsr.ingestion.library import DocumentLibrary, normalize_doc_path
from ahsr.retrieval.hybrid import MODES
from ahsr.suggest import suggest_queries

log = logging.getLogger(__name__)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class SearchService:
    def __init__(self, container: Container):
        self.c = container
        self.s = container.settings
        self.library = DocumentLibrary(self.s.docs_dir, self.s.max_doc_bytes, self.s.max_documents)
        self.started_at = time.time()
        self._index_lock = threading.Lock()
        self._eval_lock = threading.Lock()
        self._suggestions: tuple[tuple, list[dict]] | None = None

    # -- validation ------------------------------------------------------------------------------
    def clean_text(self, text: str, field: str = "query") -> str:
        text = (text or "").strip()
        if not text:
            raise BadRequest(f"The {field} is empty.", code="empty_query")
        if len(text) > self.s.max_query_chars:
            raise BadRequest(f"The {field} is too long (limit {self.s.max_query_chars} characters).",
                             code="query_too_long")
        return text

    def _writable(self) -> None:
        if self.s.read_only:
            raise Forbidden("This server is read-only: documents cannot be changed.", code="read_only")

    # -- status ----------------------------------------------------------------------------------
    def health(self) -> dict:
        info = {"app_name": self.s.app_name, "version": __version__,
                "encoder_backend": self.s.encoder_backend, "demo_mode": self.s.demo_mode,
                "llm": type(self.c.llm).__name__, "llm_mode": self.c.llm.mode,
                "tools": [t.name for t in self.c.tools], "auth_required": bool(self.s.api_key),
                "read_only": self.s.read_only, "max_query_chars": self.s.max_query_chars,
                "max_doc_bytes": self.s.max_doc_bytes, "uptime_s": int(time.time() - self.started_at)}
        try:
            info.update(status="ok", chunks=self.c.store.count(), documents=len(self.library.paths()))
        except Exception as e:
            log.error("health: vector store check failed: %s", e)
            info.update(status="degraded", chunks=None, documents=None, error="The vector store is unreachable.")
        return info

    # -- retrieval -------------------------------------------------------------------------------
    @staticmethod
    def _route_dict(route, routed: bool = True) -> dict:
        return {"label": route.label, "p_identifier": route.p_identifier, "sparse_weight": route.sparse_weight,
                "dense_weight": route.dense_weight, "reasons": list(route.reasons), "routed": routed}

    def route(self, query: str) -> dict:
        q = self.clean_text(query)
        return {"query": q, **self._route_dict(self.c.router.route(q))}

    def search(self, query: str, top_k: int = 5, mode: str = "hybrid") -> dict:
        q = self.clean_text(query)
        if mode not in MODES:
            raise BadRequest(f"mode must be one of {', '.join(MODES)}.", code="invalid_mode")
        t0 = time.perf_counter()
        try:
            res = self.c.retriever.search(q, top_k=top_k, mode=mode)
        except ServiceError:
            raise
        except Exception as e:
            log.exception("search failed")
            raise Unavailable("Search is temporarily unavailable. Check the vector store.") from e
        top = max((h.score for h in res.hits), default=0.0)
        hits = [{"id": h.id, "score": round(h.score, 5), "rel": round(h.score / top, 3) if top else 0.0,
                 "source": h.source, "section": h.title, "origin": h.origin, "ranks": h.ranks,
                 "text": h.text, "body": h.body} for h in res.hits]
        return {"query": q, "mode": res.mode, "routed": res.routed,
                "route": self._route_dict(res.route, res.routed), "hits": hits, "took_ms": _ms(t0)}

    # -- agent -----------------------------------------------------------------------------------
    def ask(self, question: str) -> dict:
        q = self.clean_text(question, "question")
        t0 = time.perf_counter()
        try:
            out = self.c.agent.invoke({"question": q})
        except Exception as e:
            log.exception("agent failed")
            raise Unavailable("The agent could not complete this question. Try again.") from e
        return {"question": q, "answer": out["answer"], "citations": out["citations"],
                "sub_queries": out["sub_queries"], "trace": out["trace"], "research": out["research"],
                "took_ms": _ms(t0), "llm_mode": self.c.llm.mode}

    def ask_events(self, question: str) -> Iterator[dict]:
        """Yield ``{"event", "data"}`` dicts as the graph progresses. Failures become an ``error`` event."""
        q = self.clean_text(question, "question")
        t0 = time.perf_counter()
        yield {"event": "start", "data": {"question": q, "llm_mode": self.c.llm.mode}}
        try:
            for update in self.c.agent.stream({"question": q}, stream_mode="updates"):
                for node, payload in update.items():
                    for p in (payload if isinstance(payload, list) else [payload]):
                        if not isinstance(p, dict):
                            continue
                        if node == "decompose":
                            yield {"event": "decompose", "data": {"sub_queries": p["sub_queries"], "trace": p["trace"]}}
                        elif node == "research":
                            for r in p["results"]:
                                yield {"event": "research", "data": summarize_result(r)}
                        elif node == "synthesize":
                            yield {"event": "synthesize", "data": {
                                "answer": p["answer"], "citations": p["citations"], "research": p["research"],
                                "took_ms": _ms(t0), "llm_mode": self.c.llm.mode}}
            yield {"event": "done", "data": {"took_ms": _ms(t0)}}
        except Exception:
            log.exception("agent stream failed")
            yield {"event": "error", "data": {"code": "agent_failed",
                                              "message": "The agent hit an unexpected error. Try again."}}

    @staticmethod
    def sse(ev: dict) -> str:
        return f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str, ensure_ascii=False)}\n\n"

    def suggestions(self) -> dict:
        sig = tuple((i.path, i.bytes, i.modified) for i in self.library.list())
        if self._suggestions and self._suggestions[0] == sig:
            return {"suggestions": self._suggestions[1]}
        root = Path(self.s.docs_dir)
        items = suggest_queries(load_chunks(root)) if root.is_dir() else []
        self._suggestions = (sig, items)
        return {"suggestions": items}

    # -- documents -------------------------------------------------------------------------------
    def _indexed(self) -> dict[str, set[str]]:
        try:
            return self.c.store.ids_by_source()
        except Exception:
            log.warning("could not read the index inventory", exc_info=True)
            return {}

    def list_documents(self) -> dict:
        indexed = self._indexed()
        docs, total_chunks, total_indexed = [], 0, 0
        for info in self.library.list():
            wanted = {c.id for c in chunk_markdown(self.library.read(info.path), info.path)}
            have = indexed.get(info.path, set())
            total_chunks += len(wanted)
            total_indexed += len(have & wanted)
            docs.append({"path": info.path, "title": info.title, "bytes": info.bytes, "modified": info.modified,
                         "chunks": len(wanted), "indexed": len(have & wanted), "in_sync": have == wanted})
        orphans = sorted(set(indexed) - {d["path"] for d in docs})
        return {"documents": docs, "orphaned": orphans, "read_only": self.s.read_only,
                "totals": {"documents": len(docs), "chunks": total_chunks, "indexed": total_indexed}}

    def get_document(self, path: str) -> dict:
        info = self.library.stat(path)
        text = self.library.read(path)
        chunks = chunk_markdown(text, info.path)
        have = self._indexed().get(info.path, set())
        return {"path": info.path, "title": info.title, "bytes": info.bytes, "modified": info.modified,
                "markdown": text, "in_sync": have == {c.id for c in chunks},
                "chunks": [{"id": c.id, "section": c.metadata["section"],
                            "body": c.text[len(c.metadata["section"]):].lstrip("\n"), "chars": c.metadata["chars"]}
                           for c in chunks]}

    def _locked_index(self):
        if not self._index_lock.acquire(blocking=False):
            raise Conflict("The index is being updated. Try again in a moment.", code="index_busy")

    def put_document(self, path: str, content: str) -> dict:
        self._writable()
        rel = normalize_doc_path(path)
        self._locked_index()
        try:
            created = self.library.write(rel, content)
            self._suggestions = None
            try:
                added, removed = sync_document(self.c.store, self.c.dense, self.c.sparse, self.s.docs_dir, rel, content)
            except Exception as e:
                log.exception("indexing %s failed", rel)
                raise Unavailable("The document was saved but could not be indexed. Use Re-index to retry.",
                                  code="index_failed") from e
        finally:
            self._index_lock.release()
        return {"path": rel, "created": created, "added": added, "removed": removed,
                "chunks": len(chunk_markdown(content, rel))}

    def delete_document(self, path: str) -> dict:
        self._writable()
        rel = normalize_doc_path(path)
        self._locked_index()
        try:
            self.library.delete(rel)
            self._suggestions = None
            removed = remove_document(self.c.store, rel)
        finally:
            self._index_lock.release()
        return {"path": rel, "removed_chunks": removed}

    def reindex(self, full: bool = False) -> dict:
        self._writable()
        self._locked_index()
        try:
            try:
                rep = sync_directory(self.c.store, self.c.dense, self.c.sparse, self.s.docs_dir, full=full)
            except FileNotFoundError as e:
                raise NotFound(str(e), code="docs_dir_missing") from e
            self._suggestions = None
        finally:
            self._index_lock.release()
        return {**rep.as_dict(), "ingested_chunks": rep.chunks, "docs_dir": self.s.docs_dir}

    # -- evaluation ------------------------------------------------------------------------------
    def evaluate(self, k: int = 5) -> dict:
        path = Path(self.s.eval_file)
        if not path.is_file():
            raise NotFound(f"No evaluation set found at {self.s.eval_file}.", code="eval_set_missing")
        if not self._eval_lock.acquire(blocking=False):
            raise Conflict("An evaluation is already running.", code="eval_busy")
        try:
            queries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            t0 = time.perf_counter()
            rep = evaluate_detailed(self.c.retriever, queries, k)
        except (ValueError, KeyError) as e:
            raise BadRequest(f"The evaluation set is malformed: {e}", code="eval_set_invalid") from e
        finally:
            self._eval_lock.release()
        return {**rep, "n": len(queries), "demo_mode": self.s.demo_mode, "took_ms": _ms(t0)}


@lru_cache(maxsize=1)
def get_service() -> SearchService:
    return SearchService(get_container())
