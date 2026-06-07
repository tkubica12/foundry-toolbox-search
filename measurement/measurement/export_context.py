from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv

from measurement.mcp_client import McpEndpoint, call_tool, list_tools, tool_to_schema

SEARCH_QUERIES = [
    {
        "name": "loan_balance",
        "query": "loan current balance as of date get loan balance tool",
        "limit": 5,
    },
    {
        "name": "mortgage_affordability",
        "query": "mortgage affordability annual income monthly debt",
        "limit": 5,
    },
    {
        "name": "portfolio_summary",
        "query": "portfolio summary market value customer portfolio",
        "limit": 5,
    },
    {
        "name": "account_kyc",
        "query": "current account KYC status customer",
        "limit": 5,
    },
]


def toolbox_endpoint(name: str) -> str:
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
    return f"{project_endpoint}/toolboxes/{name}/mcp?api-version=v1"


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def export_direct_tools(output_dir: Path, endpoints: list[McpEndpoint]) -> None:
    raw_servers: dict[str, list[dict[str, Any]]] = {}
    model_tools: list[dict[str, Any]] = []
    for endpoint in endpoints:
        tools = await list_tools(endpoint)
        raw_servers[endpoint.label] = [tool.model_dump(mode="json") for tool in tools]
        for tool in tools:
            model_tools.append(tool_to_schema(tool, f"{endpoint.label}__{tool.name}"))
    dump_json(output_dir / "standalone-mcp-tools.json", raw_servers)
    dump_json(output_dir / "direct-agent-tools.json", model_tools)


async def get_toolbox_tools(name: str, credential: InteractiveBrowserCredential) -> tuple[McpEndpoint, dict[str, Any]]:
    endpoint = McpEndpoint(name, toolbox_endpoint(name), foundry_toolbox=True)
    tools = await list_tools(endpoint, credential)
    return endpoint, {
        "toolbox": name,
        "endpoint": endpoint.url,
        "tools": [tool.model_dump(mode="json") for tool in tools],
    }


async def export_tool_search_results(output_dir: Path, toolboxes: list[McpEndpoint], credential: InteractiveBrowserCredential) -> None:
    results: dict[str, Any] = {}
    for endpoint in toolboxes:
        results[endpoint.label] = {}
        for query in SEARCH_QUERIES:
            result = await call_tool(
                endpoint,
                "tool_search",
                {"query": query["query"], "limit": query["limit"]},
                credential,
            )
            results[endpoint.label][query["name"]] = {
                "query": query["query"],
                "limit": query["limit"],
                "result": json.loads(result),
            }
    dump_json(output_dir / "tool-search-results.json", results)


def latest_experiment_toolboxes(results_path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    metadata = data["metadata"]
    return {
        scenario: {
            "cold": values["cold_toolbox_name"],
            "warm": values["warm_toolbox_name"],
        }
        for scenario, values in metadata.items()
        if isinstance(values, dict) and "cold_toolbox_name" in values and "warm_toolbox_name" in values
    }


async def main_async(args: argparse.Namespace) -> None:
    load_dotenv(args.env_file)
    output_dir = Path(args.output_dir)
    credential = InteractiveBrowserCredential(
        cache_persistence_options=TokenCachePersistenceOptions(name="foundry-toolbox-search"),
        timeout=900,
    )
    print("Authenticating to Azure - complete the browser sign-in once if prompted.")
    credential.get_token("https://ai.azure.com/.default")

    endpoints = [
        McpEndpoint("loans", os.environ["MCP_LOANS_URL"]),
        McpEndpoint("investments", os.environ["MCP_INVESTMENTS_URL"]),
        McpEndpoint("accounts", os.environ["MCP_ACCOUNTS_URL"]),
    ]
    experiment_toolboxes = latest_experiment_toolboxes(Path(args.results_file))

    await export_direct_tools(output_dir, endpoints)
    cold_payload: dict[str, Any] = {}
    warm_payload: dict[str, Any] = {}
    toolbox_endpoints: list[McpEndpoint] = []
    for scenario, names in experiment_toolboxes.items():
        cold_endpoint, cold_tools = await get_toolbox_tools(names["cold"], credential)
        warm_endpoint, warm_tools = await get_toolbox_tools(names["warm"], credential)
        cold_payload[scenario] = cold_tools
        warm_payload[scenario] = warm_tools
        toolbox_endpoints.extend([cold_endpoint, warm_endpoint])
    dump_json(output_dir / "cold-toolbox-tools.json", cold_payload)
    dump_json(output_dir / "warm-toolbox-tools.json", warm_payload)
    await export_tool_search_results(output_dir, toolbox_endpoints, credential)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export reference MCP/toolbox context JSON files.")
    parser.add_argument("--env-file", default=".env.generated")
    parser.add_argument("--results-file", default="measurement/results-autopin.json")
    parser.add_argument("--output-dir", default="measurement/context")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
