# Standalone image for this service (generated from python.Dockerfile + service tail)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY agent agent
COPY rag rag
COPY mcp_servers mcp_servers
COPY gigsim gigsim
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY worker worker
COPY evals evals
COPY data/policy_pack data/policy_pack
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch && pip install -e .
ARG SERVER=portfolio
ENV SERVER=${SERVER}
CMD ["sh", "-c", "python -m mcp_servers.${SERVER} --transport streamable-http --host 0.0.0.0 --port ${PORT:-9100}"]
