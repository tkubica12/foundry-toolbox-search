from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, ToolConfig, ToolboxSearchPreviewTool
from azure.core.credentials import TokenCredential
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv
from openai import RateLimitError

from measurement.mcp_client import McpEndpoint, list_tools


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    expected_markers: tuple[str, ...]


SCENARIOS = [
    Scenario(
        name="loan-single-tool",
        prompt=(
            "For customer c123, get the current balance for loan LN-100 as of 2026-06-06. "
            "Reply as compact JSON with keys answer and markers."
        ),
        expected_markers=("LN-100", "184250.75"),
    ),
    Scenario(
        name="cross-domain-three-tools",
        prompt=(
            "For customer c123, answer with compact JSON only. Use tools to get three values: "
            "current balance for loan LN-100 as of 2026-06-06, portfolio summary for portfolio PF-42, "
            "and current-account KYC status for customer c123. "
            "For toolbox mode, use these searches when needed: "
            "'exact tool name loans___get_loan_balance', "
            "'portfolio valuation total value customer portfolio', and "
            "'exact tool name accounts___check_account_kyc_status'. "
            "Include all returned markers."
        ),
        expected_markers=("LN-100", "184250.75", "INV-DEMO-C123", "248500", "ACCT-DEMO-C123", "current"),
    ),
]


def get_nested_int(obj: Any, *names: str) -> int:
    current = obj
    for name in names:
        if current is None:
            return 0
        current = getattr(current, name, None)
        if current is None and isinstance(obj, dict):
            current = obj.get(name)
    return int(current or 0)


def usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    cached_tokens = get_nested_int(usage, "input_tokens_details", "cached_tokens")
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": max(input_tokens - cached_tokens, 0),
        "output_tokens": output_tokens,
        "total_tokens": int(getattr(usage, "total_tokens", 0) or input_tokens + output_tokens),
    }


def output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "output_text":
                chunks.append(getattr(content, "text", ""))
    return "".join(chunks)


def is_correct(text: str, markers: tuple[str, ...]) -> bool:
    return all(marker in text for marker in markers)


def response_trace(response: Any) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)
        if item_type == "mcp_list_tools":
            trace.append(
                {
                    "type": item_type,
                    "server_label": getattr(item, "server_label", None),
                    "tools_count": len(getattr(item, "tools", []) or []),
                }
            )
        elif item_type == "mcp_call":
            trace.append(
                {
                    "type": item_type,
                    "server_label": getattr(item, "server_label", None),
                    "name": getattr(item, "name", None),
                    "arguments": getattr(item, "arguments", None),
                    "output_preview": str(getattr(item, "output", ""))[:1000],
                }
            )
        elif item_type == "message":
            trace.append({"type": item_type, "text_preview": output_text(type("R", (), {"output": [item]})())[:500]})
        else:
            trace.append({"type": str(item_type), "name": getattr(item, "name", None)})
    return trace


