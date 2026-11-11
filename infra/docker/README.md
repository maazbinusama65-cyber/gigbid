One Dockerfile per service: `python.Dockerfile` (shared source of the standalone service Dockerfiles), `api`, `worker`, `mcp` (parameterised by
`SERVER`), `gigsim`, `web` (+ `nginx.conf`). `docker compose -f infra/docker-compose.yml up --build` starts
web, API, worker, the three MCP servers, GigSim, Postgres, Redis and Ollama. Build the base first
(`docker compose build api` does it through the shared anchor).
