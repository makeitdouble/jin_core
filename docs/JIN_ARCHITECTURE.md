# JIN Core Engine — Current Architecture

**Verified snapshot:** `jin_core(20260826-090339).zip`<br>
**Inspection date:** 2026-08-26<br>
**Intent sources used for reconciliation:** current source/tests plus the accumulated 2026-08-23--26 project decisions<br>
**Purpose:** describe the architecture that is actually visible in the current source tree, while explicitly separating legacy compatibility from active design.

This document supersedes the architectural parts of the old root `ARCHITECTURE.md` and `README.md` wherever they still describe L2/L3 as live architectural layers or `SAVE_SESSION` as a current model action.

---

## 1. Product boundary

JIN Core Engine is an experimental local cognitive runtime for interchangeable OpenAI-compatible models. The runtime, not a particular model, is the product.

Core product properties:

- visible/inspectable context and memory;
- visible reasoning when the provider exposes it;
- explicit runtime actions with private model markers;
- session continuity across reloads/tabs/archived sessions;
- persistent files and memory objects with stable IDs;
- runtime state projected into the UI and Live Avatar;
- separate BRAIN and SERVICE roles even when both roles resolve to the same physical model.

The codebase is intentionally not structured as a generic autonomous-agent framework. The main foreground path remains direct.

---

## 2. Top-level runtime flow

```text
Browser UI
   <-> FastAPI / WebSocket (/ws/chat)
       -> RuntimeContext
       -> asyncio.Queue
       -> process_message()
       -> AgentRuntime
       -> BrainNode
       -> RuntimeStream
          -> visible reasoning/content
          -> private runtime actions
             -> contracts/*.json
             -> guard / normalization
             -> utils/actions/dispatcher.py
             -> state mutation / tool result
             -> optional Brain follow-up in the same request sequence

Background / secondary paths:
   completed foreground turn
       -> L1 SERVICE summarization
       -> L1 diff + Facts Memory companion state
       -> metabolism integration

   browser idle tick
       -> L4 extraction/merge pipeline
```

Main ownership by package:

| Area | Current responsibility |
| --- | --- |
| `app.py` | FastAPI app, HTTP APIs, static files, session-restore endpoint, WebSocket router registration |
| `websocket/` | connection lifecycle, queueing, bootstrap/resume, foreground turn orchestration, server->browser events |
| `runtime/runtime_context.py` | live in-process state hub for one logical runtime |
| `agent/` | direct Brain execution and per-turn state |
| `runtime/stream.py` | model stream handling, reasoning/content/action separation, recovery/limits |
| `contracts/` | canonical model-facing runtime-action contracts and action rule assembly |
| `utils/actions/` | payload normalization, action execution, storage/state mutation |
| `rules/brain_context_builder.py` | deterministic Brain prompt assembly from current state |
| `runtime/L1_memory*` | live runtime-memory summarization, snapshots, diffs, interrupted-turn memory path |
| `runtime/L4_memory*` | Facts Memory ingestion, durable L4 extraction/merge, reconciliation, delete/restore |
| `runtime/metabolism.py` | active homeostat/salience system and SERVICE integration |
| `utils/*_store.py` | durable file/report/fact stores |
| `ui/static/js/runtime/` | browser-side runtime state, persistence, session checkpointing, memory UI, avatar |
| `ui/static/js/logger/` | inspectable logger/action/memory projections |

---

## 3. Connection, queue, and turn ordering

### 3.1 RuntimeContext

`runtime/runtime_context.py::RuntimeContext` is the central live state object. It holds, among other things:

- clients and active streams;
- current/previous reasoning and visible answer state;
- runtime action history, action guard confirmations, tool results and follow-up state;
- live L1/runtime memory and snapshots;
- Active Memory records;
- Delayed Memory reports and loaded IDs;
- Facts Memory records and L4 store;
- attached file IDs and sequence attachments;
- session/reconnect/archived-restore metadata;
- L4/background tasks;
- metabolism state;
- avatar color/size/position/speed related state;
- message/turn/sequence counters.

