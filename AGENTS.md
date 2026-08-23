# AGENTS.md — JIN Core Engine

This file is the mandatory entry point for any coding agent working in this repository.

## Read order before changing code

1. Read `AGENTS.md`.
2. Read the relevant sections of `docs/JIN_ARCHITECTURE.md`.
3. Read `docs/JIN_DECISIONS.md` for product-intent constraints and rejected directions.
4. Read `docs/JIN_CURRENT_STATE.md` for transitional formats, stale legacy, known conflicts, and test status.
5. Inspect the current implementation end-to-end before editing it.

Do not treat `README.md`, the old root `ARCHITECTURE.md`, old tests, comments, filenames, or search indexes as stronger evidence than the current source tree plus these documents. If sources conflict, report the conflict instead of silently choosing one.

## Source precedence

Use this order when deciding what is true:

1. Current source code for **what is implemented now**.
2. `docs/JIN_DECISIONS.md` for **what the product is intended to mean**.
3. `docs/JIN_CURRENT_STATE.md` for **known migrations/conflicts/temporary compatibility**.
4. Historical docs/tests/comments only as legacy evidence.

A current implementation can still violate a product decision. Do not hide that. State both sides and ask before changing product semantics.

## Architectural invariants

- JIN Core Engine is a model-agnostic cognitive runtime, not a chatbot skin and not a framework tied to one LLM.
- The normal model path is direct: user turn -> `AgentRuntime` -> `BrainNode`. Do not add a pre-Brain routing framework without an explicit task.
- `RuntimeContext` is the in-process live state hub for a runtime session. Do not create parallel sources of truth for state it already owns.
- L2 and L3 are **removed architectural layers**. Do not restore them from old README/tests/indexes. Any surviving L2/L3 names must be classified as compatibility, stale tests/docs, UI residue, or dead legacy before touching them.
- Durable facts belong in L4. Do not reintroduce a durable-L1/L2/L3 memory hierarchy.
- Active Memory, Delayed Memory, L4 facts, persistent Files, live L1/runtime memory, and session checkpoints are different systems with different lifetimes. Do not collapse them into one generic memory store.
- Session continuity must distinguish completed turns from interrupted turns and must preserve original timestamps where available.
- Browser checkpoint `saved_at` is a causal freshness boundary for archive enrichment, not a generic "last touched" timestamp. A field-local mutation must not advance it unless the whole checkpoint is genuinely refreshed.
- In predecessor bootstrap, an explicitly present `tool_results: []` is an authoritative cleared value. Do **not** generalize that tombstone rule to `loaded_memory_ids` or `active_memory_records`; their empty browser values still retain archive-fallback semantics.
- Session-action history is structured continuity data. Preserve supported part metadata across persistence/bootstrap (for example JIN_COLOR `parts[].colors`), not only the visible action text.
- Archived restore intentionally stages historical resources and replays them through the real action path after the one-shot restore response. Do not add a second late apply path.
- Anonymous/shadow mode may read global durable context but must not silently perform restricted persistent writes.

## Runtime actions

- `contracts/*.json` are the canonical model-facing contracts for concrete action schemas and action-specific rules.
- Keep `rules/runtime.py` for cross-action sequencing/loop invariants, not duplicated field-by-field action instructions.
- Every new action needs: contract -> parser/normalization -> guard if needed -> dispatcher/handler -> emitted state/result -> tests.
- Streaming can split markers at arbitrary chunk boundaries. Always test complete, split, repeated, incomplete, false-prefix, and flush/stop cases.
- Do not let private action markers leak into visible answer text.
- Do not emit the same action twice because two parser paths recognized the same marker.
- Current Delayed save contract is `<SAVE_DELAYED_MEMORY>` with a JSON body. The old `<SAVE_DELAYED_MEMORY_CONTENT>` key/value format is legacy only.
- Current Active create/update model boundary is flat JSON. `SAVE_ACTIVE_MEMORY` custom fields must come from explicit structured JSON; plain prose such as a trailing `(field: value)` is still prose/conditions, not schema. Legacy nested update payloads and self-closing UPDATE attributes may be accepted locally for compatibility; do not advertise them as preferred syntax.
- Search actions are effective only when the configured provider is actually available (`settings.CAN_SEARCH`). Feature flags alone must not expose `WEB_SEARCH`/`DEEP_WEB_SEARCH`; do not invent client-side API-key shape regexes when the provider has no stable key-shape contract.
- `CLEAN_TOOL_RESULTS` is a no-payload marker. Bare `<CLEAN_TOOL_RESULTS>` and the redundant paired form must execute once; any closing tag is parser noise and must be consumed even across stream chunks.
- `SAVE_SESSION` is not a current runtime-action contract in this snapshot. Treat old references as legacy/session-restore compatibility until proven otherwise.

