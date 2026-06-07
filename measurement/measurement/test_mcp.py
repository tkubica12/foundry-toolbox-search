from __future__ import annotations

import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions

from measurement.mcp_client import McpEndpoint, call_tool, list_tools


def endpoints_from_env(include_toolbox: bool) -> list[McpEndpoint]:
    endpoints = [
        McpEndpoint("loans", os.environ["MCP_LOANS_URL"]),
        McpEndpoint("investments", os.environ["MCP_INVESTMENTS_URL"]),
        McpEndpoint("accounts", os.environ["MCP_ACCOUNTS_URL"]),
    ]
    if include_toolbox:
        endpoints.append(McpEndpoint("toolbox", os.environ["TOOLBOX_ENDPOINT"], foundry_toolbox=True))
    return endpoints


async def main_async(include_toolbox: bool) -> None:
    credential = None
    if include_toolbox:
        credential = InteractiveBrowserCredential(
            cache_persistence_options=TokenCachePersistenceOptions(name="foundry-toolbox-search"),
            timeout=900,
        )
        print("Authenticating to Azure - complete the browser sign-in once if prompted.")
        credential.get_token("https://ai.azure.com/.default")
    for endpoint in endpoints_from_env(include_toolbox):
        tools = await list_tools(endpoint, credential)
        print(f"{endpoint.label}: {len(tools)} tools")
        for tool in tools[:5]:
            print(f"  - {tool.name}: {(tool.description or '')[:80]}")
        if endpoint.label == "loans":
            result = await call_tool(endpoint, "get_loan_balance", {"loan_id": "LN-100", "as_of_date": "2026-06-06"}, credential)
            print(json.dumps({"sample_result": result[:300]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP endpoints.")
    parser.add_argument("--env-file", default=".env.generated")
    parser.add_argument("--include-toolbox", action="store_true")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    asyncio.run(main_async(args.include_toolbox))


if __name__ == "__main__":
    main()