Do not create a parallel state container for a concept already owned here unless the lifetime is intentionally browser-only or filesystem-persistent.

### 3.2 Pending request queue

The websocket endpoint uses a normal `asyncio.Queue` to serialize queued requests in FIFO order. Foreground work still has explicit guards around background L4 processing.

### 3.3 Foreground turn

`websocket/messages.py::process_message()` currently performs the foreground lifecycle:

1. classify ordinary turn vs action-guard retry vs archived-session resume tick;
2. resolve current attachments;
3. establish turn ID and sequence ID;
4. reset per-turn transient state;
5. on ordinary turns: apply browser idle/Active/pattern/avatar state, prepare metabolism, and auto-load Delayed Memory by user-typed tags;
6. append the user turn to the local chat log;
7. build `AgentState` and execute `AgentRuntime`;
8. persist reasoning log and emit action/session telemetry;
9. append visible JIN output to chat log/recent-turn state;
10. settle immediate metabolism effects;
11. schedule normal or interrupted L1 memory integration.

A later foreground turn can wait for a pending L1 update through `wait_for_runtime_memory_update()` so the Brain does not race stale live memory.

---

## 4. Agent and model boundary

`agent/runtime.py::AgentRuntime` is intentionally thin. It logs the flow and invokes `BrainNode` directly.

```text
user request -> AgentRuntime -> BrainNode
```

There is no active planner/router node in front of Brain.

Physical model endpoints are resolved through the client/config layer. Logical roles remain:

- **BRAIN** — foreground reasoning, visible answer, runtime decisions;
- **SERVICE** — L1 integration, metabolism/L4/supporting model work.

`USE_SERVICE_AS_BRAIN=True` may map both logical roles to one endpoint without removing the role distinction.

---

## 5. Brain context assembly

`rules/brain_context_builder.py::build_brain_context()` is the authoritative prompt assembly path.

The current high-level order is:

1. optional `<CURRENT_RUNTIME_SETTINGS>` — absolute first block when non-empty;
2. on archived restore only: session-restore continuation instruction;
3. current concerns;
4. trusted runtime XML / enabled actions;
5. recent tool results;
6. session action history;
7. ordinary turn: attached-files inventory, then Delayed Memory inventory; restore turn: staged resource metadata instead;
8. skills inventory;
9. loaded skill content;
10. runtime-context group:
   - explicit user feedback;
   - silent metabolism state;
   - Active Memory view;
   - L1/runtime memory snapshot;
   - visible session counters;
   - runtime TODO state;
   - loaded Delayed Memory bodies;
   - L4 long-term memory;
   - zero-diff stall alert;
11. archived exact-dialogue priming block, otherwise rolling recent visible messages;
12. archived reasoning dump, otherwise previous-reasoning loop/crop;
13. runtime-action instructions assembled from current contracts;
14. identity block;
15. turn/loop rules.

On ordinary turns, `<PREVIOUS_CHAT_MESSAGES>` takes the newest three recent USER/JIN pairs. The bound is pair count only: selected message bodies are no longer character-cropped. CRLF/CR is normalized, physical newlines are serialized as literal `\\n`, surrounding whitespace is stripped, and XML-sensitive characters are escaped without removing the remaining text.

The ordinary initial Brain prompt also includes the previous successfully completed reasoning in `<PREVIOUS_REASONING_CONTENT>`. Up to 2000 characters are kept whole; above that threshold the projection keeps the first and last 25% and replaces the middle with `CUTTED N chars`. Interrupted/recovery reasoning is tracked separately. Action and recovery follow-ups explicitly assemble their own current-turn/loop reasoning context instead of duplicating the ordinary previous-reasoning block. The visible TODO context snapshot mirrors the same ordinary-vs-follow-up choice.

Prompt text is a transient projection. Canonical state remains in `RuntimeContext`, browser persistence, and filesystem stores.

---

## 6. Streaming and runtime actions

### 6.1 RuntimeStream

`runtime/stream.py::RuntimeStream` owns the Brain stream lifecycle and separates:

