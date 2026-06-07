# measurement

`test_mcp.py` checks MCP endpoints. `measure.py` compares direct MCP tool exposure with Foundry Toolbox Tool Search and records token usage.

Set the environment values emitted by `infra/provision.py`, then run `uv run --project measurement python -m measurement.measure`.
