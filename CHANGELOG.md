# Changelog

## 0.2.0

**Added**
- Web UI (served at `/`): live routing readout, streamed agent work log, answers with clickable citations,
  ranked and side-by-side search, document library (upload/edit/delete/reader), evaluation dashboard,
  light/dark themes, keyboard shortcuts, responsive layout, accessible dialogs and live-region announcements.
- API: `POST /route`, `GET /suggestions`, `GET|PUT|DELETE /documents/{path}`, `GET /documents`,
  `POST /eval`, `POST /ingest?full=`; richer `/health`; SSE `start` and `error` events.
- Incremental, zero-downtime indexing with content-derived chunk ids; automatic rebuild on vector-size change.
- Agent: structured step records, "closest matches" fallback flagged as unconfirmed instead of a dead end,
  per-tool failure isolation, per-question timings, citation passage text.
- Security/ops: constant-time API-key check, token-bucket rate limiting, input limits, path validation,
  read-only mode, security headers + CSP, request ids, uniform JSON errors, optional CORS.

**Fixed**
- `.env` was only honoured by Docker; it is now loaded for local runs (and invalid values give clear errors).
- `/ingest` dropped the collection before rebuilding, so searches failed mid-reindex.
- `/ask/stream` gave no signal when the agent failed mid-stream.
- Offline decomposer dropped bare-identifier fragments (`--dry-run and also ...` lost the flag).
- Offline grader accepted passages about a *different* error code for an exact code lookup.
- Offline synthesis flattened code blocks, cut text mid-word and left dangling "Via the API:" fragments.
- Anthropic client used the SDK's 10-minute default timeout.
- Single-engine search modes still ran both encoders; repeated queries were re-embedded.
- Docker: ran as root, Qdrant unpinned and published on all interfaces, API raced Qdrant at start-up.
- Over-long prose paragraphs were never split by the chunker.
