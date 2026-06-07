# Foundry toolbox search demo

Demo showing how Microsoft Foundry Toolboxes simplify many MCP servers into one endpoint and how Tool Search reduces model-side input tokens through progressive disclosure.

Docs: [MCP tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol), [Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox), [Tool Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/tool-search).

## Layout

| Folder | Purpose |
| --- | --- |
| `infra` | Provision Azure resources, deploy MCP servers, create Foundry toolbox. |
| `mcp_servers` | Three mocked FSI MCP domains: loans, investments, accounts. |
| `measurement` | Local/cloud MCP checks and token comparison runs. |

## Reference JSON

These files show what the agent sees in context and what `tool_search` returns:

| File | What it shows |
| --- | --- |
| [`standalone-mcp-tools.json`](measurement/context/standalone-mcp-tools.json) | Raw `tools/list` output from the three standalone MCP servers. |
| [`direct-agent-tools.json`](measurement/context/direct-agent-tools.json) | Tool schemas passed to the model in direct MCP mode. |
| [`cold-toolbox-tools.json`](measurement/context/cold-toolbox-tools.json) | Fresh toolbox `tools/list`: only `tool_search` and `call_tool`. |
| [`warm-toolbox-tools.json`](measurement/context/warm-toolbox-tools.json) | Warmed toolbox `tools/list` after auto-pin. |
| [`tool-search-results.json`](measurement/context/tool-search-results.json) | Raw `tool_search` responses for demo search queries. |

Toolbox `tools/list` can change after use because Foundry auto-pin is service-managed; measurement metadata in `results-autopin.json` records the true initial cold/warm lists observed before each run.

## Results

Measured with `gpt-5.4-mini` in Sweden Central against 150 mocked MCP tools using the native Responses API MCP tool pattern. The measurement does not add discovered toolbox schemas back into the `tools` array; the model calls the toolbox MCP endpoint directly (`tool_search` then `call_tool`). Inputs are uncached/full-price because each measured request uses a random instruction nonce, and direct MCP also uses cache-busted URLs and random server labels. Foundry Tools compute for `tool_search` is not included. Cold toolboxes are fresh per scenario and expose only `tool_search` and `call_tool`; warm toolboxes are separate per scenario and measured after two warmup runs.

| Scenario | Prompt | Correct | Input | Output | MCP calls |
| --- | --- | --- | ---: | ---: | ---: |
| Direct MCP | One loan tool | Yes | 8,148 | 107 | 1 |
| Cold toolbox + Tool Search | One loan tool | Yes | 2,025 | 175 | 3 |
| Warm toolbox + auto-pin | One loan tool | Yes | 565 | 90 | 1 |
| Direct MCP | Three domain tools | Yes | 8,397 | 223 | 3 |
| Cold toolbox + Tool Search | Three domain tools | Yes | 2,333 | 321 | 6 |
| Warm toolbox + auto-pin | Three domain tools | Yes | 874 | 228 | 3 |

Interpretation: direct MCP imports all 150 tool schemas. Cold toolbox keeps the visible schema set tiny but pays extra MCP calls for `tool_search`. Warm toolbox is best because auto-pin makes frequent tools directly callable and removes search calls while keeping the visible schema set small.

Approximate model cost per 1,000 requests using `gpt-5.4-mini` prices of $0.75 / 1M input tokens and $4.50 / 1M output tokens:

| Scenario | Prompt | Input cost | Output cost | Total |
| --- | --- | ---: | ---: | ---: |
| Direct MCP | One loan tool | $6.11 | $0.48 | $6.59 |
| Cold toolbox + Tool Search | One loan tool | $1.52 | $0.79 | $2.31 |
| Warm toolbox + auto-pin | One loan tool | $0.42 | $0.41 | $0.83 |
| Direct MCP | Three domain tools | $6.30 | $1.00 | $7.30 |
| Cold toolbox + Tool Search | Three domain tools | $1.75 | $1.44 | $3.20 |
| Warm toolbox + auto-pin | Three domain tools | $0.66 | $1.03 | $1.68 |
