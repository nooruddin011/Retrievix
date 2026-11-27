# TASK: Finish and verify the "Agentic Hybrid Search Router" project

You are taking over a nearly complete project in this repo (Python/FastAPI/Qdrant/LangGraph backend +
a no-build vanilla-JS web UI in src/ahsr/web). A previous engineer built and tested it in a sandbox WITHOUT
network access, so FastAPI, qdrant-client and langgraph were replaced by minimal stand-ins, and nothing
requiring model downloads, Docker, or an Anthropic key was ever executed. Your job: close every gap below,
fix whatever breaks, and leave the project verified end-to-end. Do not stop at a plan; implement, run,
and fix. Work phase by phase, one commit per phase, and keep going until the Definition of Done is met.

## Read first
README.md (architecture, API, Status table), CHANGELOG.md, .env.example, src/ahsr/service.py (framework-free
service layer), src/ahsr/api/main.py (thin FastAPI adapter), src/ahsr/agent/graph.py + llm.py, tests/.

## Ground rules
- Real libraries only: never re-introduce stand-ins/mocks of fastapi, qdrant-client or langgraph.
- Never weaken or delete a test to make it pass. Fix the code, or fix the test only if the test is wrong,
  and say why.
- Keep the public API contract and the UI working. If you change a response shape, update the UI
  (src/ahsr/web/js), tests, README and CHANGELOG in the same commit.
- UI constraints stay: no build step, no CDN/runtime network deps, strict CSP (no inline script/style, no
  eval), never use innerHTML with untrusted text. Python >= 3.10.
- Offline mode must keep working with zero network and zero keys (ENCODER_BACKEND=hash, empty
  ANTHROPIC_API_KEY); CI must pass that way.
- Secrets come from the environment/.env only. Never print, log, hardcode or commit them. If you need a key
  or data I haven't supplied, stop that sub-task, finish everything else, and list exactly what you need.
- Do not claim something works unless you ran it. Record the command and result.

## Phase 0: Baseline with real dependencies
1. Create a venv (3.11 or 3.12), `pip install -e ".[dev]"`, run `make test` and `make lint`.
2. Never-executed code that MUST now pass: tests/test_api.py and tests/test_pipeline.py::test_api_endpoints.
   Fix all failures in code. Specific risks to check against the real libraries:
   a. FastAPI: `from __future__ import annotations` + `req: EvalRequest | None = None` (optional body);
      the `guard()` dependency (Header + Depends(get_service) inside a closure); the `app.mount("/")`
      StaticFiles catch-all vs route order and 404/405 JSON envelopes; BaseHTTPMiddleware with
      StreamingResponse/SSE; the generic `Exception` handler; `/documents/{path:path}` with encoded slashes;
      `lru_cache`d dependency.
   b. qdrant-client: HybridStore uses scroll(with_payload=["source"]), get_collection().config.params
      .vectors[DENSE].size, delete(points_selector=PointIdsList), collection_exists, query_points with
      prefetch/FusionQuery. Verify in `:memory:`, `path:` and against a real Qdrant SERVER (docker). Add a
      keyword payload index on `source` for server mode. Confirm compat() and the auto-rebuild on vector-size
      change work for real.
   c. LangGraph: confirm `stream_mode="updates"` chunk shapes for parallel `Send` tasks in
      SearchService.ask_events (chunks may be per-task, coalesced, or lists); confirm reducers, the
      conditional fan-out and `research -> synthesize` fan-in behave as the stand-in assumed. Make
      ask_events robust to the real shapes and add a test with the real graph asserting one `research`
      event per sub-question.
3. Pin tested version ranges for fastapi, starlette, pydantic, qdrant-client, langgraph, anthropic, httpx in
   pyproject.toml, and add `pytest-timeout`/`pip-audit` to the dev extras.
4. Add a `make smoke` target + scripts/smoke.sh: boot the server offline (hash encoders, :memory:),
   curl /health, /route, /search, /ask, /ask/stream (assert SSE event order), /documents CRUD, /eval; exit
   non-zero on any failure.

## Phase 1: Docker
1. `docker compose up --build` from a clean checkout WITHOUT a .env (env_file is optional) and with one.
2. Verify: the pinned `qdrant/qdrant:v1.12.4` tag exists (bump if not); the API waits for Qdrant (no crash
   loop); both healthchecks go healthy; UI loads at http://localhost:8000; uploads from the UI persist to
   ./data/docs and survive `docker compose down && up`; the non-root user (uid 1000) can write the bind
   mount, and works with a named volume too (document the chown note for other host uids).
3. Verify API_KEY, READ_ONLY=1 and RATE_LIMIT_PER_MIN behave correctly in the container. Add a
   Qdrant API-key variant to docs. Report image size; trim if easy (multi-stage build).

## Phase 2: Real models
1. ENCODER_BACKEND=hf: run `make ingest` and exercise HFDenseEncoder, HFSparseEncoder (SPLADE
   log(1+ReLU) max-pool, SPARSE_MAX_TERMS) and TransformerRouter (via ROUTER_MODEL) for real. Fix bugs
   (pooling, query prefix, truncation, batching, device handling, empty-vector edge cases).
2. Thread safety: LangGraph runs sub-question research in parallel threads that share the models. Prove
   concurrent /ask calls are safe (torch.inference_mode/no_grad, locks if needed) with a concurrency test.
3. Add HF tests gated by `RUN_HF_TESTS=1` (skipped in CI by default); add a manual/nightly CI job for them.
4. Run `make eval` with real models and record the dense / sparse / flat / routed table in the README with
   the model names and date. The CI hash gate must remain.
