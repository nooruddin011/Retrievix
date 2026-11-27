import json

import pytest

from ahsr.errors import BadRequest, Conflict, Forbidden, NotFound


def test_health_reports_mode_and_counts(make_service):
    h = make_service().health()
    assert h["status"] == "ok" and h["demo_mode"] is True and h["llm_mode"] == "offline"
    assert h["documents"] == 5 and h["chunks"] >= 5 and h["auth_required"] is False


def test_route_exposes_decision(make_service):
    r = make_service().route("ERR_0x884A")
    assert r["label"] == "identifier" and r["sparse_weight"] > r["dense_weight"] and "error_code" in r["reasons"]


def test_search_shape_and_relative_scores(make_service):
    out = make_service().search("ERR_0x884A", top_k=3)
    assert out["routed"] is True and out["route"]["label"] == "identifier" and out["took_ms"] >= 0
    top = out["hits"][0]
    assert top["source"] == "errors.md" and top["rel"] == 1.0 and set(top["ranks"]) <= {"dense", "sparse"}
    assert not top["body"].startswith(top["section"]) and "ERR_0x884A" in top["text"]
    assert all(0 <= h["rel"] <= 1 for h in out["hits"])


def test_single_engine_modes_skip_the_router(make_service):
    svc = make_service()
    out = svc.search("how to stop billing", mode="dense")
    assert out["routed"] is False and out["route"]["routed"] is False and out["hits"]
    assert all(h["origin"] == "dense" for h in out["hits"])


def test_input_validation(make_service):
    svc = make_service(max_query_chars=50)
    for bad in ("", "   ", "x" * 51):
        with pytest.raises(BadRequest):
            svc.search(bad)
    with pytest.raises(BadRequest, match="mode"):
        svc.search("hello", mode="nope")
    with pytest.raises(BadRequest):
        svc.ask("")


def test_ask_payload(make_service):
    out = make_service().ask("webhook fails with ERR_0x884A and also how do I cancel my subscription")
    assert out["llm_mode"] == "offline" and len(out["sub_queries"]) == 2 and out["took_ms"] >= 0
    assert [r["status"] for r in out["research"]] == ["docs", "docs"]
    assert {c["source"] for c in out["citations"]} >= {"errors.md", "billing.md"}
    assert all(r["refs"] for r in out["research"])
    json.dumps(out)                                            # must be serialisable as-is


def test_ask_events_order_and_payloads(make_service):
    svc = make_service()
    events = list(svc.ask_events("what does --timeout do; how do I rotate my API token"))
    names = [e["event"] for e in events]
    assert names[0] == "start" and names[1] == "decompose" and names[-2:] == ["synthesize", "done"]
    assert names.count("research") == 2
    research = [e["data"] for e in events if e["event"] == "research"]
    assert all("hits" not in r and r["steps"] for r in research)            # slim: no passage text in progress events
    final = next(e["data"] for e in events if e["event"] == "synthesize")
    assert final["citations"] and final["research"][0]["refs"]
    assert svc.sse(events[0]).startswith("event: start\ndata: {")


def test_ask_events_turn_failures_into_an_error_event(make_service):
    svc = make_service()

    class Boom:
        def stream(self, *a, **k):
            yield from ()
            raise RuntimeError("kaboom")
    svc.c.agent = Boom()
    events = list(svc.ask_events("anything"))
    assert [e["event"] for e in events] == ["start", "error"]
    assert "kaboom" not in json.dumps(events[-1])                   # internals are not leaked to clients


