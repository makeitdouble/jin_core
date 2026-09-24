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

Legacy SSE is also accepted with `"transport":"sse"` and a URL. `"http"` and `"streamable-http"` are compatibility aliases for `"streamable_http"`. Any supported transport may set a positive `read_timeout_seconds`.

`env_from_host` copies named host environment variables into a stdio server process without putting their values into the model payload. It can be a string array (`["TOKEN"]`) or a mapping (`{"CHILD_TOKEN":"HOST_TOKEN"}`). Stdio may also set `cwd`. Static scalar `env` values are supported, but because the skill body is model-visible they should not contain secrets.

## Load and discovery

Brain first loads the skill normally:

```xml
<LOAD_SKILLS_CONTEXT> blender_mcp </LOAD_SKILLS_CONTEXT>
```

For a valid MCP skill the runtime connects to the declared server and runs `tools/list`. The discovered server identity/instructions plus live tool names, descriptions, and input JSON Schemas are appended only to the in-memory loaded skill as `<MCP_RUNTIME>...</MCP_RUNTIME>`; the source `JIN_SKILL.md` is not modified. Static server metadata is kept here once instead of being repeated in every tool result.

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

The runtime exposes `CALL_MCP` only while at least one valid MCP skill is loaded and refuses to route a call to an unloaded/invalid skill. MCP calls are deliberately excluded from JIN's result-reuse cache because identical calls may represent state-changing operations and must execute again only when Brain explicitly emits them in a later follow-up. Canonical payloads are valid JSON; the parser also tolerates literal control characters in JSON strings for provider compatibility.

## Lifecycle

Each loaded skill gets one persistent MCP connection owned by a dedicated asyncio worker task. This keeps the SDK transport enter/use/exit lifecycle on one task while preserving server/session state across JIN follow-ups. The connection is closed when the skill is unloaded or the runtime transport is retired.

A changed `<MCP_SERVER>` config creates a fresh connection automatically.

## Images and screenshots

If an MCP tool returns an MCP image content block, JIN:

1. decodes it with a 20 MiB per-image safety limit;
2. stores it in `assets/files/` with a normal JIN file id;
3. removes the raw base64 from the tool result;
4. adds the hydrated image to both the current turn/sequence attachment state and pinned-file snapshot for the automatic Brain follow-up.

This lets Blender/render/vision-style MCP tools return a screenshot or render that the Brain can actually inspect on the next step instead of seeing only a path or a large base64 string.

## UI projection

Session Actions keeps MCP calls compact as `CALL_MCP: skill / tool`. The runtime-action bubble carries the parsed request, result, and raw payload; clicking a generic MCP call opens the structured MCP trace instead of dumping raw JSON. The `get_viewport_screenshot` tool is special only in presentation: when it returns a hydrated image attachment, hover/click reuses JIN's normal attachment preview/modal path.

## Dependency

JIN uses the official Python MCP SDK (`mcp==2.2.0`). The runtime imports it lazily, so ordinary non-MCP use does not initialize an MCP client.
