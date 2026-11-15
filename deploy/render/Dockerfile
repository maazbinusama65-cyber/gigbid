# GigBid demo for Render's free plan (512 MB): one container, no PyTorch.
# Build context is the repository root (render.yaml sets dockerfilePath and dockerContext).
# Retrieval uses the hashing embedder (RAG_EMBEDDER=hash), so search quality differs from the evaluated bge model;
# the model profile is `stub` (deterministic, no LLM calls, no API key).

FROM node:20-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV VITE_API_BASE=/api
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MALLOC_ARENA_MAX=2 \
    RAG_EMBEDDER=hash MODEL_PROFILE=stub \
    GIGBID_STATIC_DIR=/app/web_dist GIGBID_RUNTIME_DIR=/tmp/gigbid
WORKDIR /app

COPY deploy/render/requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY agent agent
COPY rag rag
COPY mcp_servers mcp_servers
COPY gigsim gigsim
COPY apps/api apps/api
COPY data/personas data/personas
COPY data/gigsim_seed data/gigsim_seed
COPY data/policy_pack data/policy_pack
# Editable so that paths computed from the package location (data/, agent/config.yaml) resolve to /app.
RUN pip install --no-deps -e . && mkdir -p data/processed

COPY --from=web /web/dist web_dist
COPY deploy/space/start.py start.py
CMD ["python", "start.py"]
