"""Environment-driven settings.

Read at call time so tests can override env vars. A ``.env`` file in the working directory (or the
path in ``ENV_FILE``) is loaded automatically without overriding variables that are already set, so
``cp .env.example .env`` works for local runs as well as for Docker Compose.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised for invalid configuration; the message names the offending variable."""


def load_dotenv(path: str | os.PathLike | None = None, override: bool = False) -> int:
    """Minimal .env reader: KEY=VALUE, optional quotes, ``export`` prefix, inline `` # comments``."""
    p = Path(path or os.getenv("ENV_FILE") or ".env")
    if not p.is_file():
        return 0
    loaded = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, rest = line.partition("=")
        key, rest = key.strip(), rest.lstrip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if rest[:1] in ("'", '"'):
            end = rest.find(rest[0], 1)
            value = rest[1:end] if end != -1 else rest[1:]
        else:
            value = rest.split(" #", 1)[0].rstrip()
        if override or key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


if os.getenv("AHSR_SKIP_DOTENV") != "1":
    load_dotenv()


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _int(name: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if (lo is not None and val < lo) or (hi is not None and val > hi):
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {val}")
    return val


def _float(name: str, default: float, lo: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        val = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if val < lo:
        raise ConfigError(f"{name} must be >= {lo}, got {val}")
    return val


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def _f(fn, *args, **kw):
    return field(default_factory=lambda: fn(*args, **kw))


@dataclass
class Settings:
    # vector store
    qdrant_url: str = _f(_str, "QDRANT_URL", ":memory:")
    qdrant_api_key: str = _f(_str, "QDRANT_API_KEY")
    qdrant_wait_s: int = _f(_int, "QDRANT_WAIT_S", 30, 0, 600)
    collection: str = _f(_str, "COLLECTION", "tech_docs")
    # encoders
    encoder_backend: str = _f(_str, "ENCODER_BACKEND", "hf")
    dense_model: str = _f(_str, "DENSE_MODEL", "BAAI/bge-small-en-v1.5")
    dense_pooling: str = _f(_str, "DENSE_POOLING", "cls")
    dense_query_prefix: str = _f(_str, "DENSE_QUERY_PREFIX", "Represent this sentence for searching relevant passages: ")
    sparse_model: str = _f(_str, "SPARSE_MODEL", "naver/splade-cocondenser-ensembledistil")
    sparse_max_terms: int = _f(_int, "SPARSE_MAX_TERMS", 256, 1, 4096)
    router_model: str = _f(_str, "ROUTER_MODEL")
    embed_cache_size: int = _f(_int, "EMBED_CACHE_SIZE", 512, 0, 100_000)
    # retrieval
    top_k: int = _f(_int, "TOP_K", 5, 1, 50)
    candidate_pool: int = _f(_int, "CANDIDATE_POOL", 20, 1, 500)
    rrf_k: int = _f(_int, "RRF_K", 60, 1, 1000)
    # agent
    anthropic_api_key: str = _f(_str, "ANTHROPIC_API_KEY")
    llm_model: str = _f(_str, "LLM_MODEL", "claude-sonnet-5-5")
    llm_timeout_s: float = _f(_float, "LLM_TIMEOUT_S", 45.0, 1.0)
    max_rewrites: int = _f(_int, "MAX_REWRITES", 2, 0, 10)
    max_sub_queries: int = _f(_int, "MAX_SUB_QUERIES", 4, 1, 10)
    # tools
    github_repo: str = _f(_str, "GITHUB_REPO")
    github_token: str = _f(_str, "GITHUB_TOKEN")
    code_root: str = _f(_str, "CODE_ROOT")
    # service
    app_name: str = _f(_str, "APP_NAME", "Hybrid Search")
    docs_dir: str = _f(_str, "DOCS_DIR", "data/docs")
    eval_file: str = _f(_str, "EVAL_FILE", "data/eval/queries.jsonl")
    auto_ingest: bool = _f(_bool, "AUTO_INGEST", True)
    serve_ui: bool = _f(_bool, "SERVE_UI", True)
    read_only: bool = _f(_bool, "READ_ONLY", False)
    # security / limits
    api_key: str = _f(_str, "API_KEY")
    cors_origins: list = _f(_list, "CORS_ORIGINS")
    rate_limit_per_min: int = _f(_int, "RATE_LIMIT_PER_MIN", 120, 0, 1_000_000)
    trust_proxy: bool = _f(_bool, "TRUST_PROXY", False)
    max_query_chars: int = _f(_int, "MAX_QUERY_CHARS", 2000, 16, 20_000)
    max_doc_bytes: int = _f(_int, "MAX_DOC_BYTES", 512 * 1024, 1024, 50 * 1024 * 1024)
    max_documents: int = _f(_int, "MAX_DOCUMENTS", 500, 1, 100_000)
    log_level: str = _f(_str, "LOG_LEVEL", "INFO")

    @property
    def demo_mode(self) -> bool:
        """True when the offline stand-in encoders are active (not representative of real quality)."""
        return self.encoder_backend == "hash"


def get_settings() -> Settings:
    return Settings()