def create_toolbox(project: AIProjectClient, name: str, endpoints: list[McpEndpoint]) -> str:
    endpoint_by_label = {endpoint.label: endpoint.url for endpoint in endpoints}
    version = project.beta.toolboxes.create_version(
        name=name,
        description="Fresh FSI demo toolbox for cold/warm native MCP Tool Search measurement.",
        tools=[
            MCPTool(
                server_label="loans",
                server_url=endpoint_by_label["loans"],
                require_approval="never",
                tool_configs={
                    "get_loan_balance": ToolConfig(
                        additional_search_text="loans___get_loan_balance get_loan_balance loan balance current loan balance outstanding balance loan id as of date"
                    ),
                    "get_mortgage_affordability": ToolConfig(
                        additional_search_text="mortgage affordability borrowing capacity annual income monthly debt home loan"
                    ),
                },
            ),
            MCPTool(
                server_label="investments",
                server_url=endpoint_by_label["investments"],
                require_approval="never",
                tool_configs={
                    "get_portfolio_summary": ToolConfig(
                        additional_search_text="investments___get_portfolio_summary get_portfolio_summary portfolio summary market value portfolio valuation total value customer portfolio"
                    )
                },
            ),
            MCPTool(
                server_label="accounts",
                server_url=endpoint_by_label["accounts"],
                require_approval="never",
                tool_configs={
                    "check_account_kyc_status": ToolConfig(
                        additional_search_text="accounts___check_account_kyc_status check_account_kyc_status current account KYC status compliance know your customer customer identity review"
                    ),
                    "get_account_balance": ToolConfig(
                        additional_search_text="current account balance available balance checking account cash account"
                    ),
                },
            ),
            ToolboxSearchPreviewTool(),
        ],
    )
    version_number = str(getattr(version, "version", "1"))
    project_name = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/").split("/")[-1]
    account_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"].split("/api/projects/")[0]
    return f"{account_endpoint}/api/projects/{project_name}/toolboxes/{name}/versions/{version_number}/mcp?api-version=v1"


def direct_mcp_tools(endpoints: list[McpEndpoint], label_suffix: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "mcp",
            "server_label": f"{endpoint.label}_{label_suffix}",
            "server_url": f"{endpoint.url}?cache_bust={label_suffix}",
            "require_approval": "never",
        }
        for endpoint in endpoints
    ]


def toolbox_mcp_tool(endpoint: str, credential: TokenCredential) -> dict[str, Any]:
    token = credential.get_token("https://ai.azure.com/.default").token
    return {
        "type": "mcp",
        "server_label": "toolbox",
        "server_url": endpoint,
        "headers": {
            "Authorization": f"Bearer {token}",
            "Foundry-Features": "Toolboxes=V1Preview",
        },
        "require_approval": "never",
    }


def instructions(mode: str) -> str:
    nonce = uuid.uuid4()
    base = (
        f"nonce-{nonce}. You are a terse banking assistant. Use MCP tools when needed. "
        "Return compact JSON only."
    )
    if mode.startswith("toolbox"):
        base += (
            " When using a Foundry toolbox, use tool_search to discover hidden tools and call_tool "
            "to invoke discovered tools. If an exact auto-pinned business tool is already visible, call it directly. "
            "Never invent toolbox tool names. Use only exact tool names returned by tools/list or tool_search. "
            "If a search result does not include the exact needed tool, search again with the exact target tool name."
        )
    return base


