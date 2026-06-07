# mcp_servers

Three FastMCP HTTP services with mocked FSI tools. Each service exposes `/health` and `/mcp`.

Run one locally with `uv run --project mcp_servers/loans uvicorn loans_mcp.app:app --port 8001`.