- reasoning;
- visible answer content;
- private runtime-action markers.

Recovery paths also live around the stream/Brain sequence: repetition protection, context/output-limit continuation, stop/cancel, and action follow-ups.

### 6.2 Contract-driven action boundary

Concrete action schemas live in `contracts/*.json`. `contracts/rules_assembler.py` loads them and maps runtime actions to feature flags.

Current action names in the contract table:

- `DEEP_WEB_SEARCH`
- `WEB_SEARCH`
- `CLEAN_TOOL_RESULTS`
- `JIN_COLOR`
- `JIN_SIZE`
- `JIN_POSITION`
- `JIN_SPEED`
- `UPDATE_L4_FACTS`
- `LOAD_SKILL`
- `UNLOAD_SKILL`
- `ASSET_ACTION`
- `LIST_FILES`
- `ATTACH_FILE`
- `DETACH_FILE`
- `CREATE_TODO_LIST`
- `RESOLVE_TODO`
- `CHECK_TODO`
- `SAVE_DELAYED_MEMORY`
- `LOAD_DELAYED_MEMORY`
- `UNLOAD_DELAYED_MEMORY`
- `SAVE_ACTIVE_MEMORY`
- `RESOLVE_ACTIVE_MEMORY`
- `UPDATE_ACTIVE_MEMORY`

The default `rules/brain_context_builder.py` feature map currently disables runtime TODO (`CAN_RUNTIME_TODO=False`) while the other listed capabilities are enabled there. Search is an additional effective-capability gate: `WEB_SEARCH` and `DEEP_WEB_SEARCH` are removed from the model-facing action set unless `app_settings.settings.CAN_SEARCH` is true. `CAN_SEARCH` currently means provider `serper` plus a non-empty, non-placeholder configured key; the runtime deliberately does not guess a provider-specific key shape and leaves credential validation to Serper. The search client enforces the same gate before making a request.

There is **no current `SAVE_SESSION` contract** in this snapshot.

### 6.3 Parsing compatibility

`utils/actions/regexp_utils.py` accepts more than the advertised canonical syntax so old/provider-specific marker forms can still be recognized. This compatibility is parser-level and must not be confused with the preferred model contract.

For close-tag actions, the canonical form remains a paired block. For short actions, legacy inline/colon forms may be recognized when the parser explicitly supports them.

Important current compatibility boundaries:

- `CLEAN_TOOL_RESULTS` is intentionally a no-payload bare marker. A redundant `</CLEAN_TOOL_RESULTS>` is consumed as parser-only noise, including when it arrives in a later stream chunk; the paired-looking form still means one action.
- `JIN_COLOR` and `JIN_SIZE` advertise paired XML with their payload in the tag body. Legacy inline/colon/space forms remain parser compatibility only. The stream filter must remove only the marker and preserve ordinary answer text before and after it, even across chunk boundaries.
- `JIN_SIZE` normalization preserves positive decimal `px`, `vw`, `vh`, and `%` values instead of stripping their units. Unitless values become `px`. The browser resolves relative values at application time against its live viewport: `%` uses the matching width/height axis, while `vw` and `vh` always use viewport width and height respectively. The ordinary room-state checkpoint still stores the clamped rendered pixel geometry, so reload does not reinterpret an old relative command against a different window.
- `UPDATE_ACTIVE_MEMORY` is advertised as paired flat JSON, while localized compatibility code can also read a self-closing attribute form. That attribute form is compatibility, not the canonical model contract.
- `SAVE_ACTIVE_MEMORY` does not infer custom fields from parenthesized plain prose. Only explicit JSON root fields are structural custom fields; non-JSON text remains the `conditions` value.

### 6.4 Guard and dispatcher

`runtime/action_guard.py` can pause selected state-changing actions for explicit confirmation when behavior-contract trigger requirements are not satisfied.

`utils/actions/dispatcher.py::apply_runtime_action_calls()` is the central action execution fan-out. It manages action IDs, guard decisions, action-specific handlers, emitted events, trusted tool results, and follow-up semantics.

