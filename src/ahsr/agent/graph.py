"""LangGraph workflow.

Top-level graph:   decompose --(Send fan-out)--> research x N (parallel) --> synthesize
Research subgraph: retrieve -> grade -> [relevant: finish | retries left: rewrite -> retrieve | else: tools -> finish]

Research outcome (``status``):
  docs  - at least one retrieved passage was graded relevant
  tools - documentation fell short but an external tool (code search, issues) found something
  weak  - nothing was confirmed relevant; the closest passages are kept and flagged as low confidence
  none  - nothing at all was found
"""
from __future__ import annotations

import logging
import operator
import time
from dataclasses import asdict
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ahsr.config import Settings
from ahsr.types import Hit

log = logging.getLogger(__name__)
EVIDENCE_PER_QUESTION = 3
CITATION_CHARS = 1200


class SubState(TypedDict, total=False):
    sub_query: str
    current_query: str
    attempts: int
    tried: list[str]
    hits: list[Hit]
    good: list[Hit]
    tool_hits: list[Hit]
    weak_hits: list[Hit]
    route: dict
    trace: list[str]
    steps: list[dict]              # structured twin of `trace`, consumed by the UI
    status: str                    # docs | tools | weak | none


class AgentState(TypedDict, total=False):
    question: str
    sub_queries: list[str]
    results: Annotated[list[dict], operator.add]     # fan-in from parallel branches
    trace: Annotated[list[str], operator.add]
    answer: str
    citations: list[dict]
    research: list[dict]           # per-sub-question summaries (ordered, with citation refs)


def _short(q: str, n: int = 60) -> str:
    return q if len(q) <= n else q[: n - 1] + "…"


