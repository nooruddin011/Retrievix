"""FastAPI adapter over ``SearchService``.

Retrieval:   POST /search  /route          Agent:  POST /ask  /ask/stream (SSE)
Library:     GET /documents, GET|PUT|DELETE /documents/{path}, POST /ingest
Operations:  GET /health   POST /eval      UI:     GET /  (static, served from ahsr/web)

Every error is returned as ``{"error": {"code", "message", "request_id"}}``.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ahsr import __version__
from ahsr.config import get_settings
from ahsr.errors import RateLimited, ServiceError, Unauthorized
from ahsr.ratelimit import TokenBucketLimiter
from ahsr.service import SearchService, get_service

log = logging.getLogger("ahsr.api")
_settings = get_settings()
logging.basicConfig(level=_settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")

_limiter: TokenBucketLimiter | None = None
_REQUEST_ID = re.compile(r"[^\w.\-]")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_service()                    # warm models, connect to Qdrant, sync the index at startup
    yield


app = FastAPI(title="Agentic Hybrid Search Router", version=__version__, lifespan=lifespan)

if _settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Request-Id", "Retry-After"])


# --------------------------------------------------------------------------------------- guards ----
def _limiter_for(per_minute: int) -> TokenBucketLimiter:
    global _limiter
    if _limiter is None or _limiter.per_minute != per_minute:
        _limiter = TokenBucketLimiter(per_minute)
    return _limiter


def _client_id(request: Request, api_key: str | None, trust_proxy: bool) -> str:
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
    if trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
        return "ip:" + fwd.split(",")[0].strip()
    return "ip:" + (request.client.host if request.client else "unknown")


def guard(cost: float = 1.0):
    """Dependency: rate-limit first (so failed auth attempts are throttled too), then check the API key."""
    def dependency(request: Request, x_api_key: str | None = Header(default=None),
                   svc: SearchService = Depends(get_service)):
        s = svc.s
        ok, retry = _limiter_for(s.rate_limit_per_min).check(_client_id(request, x_api_key, s.trust_proxy), cost)
        if not ok:
            raise RateLimited(retry)
        if s.api_key and not (x_api_key and hmac.compare_digest(x_api_key.encode(), s.api_key.encode())):
            raise Unauthorized("A valid API key is required.", code="invalid_api_key")
    return Depends(dependency)


# ------------------------------------------------------------------------------------- schemas ----
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(5, ge=1, le=50)
    mode: Literal["hybrid", "hybrid_flat", "hybrid_server", "dense", "sparse"] = "hybrid"


class RouteRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)


class DocumentBody(BaseModel):
    content: str = Field(max_length=5_000_000)


class EvalRequest(BaseModel):
    k: int = Field(5, ge=1, le=20)


# ------------------------------------------------------------------------------------ plumbing ----
def _error(request: Request, status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    return JSONResponse({"error": {"code": code, "message": message, "request_id": rid}},
                        status_code=status, headers=headers)


@app.exception_handler(ServiceError)
async def _service_error(request: Request, exc: ServiceError):
    return _error(request, exc.status, exc.code, exc.message, exc.headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    parts = []
    for e in exc.errors():
        where = ".".join(str(x) for x in e.get("loc", ())[1:])
        parts.append(f"{where}: {e.get('msg')}" if where else str(e.get("msg")))
    return _error(request, 422, "invalid_request", "; ".join(parts) or "Invalid request.")


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    codes = {404: "not_found", 405: "method_not_allowed"}
    return _error(request, exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return _error(request, 500, "internal_error", "Something went wrong on the server.")


@app.middleware("http")
async def _middleware(request: Request, call_next):
    rid = _REQUEST_ID.sub("", request.headers.get("x-request-id", ""))[:64] or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    t0 = time.perf_counter()
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    response.headers["X-Request-Id"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if ctype.startswith("application/json"):
        response.headers["Cache-Control"] = "no-store"
    if ctype.startswith("text/html") and not request.url.path.startswith(_DOCS_PATHS):
        response.headers["Content-Security-Policy"] = _CSP
    log.info("%s %s -> %d %dms rid=%s", request.method, request.url.path, response.status_code,
             (time.perf_counter() - t0) * 1000, rid)
    return response


# -------------------------------------------------------------------------------------- routes ----
@app.get("/health", tags=["operations"])
def health(svc: SearchService = Depends(get_service)):
    info = svc.health()
    return JSONResponse(info, status_code=200 if info["status"] == "ok" else 503)


@app.get("/suggestions", tags=["retrieval"], dependencies=[guard(1)])
def suggestions(svc: SearchService = Depends(get_service)):
    return svc.suggestions()


@app.post("/route", tags=["retrieval"], dependencies=[guard(0.25)])
def route(req: RouteRequest, svc: SearchService = Depends(get_service)):
    return svc.route(req.query)


@app.post("/search", tags=["retrieval"], dependencies=[guard(1)])
def search(req: SearchRequest, svc: SearchService = Depends(get_service)):
    return svc.search(req.query, req.top_k, req.mode)


@app.post("/ask", tags=["agent"], dependencies=[guard(5)])
def ask(req: AskRequest, svc: SearchService = Depends(get_service)):
    return svc.ask(req.question)


@app.post("/ask/stream", tags=["agent"], dependencies=[guard(5)])
def ask_stream(req: AskRequest, svc: SearchService = Depends(get_service)):
    svc.clean_text(req.question, "question")             # fail fast with a proper 400, before streaming starts

    def events():
        for ev in svc.ask_events(req.question):
            yield svc.sse(ev)
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/documents", tags=["library"], dependencies=[guard(1)])
def list_documents(svc: SearchService = Depends(get_service)):
    return svc.list_documents()


@app.get("/documents/{path:path}", tags=["library"], dependencies=[guard(1)])
def get_document(path: str, svc: SearchService = Depends(get_service)):
    return svc.get_document(path)


@app.put("/documents/{path:path}", tags=["library"], dependencies=[guard(5)])
def put_document(path: str, body: DocumentBody, svc: SearchService = Depends(get_service)):
    return svc.put_document(path, body.content)


@app.delete("/documents/{path:path}", tags=["library"], dependencies=[guard(5)])
def delete_document(path: str, svc: SearchService = Depends(get_service)):
    return svc.delete_document(path)


@app.post("/ingest", tags=["library"], dependencies=[guard(20)])
def ingest(full: bool = False, svc: SearchService = Depends(get_service)):
    return svc.reindex(full=full)


@app.post("/eval", tags=["operations"], dependencies=[guard(20)])
def evaluate(req: EvalRequest | None = None, svc: SearchService = Depends(get_service)):
    return svc.evaluate(req.k if req else 5)


# UI: mounted last so it never shadows an API route.
_WEB = Path(__file__).resolve().parent.parent / "web"
if _settings.serve_ui and _WEB.is_dir():
    app.mount("/", StaticFiles(directory=_WEB, html=True), name="ui")
