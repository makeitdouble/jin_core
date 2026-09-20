# MCP Skills

JIN exposes MCP through one generic runtime action: `CALL_MCP`. A concrete integration is a normal skill directory whose `JIN_SKILL.md` contains both human-facing usage guidance and one machine-readable server declaration.

## Skill layout

```text
assets/skills/
`-- blender_mcp/
    `-- JIN_SKILL.md
```

Minimal stdio declaration:

```md
# blender_mcp

<MCP_SERVER>
{
  "transport": "stdio",
  "command": "python",
  "args": ["path/to/server.py"],
  "env_from_host": ["OPTIONAL_API_KEY"]
}
</MCP_SERVER>

Use this skill to inspect and modify the Blender scene.
Prefer reading scene state before destructive edits.
```

Streamable HTTP:

```md
<MCP_SERVER>
{
  "transport": "streamable_http",
  "url": "http://127.0.0.1:9000/mcp"
}
</MCP_SERVER>
```

Legacy SSE is also accepted with `"transport":"sse"` and a URL.

`env_from_host` copies named host environment variables into a stdio server process without putting their values into the model payload. It can be a string array (`["TOKEN"]`) or a mapping (`{"CHILD_TOKEN":"HOST_TOKEN"}`). Static `env` values are also supported, but because the skill body is model-visible they should not contain secrets.

## Load and discovery

Brain first loads the skill normally:

```xml
<LOAD_SKILLS_CONTEXT> blender_mcp </LOAD_SKILLS_CONTEXT>
```

For a valid MCP skill the runtime connects to the declared server and runs `tools/list`. The discovered live tool names, descriptions, and input JSON Schemas are appended only to the in-memory loaded skill as `<MCP_RUNTIME>...</MCP_RUNTIME>`; the source `JIN_SKILL.md` is not modified.

The skill text therefore owns semantic guidance (when/how/why to use the integration), while the server owns the live technical tool schema.

## Calling a tool

Every MCP integration uses the same native JIN action:

```xml
<CALL_MCP>
{"skill":"blender_mcp","tool":"create_cube","arguments":{"size":2}}
</CALL_MCP>
```

Required fields:

- `skill`: exact loaded MCP skill name;
- `tool`: exact tool name from the loaded skill/live tool catalog;
- `arguments`: one JSON object matching the MCP tool input schema.

The runtime refuses to route `CALL_MCP` to an unloaded skill or a loaded skill without a valid MCP declaration. MCP calls are deliberately excluded from JIN's result-reuse cache because identical calls may represent state-changing operations and must execute again only when Brain explicitly emits them in a later follow-up.

## Lifecycle

Each loaded skill gets one persistent MCP connection owned by a dedicated asyncio worker task. This keeps the SDK transport enter/use/exit lifecycle on one task while preserving server/session state across JIN follow-ups. The connection is closed when the skill is unloaded or the runtime transport is retired.

A changed `<MCP_SERVER>` config creates a fresh connection automatically.

## Images and screenshots

If an MCP tool returns an MCP image content block, JIN:

1. decodes it with a 20 MiB per-image safety limit;
2. stores it in `assets/files/` with a normal JIN file id;
3. removes the raw base64 from the tool result;
4. adds the hydrated image to `runtime_turn_attachments` for the automatic Brain follow-up.

This lets Blender/render/vision-style MCP tools return a screenshot or render that the Brain can actually inspect on the next step instead of seeing only a path or a large base64 string.

## Dependency

JIN uses the official Python MCP SDK (`mcp==2.2.0`). The runtime imports it lazily, so ordinary non-MCP use does not initialize an MCP client.
