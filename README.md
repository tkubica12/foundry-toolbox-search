# Foundry toolbox search demo

Demo showing how Microsoft Foundry Toolboxes simplify many MCP servers into one endpoint and how Tool Search reduces model-side input tokens through progressive disclosure.

Docs: [MCP tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol), [Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox), [Tool Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/tool-search).

## Layout

| Folder | Purpose |
| --- | --- |
| `infra` | Provision Azure resources, deploy MCP servers, create Foundry toolbox. |
| `mcp_servers` | Three mocked FSI MCP domains: loans, investments, accounts. |
| `measurement` | Local/cloud MCP checks and token comparison runs. |

## Results

Measured with `gpt-5.4-mini` in Sweden Central. Token counts are model-side usage from `response.usage`; Foundry Tools compute for `tool_search` is not included.

| Scenario | Prompt | Correct | Input tokens | Output tokens |
| --- | --- | --- | ---: | ---: |
| Direct MCP | One loan tool | Yes | 6,096 | 91 |
| Toolbox + Tool Search | One loan tool | Yes | 1,041 | 98 |
| Direct MCP | Three domain tools | Yes | 13,047 | 273 |
| Toolbox + Tool Search | Three domain tools | Yes | 7,452 | 291 |
