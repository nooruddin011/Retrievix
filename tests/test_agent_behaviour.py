"""Agent control-flow details the UI relies on: step records, weak matches, tool isolation, snippets."""
from ahsr.agent.graph import build_agent, build_evidence
from ahsr.agent.llm import OfflineLLM, _snippet
from ahsr.types import Hit


class Rejecting(OfflineLLM):
    def grade(self, query, hits):
        return [False] * len(hits)


class ExplodingTool:
    name = "github_issues"

    def search(self, query, k=3):
        raise RuntimeError("rate limited")


class GoodTool:
    name = "code_search"

    def search(self, query, k=3):
        return [Hit(id="code:1", score=1.0, text="def f(): ...", payload={"source": "a.py:1", "title": "a.py"}, origin="code")]


def test_steps_are_structured_and_ordered(container):
    out = container.agent.invoke({"question": "how to stop billing"})
    steps = out["research"][0]["steps"]
    assert [s["kind"] for s in steps] == ["retrieve", "grade", "finish"]
    assert steps[0]["route"] == "conceptual" and steps[0]["hits"] > 0
    assert steps[1]["relevant"] >= 1 and steps[2]["status"] == "docs"
    assert out["research"][0]["refs"] and out["research"][0]["hit_count"] == len(out["research"][0]["refs"])


def test_rewrite_steps_are_recorded(container):
    agent = build_agent(container.retriever, Rejecting(), [], container.settings)
    kinds = [s["kind"] for s in agent.invoke({"question": "how to stop billing"})["research"][0]["steps"]]
    assert kinds == ["retrieve", "grade", "rewrite", "retrieve", "grade", "rewrite", "retrieve", "grade", "tools", "finish"]


def test_nothing_relevant_and_no_tools_keeps_closest_matches_as_low_confidence(container):
    agent = build_agent(container.retriever, Rejecting(), [], container.settings)
    out = agent.invoke({"question": "how to stop billing"})
    r = out["research"][0]
    assert r["status"] == "weak" and r["hit_count"] > 0
    assert out["citations"] and all(c["low_confidence"] for c in out["citations"])
    assert "closest matches" in out["answer"].lower()          # the answer says so instead of pretending


def test_failing_tool_does_not_sink_the_question(container):
    agent = build_agent(container.retriever, Rejecting(), [ExplodingTool(), GoodTool()], container.settings)
    out = agent.invoke({"question": "something undocumented"})
    r = out["research"][0]
    assert r["status"] == "tools"
    tool_step = next(s for s in r["steps"] if s["kind"] == "tools")
    assert tool_step["failed"] == ["github_issues"] and tool_step["results"] == 1


def test_citations_carry_passage_text_without_breadcrumb(container):
    out = container.agent.invoke({"question": "ERR_0x884A"})
    c = out["citations"][0]
    assert c["source"] == "errors.md" and c["section"].startswith("Acme Cloud Error Reference")
    assert not c["text"].startswith(c["section"]) and "signature" in c["text"].lower()
    assert c["low_confidence"] is False


def test_evidence_numbering_is_global_and_deduplicated():
    h = lambda i: {"id": i, "source": f"{i}.md", "title": i, "section": "", "origin": "hybrid", "body": f"text {i}"}
    results = [{"status": "docs", "hits": [h("a"), h("b")], "tool_hits": [], "weak_hits": []},
               {"status": "docs", "hits": [h("b"), h("c")], "tool_hits": [], "weak_hits": []}]
    view, cites = build_evidence(results)
    assert [c["n"] for c in cites] == [1, 2, 3]
    assert view[0]["refs"] == [1, 2] and view[1]["refs"] == [2, 3]


def test_snippet_never_cuts_mid_word_or_leaks_code_fences():
    text = "Set the secret. " * 40 + "\n\n```python\nclient.rotate()\n```"
    s = _snippet(text, 120)
    assert len(s) <= 125 and "```" not in s and (s.endswith(".") or s.endswith("…"))
    assert _snippet("```python\nclient.subscriptions.terminate(id)\n```") == "`client.subscriptions.terminate(id)`"


def test_offline_decompose_keeps_bare_identifier_parts():
    llm = OfflineLLM()
    assert llm.decompose("--dry-run and also how do I rotate my API token", 4) == [
        "--dry-run", "how do I rotate my API token"]
    assert llm.decompose("ERR_0x884A", 4) == ["ERR_0x884A"]
    assert llm.decompose("how to stop billing", 4) == ["how to stop billing"]


def test_offline_grader_does_not_accept_a_different_error_code():
    mk = lambda t: Hit(id=t, score=1, text=t, payload={"source": "e.md"})
    hits = [mk("ERR_0x884A webhook signature mismatch"), mk("ERR_0x1F02 rate limit exceeded"), mk("unrelated billing text")]
    assert OfflineLLM().grade("ERR_0x884A", hits) == [True, False, False]
    assert OfflineLLM().grade("what does --timeout do", [mk("`--timeout 120` sets the timeout"), mk("--max-retries 5")]) == [True, False]
    # without a strict identifier the term-overlap fallback still works
    assert OfflineLLM().grade("how to stop billing", [mk("To cancel billing choose Terminate"), mk("ERR_0x1F02 rate limit")]) == [True, False]


def test_snippet_does_not_end_on_a_dangling_colon():
    text = "Unused credits are not refunded.\n\nVia the API:\n\n```python\nclient.terminate()\n```"
    assert _snippet(text) == "Unused credits are not refunded."
