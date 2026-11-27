FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models/hf
WORKDIR /app

# CPU-only torch keeps the image small; swap the index URL for a CUDA build on GPU hosts.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies first, so editing source or the UI doesn't invalidate this layer's cache.
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[ml]"

COPY data ./data

# Run as an unprivileged user. uid 1000 matches the usual host user, so the bind-mounted ./data
# (where uploaded documents are written) stays writable without chmod gymnastics.
RUN useradd --create-home --uid 1000 app && mkdir -p /models/hf && chown -R app:app /app /models
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "ahsr.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