def build_research_graph(retriever, llm, tools: list, s: Settings):
    def retrieve(st: SubState):
        res = retriever.search(st["current_query"], top_k=s.top_k)
        line = (f"retrieve[try {st['attempts'] + 1}] '{_short(st['current_query'])}' -> "
                f"route={res.route.label} (sparse_w={res.route.sparse_weight}) hits={len(res.hits)}")
        step = {"kind": "retrieve", "attempt": st["attempts"] + 1, "query": st["current_query"],
                "route": res.route.label, "sparse_weight": res.route.sparse_weight,
                "dense_weight": res.route.dense_weight, "hits": len(res.hits)}
        return {"hits": res.hits, "route": asdict(res.route),
                "tried": st.get("tried", []) + [st["current_query"]],
                "trace": st.get("trace", []) + [line], "steps": st.get("steps", []) + [step]}

    def grade(st: SubState):
        flags = llm.grade(st["current_query"], st["hits"])
        good = [h for h, f in zip(st["hits"], flags) if f]
        return {"good": good, "trace": st["trace"] + [f"grade -> {len(good)}/{len(st['hits'])} relevant"],
                "steps": st["steps"] + [{"kind": "grade", "relevant": len(good), "total": len(st["hits"])}]}

    def after_grade(st: SubState) -> str:
        if st["good"]:
            return "finish"
        return "rewrite" if st["attempts"] < s.max_rewrites else "tools"

    def rewrite(st: SubState):
        new = llm.rewrite(st["sub_query"], st["tried"], st["hits"])
        if new.strip().lower() in {t.lower() for t in st["tried"]}:
            new = f"{new} documentation"                     # force a genuinely different query
        return {"current_query": new, "attempts": st["attempts"] + 1,
                "trace": st["trace"] + [f"rewrite -> '{_short(new)}'"],
                "steps": st["steps"] + [{"kind": "rewrite", "query": new}]}

    def use_tools(st: SubState):
        hits: list[Hit] = []
        failed: list[str] = []
        # identifier-style queries look in code first, otherwise in issues first
        ordered = sorted(tools, key=lambda t: (t.name != "code_search")
                         if st.get("route", {}).get("label") == "identifier" else (t.name == "code_search"))
        for t in ordered:
            try:
                hits += t.search(st["sub_query"], 3)
            except Exception as e:                          # one broken tool must not sink the question
                log.warning("tool %s failed: %s", t.name, e)
                failed.append(t.name)
        names = ", ".join(t.name for t in ordered) or "none configured"
        return {"tool_hits": hits,
                "trace": st["trace"] + [f"tools[{names}] -> {len(hits)} results"],
                "steps": st["steps"] + [{"kind": "tools", "tools": [t.name for t in ordered],
                                         "results": len(hits), "failed": failed}]}

    def finish(st: SubState):
        if st.get("good"):
            status = "docs"
        elif st.get("tool_hits"):
            status = "tools"
        elif st.get("hits"):
            status = "weak"
        else:
            status = "none"
        out = {"status": status, "trace": st["trace"] + [f"finish ({status})"],
               "steps": st["steps"] + [{"kind": "finish", "status": status}]}
        if status == "weak":
            out["weak_hits"] = st["hits"][:EVIDENCE_PER_QUESTION]
        return out

    g = StateGraph(SubState)
    for name, fn in [("retrieve", retrieve), ("grade", grade), ("rewrite", rewrite),
                     ("tools", use_tools), ("finish", finish)]:
        g.add_node(name, fn)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, {"finish": "finish", "rewrite": "rewrite", "tools": "tools"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("tools", "finish")
    g.add_edge("finish", END)
    return g.compile()


def _hit_dict(h: Hit) -> dict:
    return {"id": h.id, "score": h.score, "text": h.text, "body": h.body, "source": h.source,
            "title": h.title, "section": str(h.payload.get("section") or ""),
            "origin": h.origin, "ranks": h.ranks}


def _evidence_hits(r: dict) -> list[dict]:
    key = {"docs": "hits", "tools": "tool_hits", "weak": "weak_hits"}.get(r["status"])
    return (r.get(key) or [])[:EVIDENCE_PER_QUESTION] if key else []


def build_evidence(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Number evidence globally so citations like [1] are consistent across sub-questions."""
    citations: list[dict] = []
    index: dict[str, int] = {}
    view = []
    for r in results:
        low = r["status"] == "weak"
        ev = []
        for h in _evidence_hits(r):
            if h["id"] not in index:
                index[h["id"]] = len(citations) + 1
                citations.append({"n": index[h["id"]], "source": h["source"], "title": h["title"],
                                  "section": h.get("section", ""), "origin": h["origin"],
                                  "text": h["body"][:CITATION_CHARS], "low_confidence": low})
            elif not low:
                citations[index[h["id"]] - 1]["low_confidence"] = False   # confirmed elsewhere
            ev.append({"n": index[h["id"]], "source": h["source"], "section": h.get("section", ""),
                       "text": h["body"], "low_confidence": low})
        view.append({**r, "evidence": ev, "refs": [e["n"] for e in ev]})
    return view, citations


def summarize_result(r: dict, refs: list[int] | None = None) -> dict:
    """Compact, JSON-friendly description of one researched sub-question (no passage text)."""
    out = {"sub_query": r["sub_query"], "final_query": r["final_query"], "attempts": r["attempts"],
           "status": r["status"], "route": r.get("route", {}), "steps": r.get("steps", []),
           "hit_count": len(_evidence_hits(r)), "took_ms": r.get("took_ms", 0)}
    if refs is not None:
        out["refs"] = refs
    return out


def build_agent(retriever, llm, tools: list, s: Settings):
    research_graph = build_research_graph(retriever, llm, tools, s)

    def decompose(st: AgentState):
        subs = [q for q in llm.decompose(st["question"], s.max_sub_queries) if q.strip()][: s.max_sub_queries]
        subs = subs or [st["question"]]
        return {"sub_queries": subs, "trace": [f"decompose -> {len(subs)} sub-quer{'y' if len(subs) == 1 else 'ies'}"]}

    def fan_out(st: AgentState):
        return [Send("research", {"sub_query": q, "current_query": q, "attempts": 0, "tried": [],
                                  "trace": [], "steps": []}) for q in st["sub_queries"]]

    def research(st: SubState):
        t0 = time.perf_counter()
        out = research_graph.invoke(st)
        result = {"sub_query": st["sub_query"], "final_query": out["current_query"],
                  "attempts": out["attempts"], "status": out["status"], "route": out.get("route", {}),
                  "steps": out.get("steps", []), "took_ms": int((time.perf_counter() - t0) * 1000),
                  "hits": [_hit_dict(h) for h in out.get("good", [])],
                  "tool_hits": [_hit_dict(h) for h in out.get("tool_hits", [])],
                  "weak_hits": [_hit_dict(h) for h in out.get("weak_hits", [])]}
        return {"results": [result], "trace": [f"[{_short(st['sub_query'], 40)}] {t}" for t in out["trace"]]}

    def synthesize(st: AgentState):
        order = {q: i for i, q in enumerate(st["sub_queries"])}
        results = sorted(st["results"], key=lambda r: order.get(r["sub_query"], 0))
        view, citations = build_evidence(results)
        return {"answer": llm.synthesize(st["question"], view), "citations": citations,
                "research": [summarize_result(r, r["refs"]) for r in view],
                "trace": [f"synthesize -> {len(citations)} citations"]}

    g = StateGraph(AgentState)
    g.add_node("decompose", decompose)
    g.add_node("research", research)
    g.add_node("synthesize", synthesize)
    g.add_edge(START, "decompose")
    g.add_conditional_edges("decompose", fan_out, ["research"])
    g.add_edge("research", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()