Action-specific rules should stay in contracts. `rules/runtime.py` should remain limited to cross-action sequence behavior and recovery rules.

### 6.5 JIN visual action state

`utils/actions/jin_visual_sequence_actions.py` emits each contiguous color/size/position/speed run in original marker order with a shared sequence ID. The browser buffers the run and plays it as one ordered visual sequence instead of regrouping actions by type.

JIN_COLOR has additional persistence semantics:

- accepted color updates set `RuntimeContext.jin_color` before the completed session snapshot is built;
- only a true no-op against the last applied color in the same runtime-message scope is skipped, so ordered alternation remains valid and a later message may request the same color again;
- each applied color is appended to the raw JSONL log as a `runtime_action_request` with a stable event ID, turn ID, timestamp, normalized color, and structured `session_action.parts[].colors` payload;
- a log-write failure is reported but does not block the already-valid UI event.

The raw event is the durable archive recovery path. It is not a second live state owner.

### 6.6 Session-action telemetry is causal

Session-action history is not only an end-of-turn summary. `runtime/stream.py` records and emits interruption/recovery entries at the moment the cause is detected so the logger changes before any automatic follow-up begins. This applies to reasoning/content validator loops and model context/output-limit recovery; `context_overflow` is treated as a context-limit finish reason.

That ordering is part of observability semantics. Moving the emission back to final compaction makes the logger describe the past only after JIN has already continued.

---

## 7. Memory architecture — current model

The old four-layer L1/L2/L3/L4 architecture is not the current implementation.

### 7.1 L1 / live runtime memory

Active backend modules:

- `runtime/L1_memory.py`
- `runtime/L1_memory_rules.py`
- `runtime/L1_memory_utils.py`

L1 is the compact live runtime state used for the next turns. It is updated by SERVICE after foreground turns, has snapshots/diffs, and has a distinct interrupted-turn update path.

It is not a durable long-term memory tier.

### 7.2 L2 and L3

There are no `runtime/L2_memory.py`, `runtime/L3_memory.py`, `runtime/L2_memory_utils.py`, or `runtime/L3_memory_utils.py` modules in the verified snapshot.

Remaining L2/L3 names occur in stale tests, old docs, comments, UI compatibility text, and historical session fields. Those names are not evidence that the layers still exist architecturally.

### 7.3 Facts Memory

Facts Memory is a companion candidate index derived from persisted live runtime snapshots on the browser side. `ui/static/js/runtime/runtime-storage.js` stores per-session facts-memory buckets and synchronizes them to the backend through `facts_memory_store_sync`.

Backend L4 code normalizes these records and marks analyzed fields. This is an intake/candidate mechanism for L4, not an independent durable product layer equivalent to old L2/L3.

### 7.4 L4 long-term memory

Active modules:

- `runtime/L4_memory.py`
- `runtime/L4_memory_rules.py`
- `runtime/L4_memory_utils.py`
- `utils/long_term_facts_file_store.py`

L4 owns durable facts. The current L4 path includes:

- Facts Memory candidate ingestion;
- extraction phase;
- merge/rebase/validation phase;
- explicit-edit protection;
- links to Delayed Memory reports;
- archive/anchor classification;
- delete/restore reconciliation;
- server/browser store synchronization.

L4 work is scheduled from an explicit browser idle tick (`l4_memory_idle_tick`) and is guarded so it does not begin while foreground work is running or queued.

### 7.5 Delayed Memory

Delayed Memory stores larger structured reports in `memory/delayed/*.json`, with file-store logic in `utils/delayed_memory_file_store.py`.

Current save contract:

```text
<SAVE_DELAYED_MEMORY>
{
  "title": "",
  "summary": "",
  "tags": [],
  "body": "",
  "anchor_fact_ids": [],
  "facts_ids": [],
  "attachments_ids": []
}
</SAVE_DELAYED_MEMORY>
```

Important semantics:

