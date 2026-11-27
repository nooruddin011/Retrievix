"""HTTP-layer behaviour: auth, rate limiting, error envelope, security headers, library routes, UI."""
import json

import pytest
from fastapi.testclient import TestClient

from ahsr.service import get_service


@pytest.fixture(scope="module")
def client():
    from ahsr.api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def svc():
    return get_service()


def test_ui_is_served_with_strict_csp(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert client.get("/css/tokens.css").status_code == 200 and client.get("/js/main.js").status_code == 200


def test_security_headers_and_request_id(client):
    r = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert client.get("/health", headers={"X-Request-Id": "bad id<script>"}).headers["x-request-id"] == "badidscript"


def test_health_contract(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and {"app_name", "version", "demo_mode", "llm_mode", "auth_required", "read_only"} <= set(h)


def test_error_envelope_for_validation_and_unknown_routes(client):
    r = client.post("/search", json={"query": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request" and r.json()["error"]["request_id"]
    assert client.post("/search", json={"query": "x", "top_k": 500}).status_code == 422
    r = client.post("/nope", json={})
    assert r.json()["error"]["code"] in {"not_found", "method_not_allowed"}
    r = client.post("/search", json={"query": "hello", "mode": "bogus"})
    assert r.status_code == 422


def test_overlong_query_is_a_clean_400(client, svc, monkeypatch):
    monkeypatch.setattr(svc.s, "max_query_chars", 20)
    r = client.post("/ask/stream", json={"question": "x" * 50})
    assert r.status_code == 400 and r.json()["error"]["code"] == "query_too_long"


def test_api_key_is_enforced_on_protected_routes_only(client, svc, monkeypatch):
    monkeypatch.setattr(svc.s, "api_key", "s3cret")
    assert client.get("/health").status_code == 200 and client.get("/health").json()["auth_required"] is True
    for method, url, body in [("post", "/search", {"query": "x"}), ("get", "/documents", None),
                              ("post", "/ask", {"question": "x"}), ("post", "/route", {"query": "x"})]:
        r = client.request(method, url, json=body)
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key", url
        assert client.request(method, url, json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    ok = client.post("/search", json={"query": "ERR_0x884A"}, headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["hits"]


def test_rate_limit_returns_429_with_retry_after(client, svc, monkeypatch):
    monkeypatch.setattr(svc.s, "rate_limit_per_min", 3)
    codes = [client.post("/search", json={"query": "billing"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    r = client.post("/search", json={"query": "billing"})
    assert r.headers["retry-after"].isdigit() and r.json()["error"]["code"] == "rate_limited"
    monkeypatch.setattr(svc.s, "rate_limit_per_min", 100000)


def test_route_and_search_contract(client):
    r = client.post("/route", json={"query": "--dry-run"}).json()
    assert r["label"] == "identifier" and r["routed"] is True
    s = client.post("/search", json={"query": "how to stop billing", "mode": "dense", "top_k": 2}).json()
    assert s["routed"] is False and len(s["hits"]) == 2 and s["hits"][0]["rel"] == 1.0


def test_stream_emits_ordered_sse_and_never_buffers_headers(client):
    with client.stream("POST", "/ask/stream", json={"question": "how to stop billing"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream") and r.headers["x-accel-buffering"] == "no"
        body = "".join(r.iter_text())
    names = [ln[7:] for ln in body.splitlines() if ln.startswith("event: ")]
    assert names[0] == "start" and names[-1] == "done" and "synthesize" in names
    data = next(ln for ln in body.splitlines() if ln.startswith("data: ") and '"citations"' in ln)
    assert json.loads(data[6:])["citations"]


def test_document_routes_roundtrip_and_path_safety(client):
    assert client.put("/documents/api-test.md", json={"content": "# Api Test\n\n## Sec\nZebra crossing facts.\n"}).json()["created"]
    assert client.post("/search", json={"query": "zebra crossing", "top_k": 1}).json()["hits"][0]["source"] == "api-test.md"
    doc = client.get("/documents/api-test.md").json()
    assert doc["in_sync"] and doc["chunks"]
    listing = client.get("/documents").json()
    assert "api-test.md" in [d["path"] for d in listing["documents"]]
    assert client.put("/documents/notes.txt", json={"content": "x"}).status_code == 400
    assert client.put("/documents/a%2F..%2F..%2Fb.md", json={"content": "x"}).status_code in (400, 404)
    assert client.put("/documents/empty.md", json={"content": "  "}).json()["error"]["code"] == "empty_document"
    assert client.delete("/documents/api-test.md").json()["removed_chunks"] == 1
    assert client.get("/documents/api-test.md").status_code == 404


def test_read_only_mode_over_http(client, svc, monkeypatch):
    monkeypatch.setattr(svc.s, "read_only", True)
    r = client.put("/documents/x.md", json={"content": "# X\n\ny"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert client.post("/ingest").status_code == 403 and client.get("/documents").status_code == 200


def test_ingest_and_eval(client):
    rep = client.post("/ingest").json()
    assert rep["added"] == 0 and rep["ingested_chunks"] == rep["chunks"]
    ev = client.post("/eval", json={"k": 5}).json()
    assert ev["n"] == 18 and "hybrid" in ev["modes"] and ev["queries"]
    assert client.post("/eval").status_code == 200                         # body is optional
