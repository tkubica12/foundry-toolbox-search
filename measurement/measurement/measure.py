from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.core.credentials import TokenCredential
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv

from measurement.mcp_client import McpEndpoint, call_tool, list_tools, tool_to_schema


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
            "For customer c123, answer with compact JSON only. Use tools to get three values. "
            "For toolbox mode, do three separate focused tool searches instead of one broad search: "
            "search 'mortgage affordability annual income monthly debt' with limit 1, then call the exact discovered affordability tool "
            "with annual income 96000 and monthly debt 700; search 'portfolio summary market value customer portfolio' with limit 1, "
            "then call the exact discovered portfolio summary tool for portfolio PF-42; search 'current account KYC status customer' with limit 1, "
            "then call the exact discovered account KYC status tool for customer c123. "
            "Include markers."
        ),
        expected_markers=("LOAN-DEMO-C123", "INV-DEMO-C123", "ACCT-DEMO-C123", "2180", "248500", "current"),
    ),
]


def usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
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


def function_calls(response: Any) -> list[Any]:
    return [item for item in getattr(response, "output", []) or [] if getattr(item, "type", None) == "function_call"]


def add_discovered_tool_schemas(
    tools: list[dict[str, Any]],
    dispatch: dict[str, tuple[McpEndpoint, str]],
    endpoint: McpEndpoint,
    tool_search_result: str,
) -> None:
    try:
        payload = json.loads(tool_search_result)
    except json.JSONDecodeError:
        return
    existing = {tool["name"] for tool in tools}
    for discovered in payload.get("tools", []):
        name = discovered.get("name")
        if not name or name in existing:
            continue
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": discovered.get("description") or f"Call discovered toolbox tool {name}",
                "parameters": discovered.get("inputSchema") or {"type": "object", "properties": {}},
            }
        )
        dispatch[name] = (endpoint, "__toolbox_discovered__")
        existing.add(name)


def resolve_toolbox_tool_name(requested: str, dispatch: dict[str, tuple[McpEndpoint, str]]) -> str:
    if requested in dispatch:
        return requested

    normalized = requested.lower().replace("-", "_")
    candidates = [
        name for name, (_, target) in dispatch.items()
        if target == "__toolbox_discovered__"
    ]
    for candidate in candidates:
        suffix = candidate.split("___", 1)[-1].lower()
        if normalized == suffix or normalized in suffix:
            return candidate

    requested_tokens = {token for token in normalized.split("_") if token}
    best_match = ""
    best_score = 0
    for candidate in candidates:
        candidate_tokens = {token for token in candidate.lower().replace("___", "_").split("_") if token}
        score = len(requested_tokens & candidate_tokens)
        if score > best_score:
            best_score = score
            best_match = candidate
    return best_match or requested


async def build_direct_tools(endpoints: list[McpEndpoint]) -> tuple[list[dict[str, Any]], dict[str, tuple[McpEndpoint, str]]]:
    tools: list[dict[str, Any]] = []
    dispatch: dict[str, tuple[McpEndpoint, str]] = {}
    for endpoint in endpoints:
        for tool in await list_tools(endpoint):
            exposed = f"{endpoint.label}__{tool.name}"
            tools.append(tool_to_schema(tool, exposed))
            dispatch[exposed] = (endpoint, tool.name)
    return tools, dispatch


async def build_toolbox_tools(endpoint: McpEndpoint, credential: TokenCredential) -> tuple[list[dict[str, Any]], dict[str, tuple[McpEndpoint, str]]]:
    tools = await list_tools(endpoint, credential)
    return [tool_to_schema(tool) for tool in tools], {tool.name: (endpoint, tool.name) for tool in tools}


