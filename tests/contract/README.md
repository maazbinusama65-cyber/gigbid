# Contract tests

`test_tool_schemas.py` dumps every MCP tool of the Marketplace, Portfolio and Workspace servers
(name, description, inputSchema, outputSchema, annotations; plus resource templates and prompts) and
compares it with `snapshots/tool_schemas.json`. An unintended change fails CI and names the tool.

Intended change? Regenerate and review the diff like an API change:

```bash
UPDATE_SNAPSHOTS=1 pytest tests/contract/test_tool_schemas.py
git diff tests/contract/snapshots/tool_schemas.json
```