5. Execute the training scripts for real on tiny settings (CPU, few steps): `make data`, `make train-router`,
   `make train-dense`, `make train-sparse`. Fix whatever breaks, then prove each fine-tuned checkpoint loads
   through DENSE_MODEL / SPARSE_MODEL / ROUTER_MODEL and that changing the dense model triggers the
   automatic index rebuild. Document exact commands and expected outputs.

## Phase 3: Live LLM and tools (needs ANTHROPIC_API_KEY, optionally GITHUB_TOKEN, in .env)
1. Verify the default LLM_MODEL id is currently valid in Anthropic's docs; update .env.example and README
   if not.
2. Exercise ClaudeLLM decompose / grade / rewrite / synthesize for real. Check JSON parsing robustness,
   that [n] citations render as clickable chips in the UI, and that each step falls back cleanly on: bad key,
   timeout, rate limit, malformed JSON. Add unit tests with a fake Anthropic client for those failure modes.
3. Add token/cost visibility: log usage per request; cap max_tokens sensibly; batch grading calls where
   possible; document expected cost per question.
4. Verify GitHubIssuesTool live (authenticated and unauthenticated, 403/rate-limit handling, timeouts) and
   CodeSearchTool on a real CODE_ROOT (path escape, symlinks, huge/binary files, time budget). Add tests.
5. Confirm the UI labels (Claude vs "Quoted from sources", unconfirmed matches, tool results with
   Code/Issue chips) are accurate with a real key.

## Phase 4: Retrieval quality on a real corpus
Do NOT invent a corpus. Build the tooling and leave a clearly documented step for me to supply docs:
1. Add `scripts/check_eval.py` validating data/eval/queries.jsonl against data/docs (every `relevant`
   source exists, types valid, duplicates, counts per type) and wire it into CI.
2. Add a documented workflow (and `make` target) for: swap in my docs, generate candidate queries
   (`make data`), hand-label 100-200 queries, run the eval, and tune CANDIDATE_POOL, RRF_K and the router
   thresholds. Provide a small sweep script that prints a table. If I have supplied docs/queries in
   data/, run the sweep and report; otherwise stop at the tooling and say so.

## Phase 5: Items deliberately left out earlier (implement all)
1. Token-level answer streaming: new SSE `token` events from ClaudeLLM.synthesize (offline path unchanged);
   the UI renders progressively and resolves [n] citation chips when the final `synthesize` event lands.
2. True live work log: stream retrieve/grade/rewrite/tool steps AS THEY HAPPEN inside a sub-question
   (LangGraph custom stream writer or subgraph streaming) instead of one event per finished sub-question.
   Update worklog.js; keep the final event contract.
3. Client disconnect cancels in-flight agent work for /ask/stream (no wasted LLM spend).
4. Multi-turn follow-ups: optional bounded `history` in /ask and /ask/stream; use it to resolve pronouns
   in decompose/rewrite; UI thread with "follow up" input; history stays client-side; document limits.
5. Optional shared infrastructure behind env flags, with the zero-dependency default intact: REDIS_URL for
   the rate limiter and the query-embedding cache; optional LangGraph checkpointer; optional
   Langfuse/LangSmith tracing; propagate X-Request-Id into logs and traces.
6. Request-body size limit enforced before parsing (PUT /documents and all POSTs), returning the standard
   error envelope with 413; test it.
7. Scale: list_documents currently re-chunks every document and scrolls the whole index per call. Add
   caching/pagination plus a client-side filter box in the Library for large corpora.
8. Ops: optional JSON logs (LOG_FORMAT=json), optional Prometheus /metrics (METRICS=1), graceful shutdown,
   static-asset cache headers, and a deployment note for TLS/HSTS and TRUST_PROXY behind a proxy.
9. UI polish: render identifier tokens in the monospace face inside suggestion text; arrow-key navigation
   through suggestions/recent; focus management after route changes.
10. Accessibility: run axe-core (dev-only, via Playwright) on every view in light and dark; fix all
    serious/critical violations; check contrast and the keyboard-only path through every flow.
11. Real browser E2E tests in-repo (tests/e2e, Playwright, offline server). Cover: live routing bar, Ask
    streaming + citations, Search/Compare, Library create/edit/upload/drag-drop/delete, Evaluate, API-key
    prompt flow, read-only mode, offline error state, mobile width (no horizontal overflow). Add a CI job.
12. Security pass: `pip-audit`, review all file/path handling, SSRF surface of the GitHub tool, prompt
    injection handling in synthesis, CSP/headers, upload abuse (many files, large files). Fix findings.

## Definition of Done (all must be true; show evidence)
- `make test`, `make lint`, `make smoke` pass on real dependencies; CI green on 3.10 and 3.12; HF/live-key
  tests pass when enabled.
- `docker compose up --build` reaches healthy and the manual flow works (search, ask, upload, edit, delete,
  reindex) in a browser.
- With a real ANTHROPIC_API_KEY, a multi-part question returns a Claude-written answer with working
  citations, and failure fallbacks are tested.
- README Status table updated so every row is either Verified (with the command/date) or lists precisely what
  remains and why; CHANGELOG updated; .env.example complete.
- No TODOs, stubs or skipped-without-reason tests left behind.

## Final report format
Per phase: what changed (files), what you ran and the result, anything you could not verify and exactly what
you need from me (key, docs, hardware). Then a short "how to run it now" section.