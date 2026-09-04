# AGENTS.md — JIN Core Engine

This file is the mandatory entry point for any coding agent working in this repository.

## Read order before changing code

1. Read `AGENTS.md`.
2. Read the relevant sections of `docs/JIN_ARCHITECTURE.md`.
3. Read `docs/JIN_DECISIONS.md` for product-intent constraints and rejected directions.
4. Read `docs/JIN_CURRENT_STATE.md` for transitional formats, stale legacy, known conflicts, and test status.
5. Inspect the current implementation end-to-end before editing it.

Do not treat README prose, historical docs/tests/comments, filenames, or search indexes as stronger evidence than the current source tree plus these documents. If sources conflict, report the conflict instead of silently choosing one.

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
- Brain is the only foreground response route. `BrainNode` must resolve the canonical `brain` runtime/client; Service must never become a foreground response mode through `SERVICE_CONFIGURED`, model availability, or a legacy flag.
- Service is a logical background role. If no dedicated `SERVICE_API_BASE` is configured, `clients/registry.py` intentionally aliases the Service client to the Brain client; a dedicated Service endpoint changes only background execution.
- `USE_SERVICE_AS_BRAIN` is legacy config input only. `config_loader.py` may migrate it once and then removes the attribute from normalized config; launcher detection exists only to preserve old local configs during startup. Archived `SERVICE` roles/`RUNTIME_MODE=SERVICE` and the logger's old Service-output presentation are reader compatibility, not live routing.
- `RuntimeContext` is the in-process live state hub for a runtime session. Do not create parallel sources of truth for state it already owns.
- L2 and L3 are **removed architectural layers**. Do not restore them from old README/tests/indexes. Any surviving L2/L3 names must be classified as compatibility, stale tests/docs, UI residue, or dead legacy before touching them.
- Durable facts belong in L-T. FRAME is live operational memory; do not reintroduce a durable FRAME/L2/L3 hierarchy.
- Active Memory, Delayed Memory, L-T facts, persistent Files, live FRAME memory, and session checkpoints are different systems with different lifetimes. Do not collapse them into one generic memory store.
- Session continuity must distinguish a real USER move, a completed turn, an interrupted USER-only turn, an action-only completion, and a blank bootstrap tab. A real USER row can become the newest conversation move without a visible JIN row; a blank tab cannot.
- Normal browser continuity has exactly two runtime stores: ephemeral `sessionStorage` key `jin.liveRuntimeMemory.v2` for the current page's soft reconnect, and atomic `localStorage` key `jin.sessionCheckpoint.v2` for reload/new-tab bootstrap. Do not add per-session runtime records or freshness scans.
- The common browser checkpoint names the last runtime session that actually moved. Opening a tab may hydrate inherited FRAME into the ephemeral live record, but must not promote the fresh runtime ID until real user activity or a server-confirmed completed-turn commit.
- Session CLEAR writes a `state: "cleared"` tombstone. Passive runtime, room, color, bootstrap, reconnect, and retry paths must not replace it; only a successfully emitted new USER move may authorize a later checkpoint write.
- Preserve checkpoint lineage: `session_id`, `previous_session_id`, `booted_from_session_id`, nested runtime-snapshot origin, and `conversation_committed_at` have different meanings. Room/avatar field writes must not switch the checkpoint owner.
- Browser checkpoint `saved_at` is a causal freshness boundary for runtime/resource archive enrichment, not a generic "last touched" timestamp. Dialogue freshness is compared tail-to-tail independently. A field-local mutation must not advance `saved_at` unless the whole checkpoint is genuinely refreshed.
- In predecessor bootstrap, an explicitly present `tool_results: []` is an authoritative cleared value. Do **not** generalize that tombstone rule to `loaded_memory_ids` or `active_memory_records`; their empty browser values still retain archive-fallback semantics.
- Session-action history is structured continuity data. Preserve supported part metadata across persistence/bootstrap (for example JIN_COLOR `parts[].colors`), not only the visible action text.
- JIN color belongs to the common `session_snapshot`/room state and server `RuntimeContext`, not to a parallel `latestJinColor` store. The browser checkpoint wins for the same source session; structured action history and raw archive events are recovery sources only.
- Ordinary Brain turns include the previous successful reasoning block. Its projection keeps both edges and may replace only the middle with an explicit `CUTTED N chars` separator; action/recovery follow-ups build their own reasoning context and must not duplicate the ordinary block.
- `<PREVIOUS_CHAT_MESSAGES>` is bounded by the newest three pairs, not by a per-message character cap. Preserve each selected USER/JIN message in full; normalize physical newlines to literal `\\n` without silently truncating content.
- Archived restore intentionally stages historical resources and replays them through the real action path after the one-shot restore response. Do not add a second late apply path.
- Anonymous/shadow mode may read global durable context but must not silently perform restricted persistent writes.

## Runtime actions