- report inventory and loaded report body are different prompt concepts;
- reports can link L4 facts and persistent files;
- `anchor_fact_ids` must be a subset of `facts_ids` under the current contract;
- loaded/pinned/referenced/inspected are different states;
- old key/value `SAVE_DELAYED_MEMORY_CONTENT` form is legacy only.

### 7.6 Active Memory

Active Memory is live unresolved structured state/commitments, stored independently from L1 text.

Current model-facing boundary:

```json
{"conditions":"...","custom_field":"..."}
```

`UPDATE_ACTIVE_MEMORY` also prefers flat JSON at the root after `active_memory_id`.

Creation custom fields are explicit structure only: JSON root fields beside `conditions` are accepted (up to the current three-custom-field cap), while non-JSON text is preserved as conditions and is not mined for `(field: value)` suffixes. Duplicate normalized JSON keys follow normal last-value-wins behavior before the cap is applied.

Compatibility code still accepts legacy nested `fields`/`updates`, older line-based update payloads, and a self-closing UPDATE attribute form. Those are localized reader compatibility. Internally/browser-side, Active Memory is still represented in a transitional string-record format with metadata suffixes; that is an implementation detail, not the desired model-facing schema.

Paused Active records are removed from the Brain prompt. Metabolism may reorder the prompt projection by salience without changing canonical storage order.

### 7.7 Persistent Files

Persistent uploads are owned by `utils/attached_files_store.py` and `assets/files/` plus its index. Stable IDs are reused by:

- prompt attachments;
- Delayed report links;
- file actions;
- UI memory/file projections;
- Live Avatar/link highlighting.

---

## 8. Metabolism

`runtime/metabolism.py` is a real active runtime subsystem in this snapshot, not merely a future night-cycle idea.

It currently implements:

- continuous homeostat levels;
- immediate foreground impulse before Brain generation;
- outcome settling after a turn;
- active-memory salience;
- delayed-memory scoring;
- L4 context-focus/significance scoring;
- lexical/association signals;
- temperature modulation;
- debounced SERVICE integration after committed L1 updates;
- browser state emission/persistence support.

This does **not** prove that the older concept of a full nightly self-review/consolidation cycle is complete. That remains a separate product direction and must not be inferred from the existence of `metabolism.py`.

---

## 9. Persistence and session continuity

JIN deliberately splits persistence by owner/lifetime.

| State | Current storage/owner |
| --- | --- |
| live runtime checkpoint / browser-facing session state | browser storage via runtime/session modules |
| Active Memory | browser runtime storage; anonymous mode can isolate it |
| Facts Memory candidate buckets | browser storage per facts-memory session ID |
| Delayed Memory | `memory/delayed/*.json` |
| L4 facts | `memory/facts/long_term_facts.json` |
| persistent files | `assets/files/` + file index |
| visible chat / reasoning logs | `logs/` |
| live in-process orchestration | `RuntimeContext` |

### 9.1 Soft runtime resume

`runtime_resume` reconnects browser runtime state to a live/new backend context without being an archived-session checkout.

### 9.2 Session bootstrap / live checkpoint

`ui/static/js/runtime/runtime-session.js` persists live checkpoints and sends `session_bootstrap` data when appropriate. The backend normalizes and hydrates the browser-provided snapshot in `websocket/bootstrap.py`.

The browser uses one common checkpoint to name the last runtime session that actually moved. Merely opening/reloading a tab can clone inherited L1 into a fresh per-session record and record `booted_from_session_id`, but it does not promote that fresh runtime ID to the common conversation checkpoint. A real user send marks session activity immediately; a later server `completed_turn_commit` is the fallback commit signal. `conversation_committed_at` advances only for a completed turn, so it remains distinct from USER-only session movement.

Per-session runtime records are candidates for the checkpoint's L1 payload only when their `session_id` matches the common checkpoint. Nested runtime snapshots preserve their own origin session ID; lineage is not rewritten merely because the containing browser record belongs to the new tab.

The server sends a normalized `session_snapshot` at visible `message_end` and again at `agent_runtime_end`. The client merges the current room state into that snapshot and persists it before finishing the visible bubble. Completed state and room/avatar state therefore land as one checkpoint rather than racing through separate full writers.

