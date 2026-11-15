# gigbid-portfolio-mcp

A **read-only** [MCP](https://modelcontextprotocol.io) server that exposes a freelancer's own
portfolio (case studies, repo READMEs, reviews, CV, past proposals with their won / replied / ignored
outcome) so an AI assistant can write proposals and screening answers from *real, citable evidence*
instead of inventing experience.

* Tools (all `readOnlyHint=true`, no network access, cannot modify anything):
  `search_evidence(requirement, k, filters, portfolio_id)`, `get_case_study(id)`, `list_skills()`
* Resource templates: `portfolio://case/{id}`, `portfolio://proposal/{id}` (+ `portfolio://skills`)
* Prompts: `screening_answer`, `cover_letter_from_evidence`, `portfolio_gap_check`
  (each pulls the matching evidence and forbids claims it does not support)
* Transports: stdio (default) and streamable HTTP (bearer token required).

## Your data

Point `PORTFOLIO_DATA_DIR` at a folder with one sub-folder per portfolio:

```
<PORTFOLIO_DATA_DIR>/<portfolio_id>/
    cv.md  profile.json  projects.json  reviews.json  proposals.json
    case_studies/<project_id>.md          # first line "# Title"
    repos/<project_id>/README.md
```

`projects.json`: `[{"project_id","title","skills":[],"industry","date","outcome_summary"}]`,
`proposals.json`: `[{"proposal_id","job_title","text","outcome":"won|replied|ignored","date","project_ids":[]}]`.

| env | meaning | default |
|---|---|---|
| `PORTFOLIO_DATA_DIR` | folder holding the portfolios | `data/personas` |
| `PORTFOLIO_ID` | portfolio used when a call omits `portfolio_id` | `default` |
| `PORTFOLIO_BACKEND` | `auto` (use GigBid's `rag` package if importable, else local), `rag`, `local` | `auto` |
| `PORTFOLIO_MCP_TOKEN` | bearer token, required for HTTP | - |

The standalone package ships a dependency-free BM25 retriever; inside GigBid it delegates to
`rag.retriever.get_retriever(variant, portfolio_id)`.

## Install and run

```bash
# 1. uvx, straight from GitHub (nothing to clone, no PyPI account involved)
uvx --from "git+https://github.com/maazbinusama65-cyber/gigbid#subdirectory=mcp_servers/portfolio" gigbid-portfolio-mcp
#    or from a checkout:
uvx --from ./mcp_servers/portfolio gigbid-portfolio-mcp

# 2. python -m (inside the GigBid repo)
python -m mcp_servers.portfolio                                   # stdio
PORTFOLIO_MCP_TOKEN=change-me-long python -m mcp_servers.portfolio \
    --transport streamable-http --port 9101                       # http://127.0.0.1:9101/mcp

# 3. Docker
docker build -t gigbid-portfolio-mcp mcp_servers/portfolio
docker run -i --rm -v "$PWD/my_portfolio:/data" -e PORTFOLIO_DATA_DIR=/data -e PORTFOLIO_ID=me \
    gigbid-portfolio-mcp                                          # stdio
```

### Claude Desktop (`claude_desktop_config.json`) / Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "gigbid-portfolio": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/maazbinusama65-cyber/gigbid#subdirectory=mcp_servers/portfolio", "gigbid-portfolio-mcp"],
      "env": { "PORTFOLIO_DATA_DIR": "/path/to/my_portfolio", "PORTFOLIO_ID": "me", "PORTFOLIO_BACKEND": "local" }
    }
  }
}
```

Docker variant: `"command": "docker", "args": ["run","-i","--rm","-v","/path/to/my_portfolio:/data","-e","PORTFOLIO_DATA_DIR=/data","-e","PORTFOLIO_ID=me","gigbid-portfolio-mcp"]`.

Then ask: *"Using my portfolio, answer this screening question: ..."* (pick the `screening_answer` prompt).

## Requirements and verification

Python 3.11+. Dependencies are `mcp>=1.9,<2`, `pydantic` and `uvicorn`; the `<2` pin matters because `mcp` 2.x renamed the
`FastMCP` API this server uses. The package was installed into a clean virtual environment and exercised over stdio
(initialise, list the three read-only tools, `list_skills`, `search_evidence`) before this was written.

## Develop

```bash
pytest mcp_servers/portfolio          # in-memory MCP client tests
npx @modelcontextprotocol/inspector uvx --from ./mcp_servers/portfolio gigbid-portfolio-mcp
```

The tool schemas are snapshot-tested (`tests/contract/test_tool_schemas.py`).
