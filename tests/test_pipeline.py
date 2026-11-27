"""End-to-end with offline encoders, in-memory Qdrant and the offline LLM."""
from fastapi.testclient import TestClient

from ahsr.agent.graph import build_agent
from ahsr.agent.llm import OfflineLLM
from ahsr.eval.evaluate import evaluate
from ahsr.types import Hit


def test_identifier_query_finds_exact_doc(container):
    res = container.retriever.search("ERR_0x884A", top_k=3)
    assert res.route.label == "identifier"
    assert res.hits[0].source == "errors.md" and "ERR_0x884A" in res.hits[0].text


def test_conceptual_query_bridges_vocabulary_gap(container):
    res = container.retriever.search("how to stop billing", top_k=3)
    assert res.route.label == "conceptual"
    assert "billing.md" in [h.source for h in res.hits]


def test_all_modes_run(container):
    for m in ("hybrid", "hybrid_flat", "hybrid_server", "dense", "sparse"):
        assert container.retriever.search("--dry-run", top_k=3, mode=m).hits


def test_eval_hybrid_is_competitive(container):
    import json, pathlib
    qs = [json.loads(x) for x in pathlib.Path("data/eval/queries.jsonl").read_text().splitlines() if x.strip()]
    rep = evaluate(container.retriever, qs, k=5)
    assert rep["hybrid"]["overall"]["mrr"] >= 0.8
    assert rep["hybrid"]["overall"]["mrr"] >= max(rep["dense"]["overall"]["mrr"], rep["sparse"]["overall"]["mrr"]) - 0.05


def test_agent_decomposes_and_answers_multi_part(container):
    out = container.agent.invoke({"question": "webhook fails with ERR_0x884A and also how do I cancel my subscription"})
    assert len(out["sub_queries"]) == 2
    srcs = {c["source"] for c in out["citations"]}
    assert {"errors.md", "billing.md"} <= srcs
    assert "[1]" in out["answer"]


class ScriptedLLM(OfflineLLM):
    """Grader says 'irrelevant' for the first N calls so we can exercise the control flow."""
    def __init__(self, fail_first):
        self.calls, self.fail_first = 0, fail_first

    def grade(self, query, hits):
        self.calls += 1
        return [self.calls > self.fail_first] * len(hits)


class StubTool:
    name = "code_search"
    def search(self, query, k=3):
        return [Hit(id="code:x", score=1.0, text="def handler(): ...", payload={"source": "app.py:10", "title": "app.py"}, origin="code")]


def test_self_correction_rewrites_then_succeeds(container):
    agent = build_agent(container.retriever, ScriptedLLM(fail_first=1), [], container.settings)
    out = agent.invoke({"question": "how to stop billing"})
    assert out["results"][0]["attempts"] == 1 and out["results"][0]["status"] == "docs"
    assert any("rewrite" in t for t in out["trace"])


def test_tool_fallback_after_retries_exhausted(container):
    agent = build_agent(container.retriever, ScriptedLLM(fail_first=99), [StubTool()], container.settings)
    out = agent.invoke({"question": "something undocumented"})
    r = out["results"][0]
    assert r["attempts"] == container.settings.max_rewrites and r["status"] == "tools"
    assert out["citations"][0]["source"] == "app.py:10"


def test_api_endpoints(container):
    from ahsr.api.main import app
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        s = client.post("/search", json={"query": "ERR_0x1F02", "top_k": 2}).json()
        assert s["hits"][0]["source"] == "errors.md" and s["route"]["label"] == "identifier"
        a = client.post("/ask", json={"question": "how to stop billing"}).json()
        assert a["citations"] and a["research"][0]["status"] == "docs"
        with client.stream("POST", "/ask/stream", json={"question": "--dry-run"}) as r:
            body = "".join(r.iter_text())
        assert "event: decompose" in body and "event: synthesize" in body and "event: done" in body