For a predecessor/browser checkpoint, `websocket/bootstrap.py::enrich_session_bootstrap_from_archive()` may enrich dialogue, reasoning, action history, files, counters, and selected runtime state from raw logs. Normal and anonymous modes use separate log roots.

The latest raw-log selector chooses the session containing the newest real USER move. A blank bootstrap-only session with no USER row cannot win. A stopped USER-only move and a completed action-only move with an empty visible JIN row can win and remain distinguishable by whether a durable JIN row/timestamp exists. The legacy function name `find_latest_completed_session_restore_payload()` is therefore narrower than its current semantics.

Bootstrap uses two freshness clocks:

- dialogue/reasoning/counters compare the browser recent-turn tail to the archive recent-turn tail;
- runtime/resource fields still use checkpoint `saved_at` against archive tail time.

This separation prevents a harmless fresh-tab clone or room-state write from pinning dialogue to an older turn. `saved_at` must still represent a whole-checkpoint refresh, not an incidental field mutation.

Session actions are merged by stable ID when available, otherwise by structured identity, sorted by real `created_at`, and bounded. For an unchanged source session the common checkpoint owns actions at or before `saved_at`; raw logs may append only a newer tail. If raw dialogue proves that another source session has a strictly newer USER move, the stale browser source, its actions, and its color are discarded together.

`CLEAN_TOOL_RESULTS` has an explicit field-local persistence rule. On successful cleanup, the browser rewrites only `session_snapshot.tool_results` to `[]` inside the existing checkpoint and preserves checkpoint timestamp/lineage verbatim. During enrichment, the mere presence of `tool_results` (including `[]`) is authoritative, so old archived search/tool output cannot resurrect in a new tab. This exact-empty rule is intentionally **not** shared by `loaded_memory_ids` or `active_memory_records`; their empty browser collections still use the established archive fallback behavior.

Late append-only L4 tool results are the one post-checkpoint tool-result enrichment: a newer raw `runtime_tool_result` of kind `l4` may be merged after the greater of checkpoint time and `tool_results_cleared_at`. Other old tool results remain blocked by the browser checkpoint/tombstone.

Session-action parts are structured continuity data. Bootstrap normalization currently preserves `text/detail/message/id` plus recognized `colors`; color metadata is normalized to lowercase `#rrggbb` (including expansion from `#rgb`) so restored JIN_COLOR actions keep the same swatch and hex hover metadata as live actions.

Current JIN color is part of the same checkpoint. For the same source session, explicit browser `current_jin_color` wins over action history and archived trusted state. If that field is absent, the newest structured JIN_COLOR session action is the first fallback, followed by the raw archive/trusted color. Applied colors are also recorded as raw runtime events so a direct-predecessor chain can recover both final color and ordered history.

Room-state persistence is field-local. It normally refuses to write across a session-ID mismatch and never changes checkpoint `session_id`, lineage, or `saved_at`. JIN_COLOR uses one synchronous reconciliation exception: after the UI applies a live color it may merge that color into the existing common checkpoint even before the new runtime session is promoted, while preserving checkpoint ownership and freshness metadata.

Old L3-era fields can still appear in tests/compatibility paths, but there is no active L3 memory module.

### 9.3 Normal bootstrap chat tail

After backend hydration, normal bootstrap emits at most the three newest `runtime_recent_turns` to the browser. Each item may carry USER text, JIN text, saved reasoning, and original timestamps. Attachment-context boilerplate is removed from the visible USER bubble.

The client rebuilds the tail through the existing chat primitives. It keeps a real USER-only interrupted/action-only turn but does not manufacture an empty BR bubble. It then appends a date-labelled current-session divider and activates the live-turn viewport at that boundary, leaving the inherited three-turn history immediately above the initial screen. Explicit archived restore owns its own rendering path and suppresses this normal-bootstrap tail.

### 9.4 Archived session restore

Archived restore is a distinct path:

