from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from azure.core.credentials import TokenCredential
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@dataclass(frozen=True)
class McpEndpoint:
    label: str
    url: str
    foundry_toolbox: bool = False


def _headers(endpoint: McpEndpoint, credential: TokenCredential | None) -> dict[str, str] | None:
    if not endpoint.foundry_toolbox:
        return None
    if credential is None:
        raise ValueError("Foundry toolbox endpoint requires a credential.")
    token = credential.get_token("https://ai.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Foundry-Features": "Toolboxes=V1Preview"}


async def list_tools(endpoint: McpEndpoint, credential: TokenCredential | None = None) -> list[Any]:
    async with streamablehttp_client(endpoint.url, headers=_headers(endpoint, credential)) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)


async def call_tool(endpoint: McpEndpoint, name: str, arguments: dict[str, Any], credential: TokenCredential | None = None) -> str:
    async with streamablehttp_client(endpoint.url, headers=_headers(endpoint, credential)) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)
            chunks: list[str] = []
            for item in result.content:
                text = getattr(item, "text", None)
                if text is not None:
                    chunks.append(text)
                else:
                    chunks.append(json.dumps(item.model_dump(mode="json"), default=str))
            structured = getattr(result, "structuredContent", None)
            if structured:
                chunks.append(json.dumps(structured, default=str))
            return "\n".join(chunks)


def tool_to_schema(tool: Any, exposed_name: str | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "name": exposed_name or tool.name,
        "description": tool.description or f"Call MCP tool {tool.name}",
        "parameters": tool.inputSchema or {"type": "object", "properties": {}},
    }
