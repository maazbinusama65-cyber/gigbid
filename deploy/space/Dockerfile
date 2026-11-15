# Single-container GigBid demo for a Hugging Face Space (Docker SDK) or any Docker host.
# Build context = the bundle made by `python scripts/make_space_bundle.py` (this file and README.md at its root,
# the repository files it needs next to them). Not built in the author's environment before shipping: if the Space
# build fails, the build log names the failing step.

FROM node:20-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV VITE_API_BASE=/api
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/.hf GIGBID_STATIC_DIR=/app/web_dist GIGBID_RUNTIME_DIR=/tmp/gigbid
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 user
WORKDIR /app

COPY pyproject.toml README.md constraints.txt ./
COPY agent agent
COPY rag rag
COPY mcp_servers mcp_servers
COPY gigsim gigsim
COPY apps/api apps/api
COPY data/personas data/personas
COPY data/gigsim_seed data/gigsim_seed
COPY data/policy_pack data/policy_pack

# CPU-only torch first (the default Linux wheel is the multi-gigabyte CUDA build), then the project, editable so
# that paths computed from the package location (data/, agent/config.yaml) resolve to /app.
RUN pip install -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -c constraints.txt -e .

# Bake the embedding model and the persona indexes into the image so a cold start does not download or embed anything.
RUN python -c "from rag.embedder import get_embedder; get_embedder()" \
    && python -c "from rag import config; from rag.retriever import build_index; \
[build_index(p, personas_dir=config.personas_root(), index_root=config.index_root()) for p in ('ai_ml','fullstack','data_analyst')]"

COPY --from=web /web/dist web_dist
COPY start.py start.py
RUN mkdir -p /app/data/processed /tmp/gigbid && chown -R user:user /app /tmp/gigbid
USER user
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -fs http://localhost:7860/api/health || exit 1
CMD ["python", "start.py"]