1. HTTP endpoint `/api/sessions/{session_id}/restore` builds payload from logs via `utils/session_restore.py`.
2. Browser renders the same bounded three-USER-move tail carried by the restore payload and sends a `session_bootstrap`/restore payload. Saved reasoning is attached to its owning JIN turn after archive-file metadata is removed; later visible JIN-only restore rows remain in order.
3. Backend sets `runtime_session_restore_priming` and stages historical resource IDs/metadata.
4. A hidden `archived_session_resume` Brain tick receives restore-specific context.
5. The restore prompt includes the newest complete visible dialog pairs plus a bounded recent reasoning dump.
6. Historical loaded Delayed IDs, attached files, and avatar state are not blindly applied before the restore greeting.
7. `BrainNode` consumes the staged restore envelope and replays those resources through the normal runtime-action dispatcher.
8. The WebSocket tail performs defensive cleanup only; it must not apply the same resources a second time.

The restore instruction is stamped at prompt-build time with the current timezone-aware bootstrap time immediately before `Current session was bootstrapped in a browser tab!`. Archived USER timestamps remain historical dialogue metadata and are never reused as the bootstrap time.

Constants in the current source limit the restore reasoning dump to two recent reasoning items with a per-item character cap. Restored visible dialogue uses the normal three-pair limit and, like ordinary recent-message context, does not impose a per-message character cap.

The RESTORE endpoint owns archived dialogue, reasoning, and L1 for explicit URL checkout. A same-session browser checkpoint may contribute a newer room/avatar and Session Actions projection, but it cannot overwrite only `recent_turns`, reasoning, or runtime memory and thereby create a mixed conversation source. The restore instruction names `RESTORED_SESSION_DIALOG` as the newest conversational authority; L1 remains background state and may legitimately predate the final archived turn.

`utils/session_restore.py` still understands historical `SAVE_SESSION` labels in archived logs. That is restore compatibility, not proof of a current `SAVE_SESSION` runtime action.

### 9.5 Timestamp invariant

Modern records/snapshots should retain original creation timestamps across serialize -> reload -> hydrate. `now()` is only a fallback for truly legacy records without a timestamp. Rendering/loading must not rewrite historical time.

---

## 10. Anonymous / shadow mode

`runtime/anonymous_mode.py` and browser storage logic implement anonymous/shadow behavior.

Backend behavior:

- runtime is marked anonymous and persistent writes restricted;
- global Delayed Memory can still be hydrated/read;
- Delayed file-store mutation is disabled;
- `UPDATE_L4_FACTS` and `SAVE_DELAYED_MEMORY` are explicitly restricted;
- persistent asset-write actions are restricted;
- read-only/runtime-local actions remain available where safe.

Browser behavior can isolate session-facing stores in private/incognito mode. Do not broaden or narrow persistence semantics by assumption; trace both JS storage selection and backend write guards.

---

## 11. Stop, interruption, and recovery

`websocket/tasks.py::cancel_current_task()`:

- marks the active turn interrupted;
- can distinguish discard vs interrupted-memory update;
- aborts active runtime actions;
- closes active model streams;
- cancels the task;
- can schedule the interrupted L1 update.

`process_message()` later routes interrupted turns through `schedule_interrupted_runtime_memory_update()` instead of pretending the turn completed normally.

The Brain/stream layer also contains recovery for reasoning repetition and model/context output limits. Follow-up ticks preserve sequence identity rather than starting a new user request. They explicitly suppress the ordinary previous-reasoning projection and carry the relevant current-turn or loop-recovery reasoning through their dedicated builder. The corresponding session-action interruption entry is emitted before that recovery/follow-up starts, not deferred until the final answer.

---

## 12. UI synchronization and Live Avatar

The browser is a projection of runtime state, not an independent semantic authority.

Important shared identities include:

- Active Memory IDs;
- Delayed report IDs;
- L4 fact IDs;
- file IDs;
- runtime action IDs;
- turn/sequence IDs.

The Live Avatar and memory panels consume the same identities but may show different **strength** depending on cause:

