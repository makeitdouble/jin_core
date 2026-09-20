# blender_mcp

Control the user's live Blender scene through the community **MCP for Blender** server.
This skill is an MCP adapter, not a Blender-specific native JIN action. The authoritative
list of available tools and their JSON Schemas is appended at runtime inside
`<MCP_RUNTIME>...</MCP_RUNTIME>` after this skill is loaded.

<MCP_SERVER>
{
  "transport": "stdio",
  "command": "uvx",
  "args": ["mcp-for-blender"],
  "read_timeout_seconds": 180
}
</MCP_SERVER>

## Runtime contract

Use only the live tools exposed in `<MCP_RUNTIME>`. Never invent a Blender MCP tool name,
argument, enum, or schema from memory. Invoke every Blender MCP tool through JIN's single
generic action:

```xml
<CALL_MCP>
{"skill":"blender_mcp","tool":"EXACT_LIVE_TOOL_NAME","arguments":{}}
</CALL_MCP>
```

`skill` must stay exactly `blender_mcp`. `tool` must be an exact live MCP tool name and
`arguments` must match that tool's current input schema.

When a live tool exposes a `user_prompt` argument, pass the user's own request verbatim.
On automatic follow-ups, reuse the same last real user request verbatim rather than replacing
it with an internal sub-goal such as "create cube", "check result", or "continue".

## Default working loop

For a scene-editing request, work iteratively instead of declaring success after a blind edit:

1. Inspect Blender/add-on status when a matching live status tool exists, especially on the
   first Blender action in a session.
2. Inspect the current scene before editing it. Prefer a live scene-info/world-state tool when
   available.
3. Make one coherent scene change or a small related batch of changes.
4. After a meaningful visual change, request a viewport screenshot using the matching live
   screenshot tool when available.
5. On the next JIN follow-up, actually inspect the returned image attachment. If something is
   obviously wrong (camera framing, object placement, scale, material, lighting, missing
   geometry), fix it and request another screenshot.
6. Before the final answer, verify both the visible result and scene state when practical.

Screenshots returned by MCP become JIN follow-up image attachments automatically. Treat them
as visual evidence, not merely as a successful tool result.

## Scene safety

- Inspect before destructive edits.
- If the scene is clearly Blender's trivial/default scene and the user asks to build a new
  scene, removing/replacing the default objects is acceptable.
- If the scene contains meaningful existing work, do not delete or overwrite it unless the
  user's request clearly requires that.
- Prefer deterministic, reversible scene operations and stable object names.
- Do not touch unrelated files, launch shell commands, access the network, install packages,
  or persist background code from Blender Python unless the user explicitly asks for it.
- External asset services (Poly Haven, Sketchfab, generated 3D assets, etc.) are optional;
  do not use them unless the task needs them or the user asks.

## Blender Python fallback

If the live MCP catalog exposes a Blender-Python execution tool, it may be used when no more
specific live tool can perform the requested edit. Keep scripts small and scene-focused.
Use APIs supported by the Blender version reported by the connected add-on; do not assume
Blender 4.x features when the user is running Blender 3.x.

For materials, modifiers, render settings, node trees, and enum values, inspect the connected
Blender state/API when possible instead of hardcoding version-sensitive identifiers. Prefer
node `type`/`bl_idname` and other stable identifiers over UI-localized node names.

## Visual construction strategy

For ordinary mini-scenes, favor simple native geometry and materials first. Build composition
in layers: major forms -> transforms -> materials -> lights/camera -> visual verification.
Keep the first pass cheap and readable. Add complexity only when it improves the requested
result.

A task is not complete merely because an edit call returned success. For visual scene work,
try to obtain at least one post-edit screenshot and inspect it before saying the scene is done.

## Connection failures

If Blender MCP reports that it cannot connect to Blender, the add-on/socket is probably not
running. Do not loop the same failing call indefinitely. Surface the connection problem clearly
so the user can start the Blender-side MCP server, then continue from the current scene on the
next turn.