## UI / visual language

Before introducing any visual state, find and reuse the closest existing JIN UI primitive.

- Do not invent new highlight colors, glows, banners, badges, icons, gradients, or interaction patterns without explicit owner approval.
- Reuse existing DOM structure, CSS variables, typography, radius, spacing, animation, and semantic states whenever possible.
- Color already carries runtime meaning. A new decorative color is not harmless.
- Loaded context, mere ID reference, pin state, pause state, inspect/modal open, and delete/restore are different semantics. Do not map all of them to one generic `highlight()` call.
- For UI fixes, verify the actual rendered DOM/event path, not only data/state mutation.
- For bootstrap/restore visual fixes, locate every writer and prove there is one authoritative final apply path.
- Session-action interruption telemetry is causal UI state: validator/reasoning loops and context/output-limit recovery entries must be recorded/emitted when detected, before automatic follow-up/recovery starts.
- L4 rows use a short default preview (currently 50 characters), but a fact that is bubbled by reference/citation/context-loaded state must show its full value rather than a truncated citation.
- Hover/detail metadata must survive non-semantic refreshes: counter-only runtime-action updates and bootstrap normalization must not silently erase tooltip/swatch data.
- Do not add `backdrop-filter`/blur or new translucent effects casually. Existing shadow/tint depth is deliberate.

## Change discipline

- Respect the requested scope. If asked to analyze only, do not edit.
- Prefer the smallest coherent fix over architectural tourism.
- Do not duplicate an existing listener, timer, writer, parser, storage path, or style primitive just to make a symptom disappear.
- Do not mass-format files or change line endings for a narrow fix.
- Do not add dependencies without a concrete need.
- Preserve existing user changes. Do not overwrite unrelated dirty work.
- Compatibility belongs in a localized adapter, not scattered across runtime/UI/rules.
- Do not guess IDs, state owners, ordering, or root causes.

## Required investigation before a patch

Trace the affected flow through all relevant stages:

`source -> normalization -> canonical owner -> persistence -> bootstrap/restore -> prompt/action path -> emitted event -> UI projection -> tests`

For stateful bugs, find **all readers and all writers**. For visual bugs, find every writer of the relevant CSS variable/DOM state. For runtime actions, find every parser and dispatcher path that can emit the same action.

## Verification

At minimum, run the checks that apply to the change:

- syntax/import check;
- targeted unit/client-contract tests;
- `git diff --check` when git metadata is available;
- targeted search for the removed/renamed format;
- duplicate writer/listener/timer search;
- serialize -> reload -> hydrate round trip for restore/state changes;
- explicit-empty-vs-missing tests for bootstrap fields, plus checkpoint timestamp/lineage invariance for field-only cleanup;
- structured session-action metadata round trip (including JIN_COLOR swatch/hex hover);
- chunk-boundary tests for stream/action parsing;
- legacy-record + modern-record tests for compatibility/timestamps;
- real DOM/render-path check for UI behavior;
- search capability tests with configured/blank/placeholder provider credentials when touching search contracts or prompt exposure;
- patch apply check against the exact source snapshot when delivering `.patch`.

Do not claim the repository is green unless the relevant tests actually pass. See `docs/JIN_CURRENT_STATE.md` for the current full-suite status of the 2026-08-23 snapshot.

## Handoff format

When you finish a coding task, report:

1. root cause;
2. files changed;
3. exact behavior changed;
4. checks/tests run and their result;
5. remaining assumptions/risks;
6. any conflict between current code and documented product intent.

Keep this file short. Put architecture detail in `docs/JIN_ARCHITECTURE.md`, durable decisions in `docs/JIN_DECISIONS.md`, and migrations/known conflicts in `docs/JIN_CURRENT_STATE.md`.
