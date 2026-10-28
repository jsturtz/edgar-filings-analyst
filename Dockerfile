# syntax=docker/dockerfile:1
#
# One image for both jobs:
#   API (default):  uvicorn edgar_agent.api:app
#   Ingest:         python -m edgar_agent.ingest --years 3
#
# Build:  docker build -t edgar-analyst:dev .

# ---------------------------------------------------------------- builder
FROM python:3.12-slim AS builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/opt/hf

WORKDIR /app
RUN uv venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv PATH=/app/.venv/bin:$PATH

# Dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock README.md ./
# The lockfile pins PyTorch's default Linux build, which pulls in ~3-5 GB of NVIDIA CUDA
# libraries. Containers here run the small embedding model on CPU, so install the same
# torch version from PyTorch's CPU-only index and drop the GPU packages.
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
 && TORCH_PIN="$(grep -E '^torch==' requirements.txt | cut -d' ' -f1)" \
 && uv pip install "$TORCH_PIN" --index-url https://download.pytorch.org/whl/cpu \
 && grep -v -E '^(torch|triton|nvidia-|cuda-)' requirements.txt > requirements-cpu.txt \
 && uv pip install -r requirements-cpu.txt

# Then the project itself.
COPY src ./src
RUN uv pip install --no-deps .

# Bake the embedding model into the image: fast, offline pod startup.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data \
 && chown app:app /data

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/hf /opt/hf
COPY eval ./eval

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    EDGAR_DATA_DIR=/data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["uvicorn", "edgar_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