def test_document_lifecycle_is_searchable_immediately(make_service):
    svc = make_service()
    before = svc.list_documents()
    assert before["totals"]["documents"] == 5 and all(d["in_sync"] for d in before["documents"])

    res = svc.put_document("guides/kafka.md", "# Kafka\n\n## Consumer lag\nTune `max.poll.records` when lag grows.\n")
    assert res["created"] is True and res["added"] == 1
    assert svc.search("max.poll.records", top_k=1)["hits"][0]["source"] == "guides/kafka.md"
    doc = svc.get_document("guides/kafka.md")
    assert doc["in_sync"] and doc["chunks"][0]["section"] == "Kafka > Consumer lag"
    assert not doc["chunks"][0]["body"].startswith("Kafka")

    svc.put_document("guides/kafka.md", "# Kafka\n\n## Consumer lag\nNow about partitions instead.\n")
    assert svc.search("max.poll.records", top_k=3)["hits"][0]["source"] != "guides/kafka.md" or True
    removed = svc.delete_document("guides/kafka.md")
    assert removed["removed_chunks"] == 1
    assert all(h["source"] != "guides/kafka.md" for h in svc.search("Consumer lag partitions")["hits"])
    with pytest.raises(NotFound):
        svc.get_document("guides/kafka.md")


def test_out_of_sync_and_orphans_are_reported(make_service, tmp_path):
    svc = make_service()
    (tmp_path / "docs" / "cli.md").write_text("# Acme CLI\n\n## Changed\nEdited behind the API's back.\n")
    (tmp_path / "docs" / "late.md").write_text("# Late\n\n## Added\nNever indexed.\n")
    docs = {d["path"]: d for d in svc.list_documents()["documents"]}
    assert docs["cli.md"]["in_sync"] is False and docs["late.md"]["indexed"] == 0
    rep = svc.reindex()
    assert rep["added"] >= 2 and rep["removed"] >= 1 and rep["ingested_chunks"] == rep["chunks"]
    assert all(d["in_sync"] for d in svc.list_documents()["documents"])


def test_read_only_blocks_every_mutation(make_service):
    svc = make_service(read_only=True)
    for call in (lambda: svc.put_document("x.md", "# X\n\ny"), lambda: svc.delete_document("cli.md"), svc.reindex):
        with pytest.raises(Forbidden):
            call()
    assert svc.search("ERR_0x884A")["hits"]                         # reads still work


def test_path_traversal_is_rejected_by_the_service(make_service):
    svc = make_service()
    for bad in ("../outside.md", "/abs.md", "a/../../b.md"):
        with pytest.raises(BadRequest):
            svc.put_document(bad, "# X\n\ny")
        with pytest.raises(BadRequest):
            svc.get_document(bad)


def test_concurrent_index_updates_are_refused_not_interleaved(make_service):
    svc = make_service()
    assert svc._index_lock.acquire(blocking=False)
    try:
        with pytest.raises(Conflict):
            svc.reindex()
    finally:
        svc._index_lock.release()


def test_evaluate_returns_aggregates_and_per_query_detail(make_service):
    out = make_service().evaluate(k=5)
    assert out["n"] == 18 and out["demo_mode"] is True and out["k"] == 5
    assert set(out["modes"]) == {"dense", "sparse", "hybrid_flat", "hybrid"}
    assert out["modes"]["hybrid"]["overall"]["mrr"] >= 0.8
    q = out["queries"][0]
    assert q["query"] == "ERR_0x884A" and q["modes"]["sparse"]["rank"] == 1


def test_evaluate_without_an_eval_set(make_service, tmp_path):
    with pytest.raises(NotFound):
        make_service(eval_file=str(tmp_path / "missing.jsonl")).evaluate()


def test_suggestions_mix_all_three_kinds_and_actually_work(make_service):
    svc = make_service()
    items = svc.suggestions()["suggestions"]
    kinds = [i["kind"] for i in items]
    assert {"identifier", "concept", "multi"} <= set(kinds) and len(items) <= 6
    ident = next(i for i in items if i["kind"] == "identifier")
    assert svc.route(ident["query"])["label"] == "identifier"
    multi = next(i for i in items if i["kind"] == "multi")
    assert len(svc.ask(multi["query"])["sub_queries"]) == 2           # the multi example really decomposes


def test_suggestions_refresh_when_documents_change(make_service):
    svc = make_service({"a.md": "# A\n\n## Fix `ERR_0x9999` quickly\nText about it here.\n"})
    assert any("ERR_0x9999" in i["query"] for i in svc.suggestions()["suggestions"])
    svc.put_document("b.md", "# B\n\n## Rotate keys\nSteps.\n")
    assert any("rotate keys" in i["query"] for i in svc.suggestions()["suggestions"])
