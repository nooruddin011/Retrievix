import os
import pathlib
import shutil
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Tests that upload/delete documents work on a throw-away copy, never on the repo's data/docs.
_DOCS = pathlib.Path(tempfile.mkdtemp(prefix="ahsr-docs-")) / "docs"
shutil.copytree(ROOT / "data" / "docs", _DOCS)
os.environ.update({"ENCODER_BACKEND": "hash", "QDRANT_URL": ":memory:", "ANTHROPIC_API_KEY": "",
                   "GITHUB_REPO": "", "CODE_ROOT": "", "API_KEY": "", "READ_ONLY": "0",
                   "AHSR_SKIP_DOTENV": "1", "RATE_LIMIT_PER_MIN": "100000",
                   "DOCS_DIR": str(_DOCS), "EVAL_FILE": str(ROOT / "data" / "eval" / "queries.jsonl")})


@pytest.fixture(scope="session")
def container():
    from ahsr.container import build_container
    return build_container()


@pytest.fixture
def make_service(tmp_path):
    """Build an isolated service (own docs dir + own in-memory index) so tests may freely mutate it."""
    def _make(docs: dict[str, str] | None = None, **overrides):
        from ahsr.config import Settings
        from ahsr.container import build_container
        from ahsr.service import SearchService
        d = tmp_path / "docs"
        d.mkdir(exist_ok=True)
        if docs is None:
            docs = {p.name: p.read_text() for p in (ROOT / "data" / "docs").glob("*.md")}
        for name, text in docs.items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text)
        s = Settings(docs_dir=str(d), **overrides)
        return SearchService(build_container(s))
    return _make
