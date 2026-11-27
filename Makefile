.PHONY: install test test-py test-web lint eval serve ingest up down data train-dense train-sparse train-router
install:        ## core + dev deps (add ".[ml]" for PyTorch models)
	pip install -e ".[dev]"
test: test-py test-web   ## everything, offline: hash encoders + in-memory Qdrant, no downloads
test-py:
	python -m pytest -q
test-web:       ## unit tests for the UI's pure modules (needs Node 18+, no npm install)
	node --test tests/web/*.test.mjs
lint:
	python -m pyflakes src tests
	@for f in $$(find src/ahsr/web -name '*.js'); do node --check $$f || exit 1; done
eval:           ## retrieval ablation table (set ENCODER_BACKEND=hash to run offline)
	python -m ahsr.eval.evaluate
ingest:         ## incremental: only new/changed passages are embedded (add --full to rebuild)
	python -m ahsr.ingestion.ingest
serve:          ## UI + API on http://localhost:8000 (reads .env)
	uvicorn ahsr.api.main:app --reload --port 8000
up:
	docker compose up --build -d
down:
	docker compose down
data:           ## synthesize training pairs + router labels from data/docs
	python -m ahsr.training.synth_data
train-dense:
	python -m ahsr.training.train_dense --data data/train/pairs.jsonl --out models/dense
train-sparse:
	python -m ahsr.training.train_sparse --data data/train/pairs.jsonl --out models/sparse
train-router:
	python -m ahsr.training.train_router --data data/train/router.jsonl --out models/router