async def run_agent_loop(
    client: Any,
    model: str,
    prompt: str,
    tools: list[dict[str, Any]],
    dispatch: dict[str, tuple[McpEndpoint, str]],
    credential: TokenCredential | None = None,
) -> tuple[str, dict[str, int], int, list[dict[str, Any]]]:
    tool_names = {tool["name"] for tool in tools}
    instructions = "You are a terse banking assistant. Use tools when needed. Final answer must be compact JSON only."
    if {"tool_search", "call_tool"}.issubset(tool_names):
        instructions += (
            " You have a Foundry toolbox. tool_search only discovers candidate tools and never returns business data. "
            "For every requested business value, first use tool_search if needed, then invoke the selected tool via call_tool. "
            "Use narrow, separate tool_search calls with limit 1 for unrelated domains rather than one broad search. "
            "Prefer exact semantic matches such as get_portfolio_summary for portfolio market value summary requests, "
            "and check_account_kyc_status for current-account KYC status requests. "
            "Never answer from tool_search results alone."
        )
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
        tools=tools,
        temperature=0,
    )
    totals = usage_dict(response)
    tool_calls = 0
    trace: list[dict[str, Any]] = []
    while function_calls(response):
        follow_up: list[dict[str, Any]] = []
        for call in function_calls(response):
            tool_calls += 1
            endpoint, mcp_name = dispatch[call.name]
            arguments = json.loads(call.arguments or "{}")
            if endpoint.foundry_toolbox and mcp_name == "tool_search":
                arguments["limit"] = 1
            if mcp_name == "__toolbox_discovered__":
                result = await call_tool(endpoint, "call_tool", {"name": call.name, "arguments": arguments}, credential)
            elif endpoint.foundry_toolbox and mcp_name == "call_tool":
                requested_name = str(arguments.get("name", ""))
                arguments = {
                    **arguments,
                    "name": resolve_toolbox_tool_name(requested_name, dispatch),
                }
                result = await call_tool(endpoint, mcp_name, arguments, credential)
            else:
                result = await call_tool(endpoint, mcp_name, arguments, credential)
            if endpoint.foundry_toolbox and mcp_name == "tool_search":
                add_discovered_tool_schemas(tools, dispatch, endpoint, result)
            trace.append({"tool": call.name, "arguments": arguments, "result_preview": result[:1000]})
            follow_up.append({"type": "function_call_output", "call_id": call.call_id, "output": result})
        response = client.responses.create(
            model=model,
            previous_response_id=response.id,
            input=follow_up,
            tools=tools,
            temperature=0,
        )
        next_usage = usage_dict(response)
        for key, value in next_usage.items():
            totals[key] = totals.get(key, 0) + value
    return output_text(response), totals, tool_calls, trace


def is_correct(text: str, markers: tuple[str, ...]) -> bool:
    return all(marker in text for marker in markers)


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

    direct_endpoints = [
        McpEndpoint("loans", os.environ["MCP_LOANS_URL"]),
        McpEndpoint("investments", os.environ["MCP_INVESTMENTS_URL"]),
        McpEndpoint("accounts", os.environ["MCP_ACCOUNTS_URL"]),
    ]
    toolbox_endpoint = McpEndpoint("toolbox", os.environ["TOOLBOX_ENDPOINT"], foundry_toolbox=True)

    direct_tools, direct_dispatch = await build_direct_tools(direct_endpoints)
    base_toolbox_tools, base_toolbox_dispatch = await build_toolbox_tools(toolbox_endpoint, credential)
    print(f"Direct tool schemas exposed: {len(direct_tools)}")
    print(f"Toolbox schemas exposed initially: {len(base_toolbox_tools)}")

    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for mode, tools, dispatch in [
            ("direct-mcp", direct_tools, direct_dispatch),
            ("toolbox-search", deepcopy(base_toolbox_tools), dict(base_toolbox_dispatch)),
        ]:
            text, usage, tool_calls, trace = await run_agent_loop(
                client,
                model,
                scenario.prompt,
                tools,
                dispatch,
                credential if mode == "toolbox-search" else None,
            )
            row = {
                "mode": mode,
                "scenario": scenario.name,
                "correct": is_correct(text, scenario.expected_markers),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
                "tool_calls": tool_calls,
                "trace": trace,
                "answer": text,
            }
            rows.append(row)
            print(json.dumps(row, indent=2))

    Path(args.output).write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure direct MCP vs Foundry toolbox tool search.")
    parser.add_argument("--env-file", default=".env.generated")
    parser.add_argument("--output", default="measurement/results.json")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