def run_native_response(client: Any, model: str, scenario: Scenario, mode: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    response = create_response_with_retry(
        client,
        model=model,
        instructions=instructions(mode),
        input=scenario.prompt,
        tools=tools,
        temperature=0
    )
    usage = usage_dict(response)
    text = output_text(response)
    trace = response_trace(response)
    return {
        "mode": mode,
        "scenario": scenario.name,
        "correct": is_correct(text, scenario.expected_markers),
        **usage,
        "mcp_calls": sum(1 for item in trace if item["type"] == "mcp_call"),
        "trace": trace,
        "answer": text,
    }


def create_response_with_retry(client: Any, **kwargs: Any) -> Any:
    for attempt in range(6):
        try:
            return client.responses.create(**kwargs)
        except RateLimitError:
            if attempt == 5:
                raise
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("Responses API retry loop exhausted")


async def main_async(args: argparse.Namespace) -> None:
    load_dotenv(args.env_file)
    credential = InteractiveBrowserCredential(
        cache_persistence_options=TokenCachePersistenceOptions(name="foundry-toolbox-search"),
        timeout=900,
    )
    print("Authenticating to Azure - complete the browser sign-in once if prompted.")
    credential.get_token("https://ai.azure.com/.default")
    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential)
    client = project.get_openai_client()
    model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-5.4-mini")

    endpoints = [
        McpEndpoint("loans", os.environ["MCP_LOANS_URL"]),
        McpEndpoint("investments", os.environ["MCP_INVESTMENTS_URL"]),
        McpEndpoint("accounts", os.environ["MCP_ACCOUNTS_URL"]),
    ]
    existing_toolbox = McpEndpoint("toolbox", os.environ["TOOLBOX_ENDPOINT"], foundry_toolbox=True)
    direct_mcp_tool_count = 0
    for endpoint in endpoints:
        direct_mcp_tool_count += len(await list_tools(endpoint))
    metadata: dict[str, Any] = {
        "direct_mcp_tool_count": direct_mcp_tool_count,
        "existing_toolbox_initial_tools": [tool.name for tool in await list_tools(existing_toolbox, credential)],
        "measurement_implementation": "native Responses API MCP tools; no discovered schemas are added to tools array",
    }

    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        direct_row = run_native_response(
            client,
            model,
            scenario,
            "direct-mcp",
            direct_mcp_tools(endpoints, uuid.uuid4().hex[:8]),
        )
        rows.append(direct_row)
        print(json.dumps(direct_row, indent=2))

        if args.auto_pin_experiment:
            suffix = f"{scenario.name}-{int(time.time())}"
            cold_name = f"{args.toolbox_prefix}-cold-{suffix}"
            warm_name = f"{args.toolbox_prefix}-warm-{suffix}"
            cold_url = create_toolbox(project, cold_name, endpoints)
            warm_url = create_toolbox(project, warm_name, endpoints)
            cold_endpoint = McpEndpoint(cold_name, cold_url, foundry_toolbox=True)
            warm_endpoint = McpEndpoint(warm_name, warm_url, foundry_toolbox=True)
            cold_initial = [tool.name for tool in await list_tools(cold_endpoint, credential)]
            warm_before = [tool.name for tool in await list_tools(warm_endpoint, credential)]

            metadata[scenario.name] = {
                "cold_toolbox_name": cold_name,
                "cold_initial_tools": cold_initial,
                "warm_toolbox_name": warm_name,
                "warm_initial_tools_before_warmup": warm_before,
            }
            for index in range(args.warmup_runs):
                print(f"Warmup {scenario.name} run {index + 1}/{args.warmup_runs}")
                run_native_response(client, model, scenario, "toolbox-warmup", [toolbox_mcp_tool(warm_url, credential)])
            if args.auto_pin_wait_seconds:
                print(f"Waiting {args.auto_pin_wait_seconds}s for {scenario.name} auto-pin updates")
                await asyncio.sleep(args.auto_pin_wait_seconds)
            warm_after = [tool.name for tool in await list_tools(warm_endpoint, credential)]
            metadata[scenario.name]["warm_initial_tools_after_warmup"] = warm_after

            cold_row = run_native_response(client, model, scenario, "toolbox-cold-search", [toolbox_mcp_tool(cold_url, credential)])
            rows.append(cold_row)
            print(json.dumps(cold_row, indent=2))
            warm_row = run_native_response(client, model, scenario, "toolbox-warm-auto-pin", [toolbox_mcp_tool(warm_url, credential)])
            rows.append(warm_row)
            print(json.dumps(warm_row, indent=2))
        else:
            row = run_native_response(client, model, scenario, "toolbox-search", [toolbox_mcp_tool(existing_toolbox.url, credential)])
            rows.append(row)
            print(json.dumps(row, indent=2))

    Path(args.output).write_text(json.dumps({"metadata": metadata, "rows": rows}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure native Responses MCP vs Foundry toolbox tool search.")
    parser.add_argument("--env-file", default=".env.generated")
    parser.add_argument("--output", default="measurement/results.json")
    parser.add_argument("--auto-pin-experiment", action="store_true")
    parser.add_argument("--toolbox-prefix", default="fsi-autopin")
    parser.add_argument("--warmup-runs", type=int, default=2)
    parser.add_argument("--auto-pin-wait-seconds", type=int, default=60)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