- object actually loaded into context -> active/strong state;
- object merely referenced/cited by ID -> weak linked state;
- object only inspected in a modal -> no implied context load.

Do not collapse these into a generic highlight state.

The L4 panel deliberately separates compact browsing from surfaced evidence: ordinary fact rows use a 50-character value preview, while a row bubbled by runtime reference, explicit reasoning citation, or context-loaded state renders its full value. The storage value is never truncated; this is projection-only behavior.

Session-action logger rows are also a projection of structured history. The compact logger keeps the most recent five items in chronological order with their original numbering and reuses the existing attached-files header/button primitive for `FULL`. JIN_COLOR parts render one swatch per applied color and expose the normalized hex on hover; bootstrap must preserve the `colors` payload for this to work after reload. Runtime-action bubble details are retained across counter-only updates so a count refresh cannot erase existing hover metadata.

JIN visual-action chat bubbles are currently release-gated off, but parsing, execution, avatar updates, raw event persistence, and Session Actions logging remain active. A UI visibility flag must not be mistaken for a disabled runtime action.

Color has one visual transition owner in the avatar API. The initial bootstrap application consumes the one 2000 ms transition; later/live JIN_COLOR applications use 333 ms. The API writes the same temporary duration to avatar-center and scene-tint CSS variables before applying the color, so both projections move together. The old color queue and separate bootstrap tint-shift helper are absent.

Normal session bootstrap applies the color from the common local checkpoint during early room restoration, then accepts one server `session_actions_update` reconciliation with `bootstrap_restore=true`. There is no client-side color resolver scanning competing sources.

### Header auto-hide

`ui/static/js/header-autohide.js` currently uses:

- reveal-zone height = 2 x measured header height;
- show debounce = **333 ms** in this snapshot;
- hide delay = **1000 ms**;
- panel occlusion logic so moving over panels/avatar does not trigger the reveal path incorrectly.

The product intent recorded on 2026-08-21 was approximately 250 ms reveal debounce. The code/intention mismatch is tracked in `JIN_CURRENT_STATE.md`; do not silently change it while working on an unrelated task.

### Visual rule

New UI states must reuse the closest existing JIN primitive. The UI deliberately avoids generic SaaS success/error visual language, arbitrary new glow colors, and decorative blur.

---

## 13. Extension rules

### New runtime action

Start at `contracts/*.json`, then connect normalization/handler logic in `utils/actions/`, guard semantics if necessary, event/tool-result/follow-up behavior, and tests.

### New durable state

Define exactly one canonical owner, stable identity, persistence location, bootstrap/hydration path, mutation path, reconciliation rules, and browser projection.

### New model context source

Keep canonical state outside the prompt builder. Serialize it in `utils/context/` or `rules/brain_context_builder.py` at a deliberate position.

### New UI behavior

Use existing semantic IDs/events and existing CSS/DOM primitives first. New visual language requires explicit justification.

---

## 14. Known architectural traps

Do not infer architecture from these alone:

- old root `README.md` / `ARCHITECTURE.md`;
- `tests/test_l2_memory.py` and `tests/test_l3_session_memory.py`;
- `SAVE_SESSION` references in old tests/log parsing;
- comments mentioning “L1/L2/L3 glow”;
- stale CodeGraph/search indexes;
- historical field names like `runtime_l3_session_memory`;
- the name `find_latest_completed_session_restore_payload()`; current selection is newest real USER move, including USER-only interruption;
- treating any write to a browser checkpoint as permission to advance `saved_at`;
- using runtime `saved_at` to decide whether copied dialogue is current;
- treating a newly opened runtime ID as the newest conversation before a real USER move;
- assuming an empty collection always means "missing" during archive enrichment;
- sanitizing session actions down to text while dropping structured UI metadata such as `parts[].colors`.
- adding a separate JIN color key/resolver/queue instead of reconciling the common checkpoint and raw action log.

The verified filesystem has no active L2/L3 modules and no current `SAVE_SESSION` contract.

For the exact transition/conflict list, see `docs/JIN_CURRENT_STATE.md`.