- `contracts/*.json` are the canonical model-facing contracts for concrete action schemas and action-specific rules. Every concrete contract keeps its human-readable `schema` lines before `rules`; failed action results reuse that schema instead of inventing a second error-format contract.
- Failed runtime actions are not completion. Render their tool result as readable text (status/reason, supplied payload when relevant, and the correct action schema), then use the shared failure follow-up so Brain continues from the failure rather than assuming the mutation happened.
- Keep `rules/runtime.py` for cross-action sequencing/loop invariants, not duplicated field-by-field action instructions.
- Every new action needs: contract -> parser/normalization -> guard if needed -> dispatcher/handler -> emitted state/result -> tests.
- Streaming can split markers at arbitrary chunk boundaries. Always test complete, split, repeated, incomplete, false-prefix, and flush/stop cases.
- Do not let executable private action markers leak into visible answer text. A marker immediately preceded by an opening quote/backtick/bracket is a literal example: keep it visible and do not execute it, including across stream chunk boundaries.
- Canonical `JIN_COLOR` and `JIN_SIZE` syntax is paired XML with the payload in the body: `<JIN_COLOR> #00f2ff </JIN_COLOR>` and `<JIN_SIZE> w:120 h:120 </JIN_SIZE>`. Inline/colon forms are localized legacy compatibility only. Marker removal must preserve ordinary visible text on both sides of the marker.
- `JIN_SIZE` accepts positive decimal `px`, `vw`, `vh`, and `%` values; unitless values mean `px`. Preserve relative units through parsing/events and resolve them against the live browser viewport only when applying the action. `%` is axis-relative (width -> viewport width, height -> viewport height); `vw` and `vh` always use their named viewport axis. Persist the resulting rendered room geometry in pixels.
- Consecutive JIN visual markers are ordered state events. Drop only a true adjacent/no-op repetition in the same runtime-message scope; preserve alternation such as red -> blue -> red and allow the same color again in a later message.
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
- Normal bootstrap renders at most the three newest real USER moves with their JIN/reasoning when present, followed by a divider dated to the last message in that source session (JIN completion, otherwise USER; omit it when timestamps are unavailable). Preserve USER-only interrupted/action-only moves without manufacturing an empty JIN bubble, and do not duplicate this tail during explicit archived restore.
- The first bootstrap color transition is the one 2-second transition; ordinary/live color changes use the shared 333 ms avatar-and-scene transition. Do not restore an old tint queue or add a second transition writer.
- Session-action interruption telemetry is causal UI state: validator/reasoning loops and context/output-limit recovery entries must be recorded/emitted when detected, before automatic follow-up/recovery starts.
- L-T rows use a short default preview (currently 50 characters), but a fact that is bubbled by reference/citation/context-loaded state must show its full value rather than a truncated citation.
- L-T facts absorbed by Delayed reports are hidden in the default active view unless context-loaded; the L-T counter toggles `show all` / `show active`. Keep normal fact sorting in both modes, and keep report-linked fact IDs opening the existing Delayed report modal.
- Memory inspector editing is value-only: double-click opens the existing hover card as an editor; FRAME edits only the latest frame value, Active edits conditions/value while preserving metadata/custom fields, and L-T edits only the fact value. Keys/IDs are not editable. Drafts remain page-local until the checkmark succeeds; rollback restores the last acknowledged value.
- Active and L-T explicit edits must surface the server `updated_at` immediately. Active pause/resume writes must synchronize the canonical Active store before later edits so a UI status change cannot be overwritten by stale backend state.
- FRAME values follow the detected language of the current user message while FRAME keys remain structural English `snake_case`; do not turn localized values into localized keys.
- Composer attachment chips are projections of already-pinned persistent files: click opens the existing preview, hold detaches from the message/context, and detach must not delete the persistent file or auto-expand Console.
- Completed assistant output uses the explicit `Copy all` control under the avatar/message shell. Do not restore invisible bubble double-click/long-hold copy-or-retry gesture zones; answer rating remains release-gated off.
- Live Avatar L-T facts fan out in batches of 100 over additional outer lanes. Keep Active Memory between the outermost L-T lane and the file ring, and reuse the existing memory-row hover zoom/reference highlighting rather than adding a competing ring effect.
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
- blank-tab vs completed vs interrupted USER-only vs action-only latest-session selection, separately for normal and anonymous log roots;
- dialogue-tail freshness independent of runtime `saved_at`, plus v1-to-v2 exact-owner migration, orphan rejection, write-failure preservation, and cleared-tombstone multi-tab protection;
- structured session-action metadata round trip (including JIN_COLOR swatch/hex hover);
- JIN_COLOR server-context -> raw runtime log -> common checkpoint -> local early apply -> one server reconciliation round trip, including stale-source replacement and repeated reload;
- full-text recent-message context tests beyond the former character cap, including physical-newline escaping and the three-pair limit;
- ordinary-turn previous-reasoning inclusion and middle-crop tests, plus absence of duplicate ordinary reasoning in action/recovery follow-ups;
- chunk-boundary tests for stream/action parsing;
- legacy-record + modern-record tests for compatibility/timestamps;
- real DOM/render-path check for UI behavior;
- search capability tests with configured/blank/placeholder provider credentials when touching search contracts or prompt exposure;
- patch apply check against the exact source snapshot when delivering `.patch`.

Do not claim the repository is green unless the relevant tests actually pass. See `docs/JIN_CURRENT_STATE.md` for the full-suite status of the exact inspected snapshot.

## Handoff format

When you finish a coding task, report:

1. root cause;
2. files changed;
3. exact behavior changed;
4. checks/tests run and their result;
5. remaining assumptions/risks;
6. any conflict between current code and documented product intent.

Keep this file short. Put architecture detail in `docs/JIN_ARCHITECTURE.md`, durable decisions in `docs/JIN_DECISIONS.md`, and migrations/known conflicts in `docs/JIN_CURRENT_STATE.md`.
