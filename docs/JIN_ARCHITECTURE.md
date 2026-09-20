# JIN Core Engine — Current Architecture

**Verified snapshot:** `jin_core(20260917-184157).zip`<br>
**Inspection date:** 2026-09-17<br>
**Reconciliation basis:** current production source is the implementation source of truth; durable decisions are retained where they still match it, and legacy tests/comments are treated as compatibility evidence only.<br>

**Purpose:** describe the architecture that is actually visible in the current source tree, while explicitly separating legacy compatibility from active design.

This document is the current architectural baseline. `README.md` is kept as the shorter product-facing overview; legacy tests/comments remain lower-confidence historical evidence.

---

## 1. Product boundary

JIN Core Engine is an experimental cognitive runtime for interchangeable OpenAI-compatible models, designed to work especially well with local runtimes. The runtime, not a particular model, is the product.

Core product properties:

- visible/inspectable context and memory;
- visible reasoning when the provider exposes it;
- explicit runtime actions with private model markers;
- session continuity across reloads/tabs/archived sessions;
- persistent files and memory objects with stable IDs;
- runtime state projected into the UI and Live Avatar;
- one foreground BRAIN route plus a logical background SERVICE role that may resolve to the same physical model.

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
       -> logical SERVICE route
          -> dedicated Service client when configured
          -> otherwise the same physical client as Brain
       -> FRAME integration + diff + Facts Memory companion state

   browser idle tick
       -> L-T extraction/merge pipeline through the same SERVICE route
```

Main ownership by package:

| Area | Current responsibility |
| --- | --- |
| `app.py` | FastAPI app, HTTP APIs, static files, session-restore endpoint, WebSocket router registration |
| `websocket/` | connection lifecycle, queueing, bootstrap/resume, foreground turn orchestration, server->browser events |
| `runtime/runtime_context.py` | live in-process state hub for one logical runtime |
| `agent/` | direct foreground Brain execution and per-turn state |
| `runtime/stream.py` | model stream handling, reasoning/content/action separation, recovery/limits |
| `contracts/` | canonical model-facing runtime-action contracts and action rule assembly |
| `utils/actions/` | payload normalization, action execution, storage/state mutation |
| `rules/brain_context_builder.py` | deterministic Brain prompt assembly from current state |
| live-memory implementation in `runtime/` | FRAME integration, snapshots, diffs, interrupted-turn memory path |
| `runtime/LT_memory*` | Facts Memory ingestion, durable L-T extraction/merge, reconciliation, delete/restore |
| `runtime/memory_attention.py` | prompt-only Active/Delayed/L-T relevance ranking |
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
- live FRAME memory and snapshots;
- Active Memory records;
- Delayed Memory reports and loaded IDs;
- Facts Memory records and L-T store;
- attached file IDs and sequence attachments;
- session/reconnect/archived-restore metadata;
- L-T/background tasks;
- prompt-only L-T focus diagnostics;
- avatar color/size/position/speed related state;
- message/turn/sequence counters.

Do not create a parallel state container for a concept already owned here unless the lifetime is intentionally browser-only or filesystem-persistent.

### 3.2 Pending request queue

The websocket endpoint uses a normal `asyncio.Queue` to serialize queued requests in FIFO order. Foreground work still has explicit guards around background L-T processing.

The queue worker now belongs to the live `RuntimeContext` session through `runtime_transport`, rather than to a physical WebSocket. `websocket/transport.py` buffers serialized output until browser acknowledgement; reconnect attaches a new sender/receiver and replays unacknowledged events in order. Brain, FRAME waits, and pending USER batches keep running while the page is frozen/disconnected. A live transport reconnect does not apply a stale browser runtime/store snapshot. Process restart still uses the existing browser bootstrap fallback. This delivery buffer is in-process transport state, not a new browser checkpoint or durable memory system.

Page departure (`pagehide`, excluding back/forward cache) retires its transport
through a same-origin, exact-epoch close beacon, with WebSocket code 4001 as a
fallback. An unexplained disconnect retains the runtime for 600 seconds; a soft
reconnect cancels that deadline. Retirement cancels the session/guard/background
tasks, closes provider streams, releases both the resume-store and cached L-T
owner references, and discards the replay buffer. Accepted queued USER moves
use the existing interrupted-turn path; retirement cannot start another Brain
turn or finish a cancelled stream as a completed turn.

### 3.3 Foreground turn

`websocket/messages.py::process_message()` currently performs the foreground lifecycle:

1. classify ordinary turn vs action-guard retry vs archived-session resume tick;
2. resolve current attachments;
3. establish turn ID and sequence ID;
4. reset per-turn transient state;
5. on ordinary turns: apply browser idle/Active/pattern/avatar state and auto-load Delayed Memory by user-typed tags;
6. append the user turn to the local chat log;
7. build `AgentState` and execute `AgentRuntime`;
8. persist reasoning log and emit action/session telemetry;
9. append visible JIN output to chat log/recent-turn state;
10. schedule normal or interrupted FRAME memory integration.

A later foreground turn can wait for a pending FRAME update through `wait_for_runtime_memory_update()` so the Brain does not race stale live memory.

---

## 4. Agent and model boundary

`agent/runtime.py::AgentRuntime` is intentionally thin. It logs the flow and invokes `BrainNode` directly.

```text
user request -> AgentRuntime -> BrainNode
```

There is no active planner/router node in front of Brain.

Physical model endpoints are resolved through the client/config layer. Logical roles remain:

- **BRAIN** — the only foreground reasoning/visible-answer/runtime-decision route;
- **SERVICE** — background FRAME, L-T, research, document-skill, and supporting model work.

`utils/brain_client_utils.py::get_brain_runtime_config()` always returns label `brain`, and `BrainNode` resolves `context.clients["brain"]`. There is no active foreground branch to Service.

`clients/registry.py` always builds the Brain client first and initially aliases `clients["service"]` to that same object. Only an explicitly configured `SERVICE_API_BASE` replaces the alias with a dedicated Service client. Therefore a one-model setup is the default topology, but the logical Service role remains background-only.

`config_loader.py::normalize_model_role_config()` accepts `USE_SERVICE_AS_BRAIN=True` only as a migration adapter for old local configs: it promotes the old Service endpoint/settings into canonical Brain settings, clears the dedicated Service URL, deletes the legacy attribute, and then normalizes Service fallbacks. The Windows launcher contains matching legacy detection only so startup can find/migrate those old configs safely. No live runtime path reads the flag.

Historical archives can still contain `role=service` / `RUNTIME_MODE=SERVICE`, and the logger UI retains presentation code for old `[SERVICE]` model-output cards. Those are reader compatibility paths, not a current response mode.

The runtime status modal is also the current model-switch surface. For an available role it reads the LM Studio catalog/load metadata, posts the selected model and remembered load configuration to `/api/runtime-model/switch`, then reconciles against `/api/status` before presenting the switch as settled. This changes the physical model backing a role; it does not create a new foreground routing mode.

---

## 5. Brain context assembly

`rules/brain_context_builder.py::build_brain_context()` is the authoritative prompt assembly path.

The current high-level order differs slightly between an ordinary user turn and archived-restore priming.

Ordinary turn:

1. optional `<RUNTIME_SETTINGS>` — first live-settings block when non-empty;
2. optional `<CONCERNS>`; it is omitted when empty, and from 50% previous-answer context usage it includes the percentage and can ask Brain to clean redundant tool results;
3. trusted runtime XML / enabled actions;
4. optional project-review context;
5. `TOOLS_RESULTS` — this is also where loaded skill bodies are projected;
6. session action history;
7. attached-files inventory, then Delayed Memory inventory;
8. always-present `<SKILLS_LIST>` availability/loaded-state inventory;
9. runtime-context group: explicit feedback/retry, Active Memory, current `<FRAME_MEMORY_N ...>` snapshot, then `<PREVIOUS_CHAT_MESSAGES>`, visible session counters, loaded Delayed Memory bodies, L-T facts, and any zero-diff alert;
10. previous reasoning evidence/loop block when applicable;
11. runtime-action instructions assembled from current contracts;
12. identity block;
13. turn/loop rules.

Archived restore priming deliberately moves continuity to the absolute front: inherited `<PREVIOUS_CHAT_MESSAGES>` first, then `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>` when available, then `<MANDATORY_SYSTEM_NOTIFICATION>`. `<RUNTIME_SETTINGS>` follows that restore preamble, after which the normal concerns/runtime/tool/action scaffolding continues. Restore resource metadata replaces the ordinary attached-file/Delayed inventories, and the ordinary previous-reasoning slot is suppressed because reasoning evidence was already projected at the front.

On ordinary turns, `<PREVIOUS_CHAT_MESSAGES>` takes the newest five recent USER/JIN pairs. The bound is pair count only: selected message bodies are not character-cropped. CRLF/CR is normalized, physical newlines are serialized as literal `\n`, surrounding whitespace is stripped, and XML-sensitive characters are escaped without removing the remaining text.

The ordinary initial Brain prompt also includes the previous successfully completed reasoning in `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>`. Up to 2000 characters are kept whole; above that threshold the projection keeps the first and last 25% and replaces the middle with `CUTTED N chars`. Action/recovery follow-ups project visible dialogue first, then carried reasoning evidence, then `<FOLLOW_UP_RESPONSE_MESSAGE>` and the current failure/recovery/tool state, rather than duplicating the ordinary previous-reasoning slot.

Prompt text is a transient projection. Canonical state remains in `RuntimeContext`, browser persistence, and filesystem stores.

---

## 6. Streaming and runtime actions

### 6.1 RuntimeStream

`runtime/stream.py::RuntimeStream` owns the Brain stream lifecycle and separates:

- reasoning;
- visible answer content;
- private runtime-action markers.

Recovery paths also live around the stream/Brain sequence: repetition protection, context/output-limit continuation, stop/cancel, and action follow-ups.

Brain-client and outer RuntimeStream action dispatch share one message-local `StreamActionQueue`. Marker parsing and visible chunks continue while asynchronous action execution waits. Actions remain ordered; normal completion drains their results before message-end/checkpoint/follow-up. Stream cancellation closes the queue so pending actions cannot outlive the turn.

### 6.2 Contract-driven action boundary

Concrete action schemas live in `contracts/*.json`. `contracts/rules_assembler.py` loads them and maps runtime actions to feature flags. Each concrete contract exposes a `schema` string array separately from its `rules`; the assembler emits `Schema:` before action rules, and `get_runtime_action_schema()` is also the canonical source used to explain invalid payloads back to the model.

Current action names in runtime order are:

- `DEEP_WEB_SEARCH`
- `WEB_SEARCH`
- `CLEAN_TOOL_RESULTS`
- `JIN_COLOR`
- `JIN_REACTION`
- `JIN_SIZE`
- `JIN_POSITION`
- `JIN_SPEED`
- `UPDATE_LT_FACTS`
- `RECALL_FACT_CONTEXT` — internal source-backed L-T recall; the model marker is `<RECALL_FACTS_CONTEXT> F1, F2 </RECALL_FACTS_CONTEXT>`; see [RECALL_FACT_CONTEXT.md](RECALL_FACT_CONTEXT.md).
- `CHAT_LOG_SEARCH` — literal local archive search; see [CHAT_LOG_SEARCH.md](CHAT_LOG_SEARCH.md).
- `LOAD_SKILL` — internal runtime name; `<LOAD_SKILLS_CONTEXT> skill1, skill2 </LOAD_SKILLS_CONTEXT>` expands an ordered comma-separated list.
- `UNLOAD_SKILL` — internal runtime name; `<UNLOAD_SKILLS_CONTEXT> skill1, skill2 </UNLOAD_SKILLS_CONTEXT>` expands an ordered comma-separated list.
- `ASSET_ACTION`
- `POSTING_BOARD` — skill-gated native Get Posting Board I/O (`feed`, `inbox`, `read`, `search`, `post`, `reply`, `ack`, `delete`).
- `LIST_ALL_USER_SHARED_FILES`
- `ATTACH_FILE_CONTENT`
- `ATTACH_FILE_BY_ID` (model-facing paired list marker: `ATTACH_FILES_BY_ID`)
- `SAVE_DELAYED_MEMORY`
- `LOAD_DELAYED_MEMORY`
- `SAVE_ACTIVE_MEMORY`
- `DELETE_ACTIVE_MEMORY`
- `UPDATE_ACTIVE_MEMORY`

The default `rules/brain_context_builder.py` feature map enables the listed capabilities. Search is an additional effective-capability gate: `WEB_SEARCH` and `DEEP_WEB_SEARCH` are removed from the model-facing action set unless `app_settings.settings.CAN_SEARCH` is true. `CAN_SEARCH` currently means provider `serper` plus a non-empty, non-placeholder key supplied through `SEARCH_SERPER_API_KEY` or `JIN_SEARCH_SERPER_API_KEY`; the runtime deliberately does not guess a provider-specific key shape and leaves credential validation to Serper. The Windows launcher loads repository-root `.env` values into its child JIN process, while direct `python app.py` starts require the variables to be exported by the calling shell. The search client enforces the same gate before making a request. `POSTING_BOARD` is separately gated by the loaded `posting_board` skill: the skill owns the per-action API contract and safety rules, while the native runtime action owns HTTP execution, tool-result projection, follow-ups, logging, and UI events. Its API token follows the same process-environment path through `GETPOSTINGBOARD_API_KEY` or `JIN_GETPOSTINGBOARD_API_KEY` and is deliberately omitted from request previews/tool results.

There is **no current `SAVE_SESSION` contract** in this snapshot.

### 6.3 Parsing compatibility

`utils/actions/regexp_utils.py` accepts more than the advertised canonical syntax so old/provider-specific marker forms can still be recognized. This compatibility is parser-level and must not be confused with the preferred model contract.

A tag immediately preceded by an opening quote, backtick, or bracket is a literal marker reference. It must remain visible without starting/executing an action. The stream filter retains a trailing opener across chunk boundaries; both browser visual-marker renderers respect the same prefix rule. Whitespace between the opener and tag does not qualify.

For close-tag actions, the canonical form remains a paired block. For short actions, legacy inline/colon forms may be recognized when the parser explicitly supports them.

There is one deliberately narrow response-prefix fallback for provider/model formatting slips: before any visible non-whitespace answer text has been emitted, a standalone line may omit angle brackets and use exact `ACTION_NAME: payload` syntax. The action name must be an enabled canonical runtime action, the action must be a payload-bearing short action (or one of the JIN one-line compatibility actions), and its normal payload builder plus fallback-specific ID checks must accept the payload. The first ordinary or malformed nonblank line disables this fallback for the rest of the answer; normal `<...>` action parsing continues everywhere as usual. Unterminated candidate lines are held until newline/flush so trailing prose cannot be swallowed, and removing an accepted line consumes its empty line as well.

Important current compatibility boundaries:

- `CLEAN_TOOL_RESULTS` is a strict paired block. Targeted cleanup uses `<CLEAN_TOOL_RESULTS> T1, T2, T3 </CLEAN_TOOL_RESULTS>` with comma-separated exact tool-result IDs; the entire list is validated before mutation. An empty `<CLEAN_TOOL_RESULTS></CLEAN_TOOL_RESULTS>` block performs full cleanup, including legacy ID-less results. The former bare marker and `<CLEAN_TOOL_RESULTS: T1 >` form are not executable compatibility syntax.
- `JIN_COLOR` and `JIN_SIZE` advertise paired XML with their payload in the tag body. Legacy inline/colon/space forms remain parser compatibility only. The stream filter must remove only the marker and preserve ordinary answer text before and after it, even across chunk boundaries.
- `JIN_SIZE` normalization preserves positive decimal `px`, `vw`, `vh`, and `%` values instead of stripping their units. Unitless values become `px`. The browser resolves relative values at application time against its live viewport: `%` uses the matching width/height axis, while `vw` and `vh` always use viewport width and height respectively. The ordinary room-state checkpoint still stores the clamped rendered pixel geometry, so reload does not reinterpret an old relative command against a different window.
- `UPDATE_ACTIVE_MEMORY` is advertised as paired JSON containing `active_memory_id` plus `fields_to_update`. Localized compatibility code can still read legacy flat/nested/line-based payloads and a self-closing attribute form, but none of those are canonical model syntax.
- `SAVE_ACTIVE_MEMORY` keeps `conditions` and optional custom fields at the JSON root and does not infer custom fields from parenthesized plain prose. Only explicit JSON root fields are structural custom fields; non-JSON text remains the `conditions` value.
- `LOAD_SKILLS_CONTEXT` and `UNLOAD_SKILLS_CONTEXT` are public list markers for the singular internal actions. The immediately previous singular `*_SKILL_CONTEXT` paired tags remain localized reader compatibility; the model contract advertises only the plural list forms.
- `JIN_REACTION` advertises paired XML with a single emoji. Its older colon form remains parser/display compatibility only.

### 6.4 Guard and dispatcher

`runtime/action_guard.py` can pause selected state-changing actions for explicit confirmation when behavior-contract trigger requirements are not satisfied.

`utils/actions/dispatcher.py::apply_runtime_action_calls()` is the central action execution fan-out. It manages action IDs, guard decisions, action-specific handlers, emitted events, trusted tool results, and follow-up semantics.

Action-specific rules should stay in contracts. `rules/runtime.py` should remain limited to cross-action sequence behavior and recovery rules.

Tool results are deliberately human-readable rather than raw JSON. On failure, `utils/context/runtime_action_result_text.py` renders the failed status/reason, relevant supplied payload, and `Correct action schema:` from the same contract. `rules/runtime.py::ACTION_FAILURE_FOLLOWUP_MESSAGE` then tells Brain not to treat the failed action as completed and to continue from `TOOLS_RESULTS`. The error renderer, contract schema, and follow-up instruction therefore form one recovery path rather than three independent descriptions.

### 6.5 JIN visual action state

`utils/actions/jin_visual_sequence_actions.py` emits each contiguous color/size/position/speed run in original marker order with a shared sequence ID. The browser buffers the run and plays it as one ordered visual sequence instead of regrouping actions by type.

JIN_COLOR has additional persistence semantics:

- accepted color updates set `RuntimeContext.jin_color` before the completed session snapshot is built;
- only a true no-op against the last applied color in the same runtime-message scope is skipped, so ordered alternation remains valid and a later message may request the same color again;
- each applied color is appended to the raw JSONL log as a `runtime_action_request` with a stable event ID, turn ID, timestamp, normalized color, and structured `session_action.parts[].colors` payload;
- a log-write failure is reported but does not block the already-valid UI event.

The raw event is the durable archive recovery path. It is not a second live state owner.

### 6.6 Session-action telemetry is causal

Session-action history is not only an end-of-turn summary. `runtime/stream.py` records and emits interruption/recovery entries at the moment the cause is detected so the logger changes before any automatic follow-up begins. This applies to reasoning/content validator loops and model context/output-limit recovery; `context_overflow` is treated as a context-limit finish reason. Provider/preflight overflow errors enter the same recovery path. Native `chat.end`/`stop` also enters it when actual provider input plus output tokens fill the loaded window. Limit entries retain a separate history row through compaction.

That ordering is part of observability semantics. Moving the emission back to final compaction makes the logger describe the past only after JIN has already continued.

---


### 6.7 Malformed action recovery

The stream parser also recognizes three non-executable forms for enabled action
names: tool-call wrappers with an object payload, paired tags with attribute
payloads, and short payload-bearing actions incorrectly emitted as paired tags
with a `{ key="value" }` body. The existing quote-prefix rule still protects
literal examples. Known unfinished envelopes remain private at stream flush.

Each detection is dispatched as internal `MALFORMED_ACTION` telemetry, never as
the attempted mutation. It receives its own T-id, action bubble and preserved
Session Actions row. The existing runtime tool-result store persists the action
name and original extracted payload. Ordered `MALFORMED_ACTION_NOTIFICATION`
blocks lead the shared follow-up prompt and obtain the correct syntax exclusively
from the target contract's `schema` array. Valid results in the same response
remain in that same follow-up. These repairs do not consume the ordinary workflow
follow-up limit, including when malformed output occurs on its last tick; user
Stop and transport/provider interruption retain their normal behavior.

---

## 7. Memory architecture — current model

The old numbered four-layer architecture is not the current implementation.

### 7.1 FRAME / live runtime memory

FRAME is the compact live runtime state exposed in the memory panel and as `<FRAME_MEMORY_N>` in Brain context. It is integrated through the logical Service route after foreground turns, has snapshots/diffs, and has a distinct interrupted-turn update path. With no dedicated Service endpoint, that background route deliberately reuses the Brain client. The FRAME integration prompt detects the current user-message language for values while keeping structural keys as English `snake_case`; localization is a value-format rule, not a schema rename.

FRAME is not a durable long-term tier. Its implementation modules, state fields, events, pending journal, UI identifiers, and tests use FRAME naming consistently.

### 7.2 L2 and L3

There are no `runtime/L2_memory.py`, `runtime/L3_memory.py`, `runtime/L2_memory_utils.py`, or `runtime/L3_memory_utils.py` modules in the verified snapshot.

Remaining L2/L3 names occur in stale tests, old docs, comments, UI compatibility text, and historical session fields. Those names are not evidence that the layers still exist architecturally.

### 7.3 Facts Memory

Facts Memory is a companion candidate index produced from FRAME snapshots on the server. Its durable source is `memory/facts/pending_facts.json` (or `pending_facts_anon.json` in anonymous mode); browser facts-memory buckets are only a projection of that file-backed profile.

`facts_memory_store_sync` no longer makes an ordinary browser inventory authoritative. It has one narrow upgrade bridge that can import pre-file-store browser candidates once while the pending-facts file carries a legacy migration flag. Backend L-T code then normalizes these records and marks analyzed fields. This is an intake/candidate mechanism for L-T, not an independent durable product layer equivalent to old L2/L3.

### 7.4 L-T long-term memory

Active modules:

- `runtime/LT_memory.py`
- `runtime/LT_memory_rules.py`
- `runtime/LT_memory_utils.py`
- `utils/long_term_facts_file_store.py`

L-T owns durable facts. The current L-T path includes:

- Facts Memory candidate ingestion;
- extraction phase;
- merge/rebase/validation phase;
- explicit-edit protection;
- links to Delayed Memory reports;
- archive/anchor classification;
- delete/restore reconciliation;
- server/browser store synchronization;
- persistent mention tracking (`mention_count`, `last_mentioned_at`) and historical-log backfill;
- recall decay: after 24 hours without a mention, Brain context uses sentence previews capped at 100 characters per sentence until JIN references the fact again.

A valid `F<number>` reference in JIN reasoning or visible output counts once per turn for that canonical fact, updates `last_mentioned_at`, increments `mention_count`, persists the store, and makes the next prompt eligible for the full fact value again. Historical mention backfill may repair older dates but never rewinds a newer live mention.

In the current single-server-event-loop deployment, L-T commits are synchronous:
read/reconcile the latest file state, apply the change, then persist without an
intervening `await`. Backfill scans archives in a worker but performs this whole
commit on the event loop too. Offloading only the final snapshot write breaks
that ordering and can overwrite another page's committed edit/deletion. This
does not provide cross-process locking for multiple servers sharing one file.

L-T work is scheduled from an explicit browser idle tick (`lt_memory_idle_tick`) and is guarded so it does not begin while foreground work is running or queued. Explicit `UPDATE_LT_FACTS` notes instead queue during Brain dispatch and wait for that turn's FRAME task to finish applying and publishing state before their Service request starts. The request-card event is not a completion boundary. Cancelling an explicit L-T waiter for a new USER preserves both its queued note and the running FRAME task.

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
  "anchor_lt_facts_ids": [],
  "lt_facts_ids": [],
  "attachments_ids": []
}
</SAVE_DELAYED_MEMORY>
```

Important semantics:

- report inventory and loaded report body are different prompt concepts;
- reports can link L-T facts and persistent files;
- `anchor_lt_facts_ids` must be a subset of `lt_facts_ids` under the current contract;
- loaded/pinned/referenced/inspected are different states;
- old key/value `SAVE_DELAYED_MEMORY_CONTENT` form is legacy only.

### 7.6 Active Memory

Active Memory is live unresolved structured state/commitments, stored independently from FRAME text.

Current model-facing boundary:

```json
{"conditions":"...","custom_field":"..."}
```

`UPDATE_ACTIVE_MEMORY` exposes one canonical JSON shape: `active_memory_id` plus a `fields_to_update` object containing every field change.

Creation custom fields are explicit structure only: JSON root fields beside `conditions` are accepted (up to the current three-custom-field cap), while non-JSON text is preserved as conditions and is not mined for `(field: value)` suffixes. Duplicate normalized JSON keys follow normal last-value-wins behavior before the cap is applied.

Compatibility code still accepts legacy nested `fields`/`updates`, older line-based update payloads, and a self-closing UPDATE attribute form. Those are localized reader compatibility. Internally/browser-side, Active Memory is still represented in a transitional string-record format with metadata suffixes; that is an implementation detail, not the desired model-facing schema.

Paused Active records are removed from the Brain prompt. Memory Attention may reorder the prompt projection by lexical/context relevance without changing canonical storage order.

### 7.7 Persistent Files

Persistent uploads are owned by `utils/attached_files_store.py` and `assets/files/` plus its index. Stable IDs are reused by:

- prompt attachments;
- Delayed report links;
- file actions;
- UI memory/file projections;
- Live Avatar/link highlighting.

The composer projects currently pinned files as compact attachment chips. A chip opens the existing file preview on click and uses the shared hold interaction to detach/unpin it from the outgoing context. Detach does not delete the underlying persistent asset, and attachment changes do not implicitly expand Console.

### Project review through linked files

`<ATTACH_FILES_BY_ID> id1, id2 </ATTACH_FILES_BY_ID>` expands to ordered
internal `ATTACH_FILE_BY_ID` actions and attaches whole existing persistent files through
the ordinary pin/hydration path. Text uses the shared attachment context budget;
images use the existing multimodal Brain payload when image input is enabled.
It accepts only system IDs, never paths, stored filenames, or line ranges.

`<LOAD_DELAYED_MEMORY> id1, id2 </LOAD_DELAYED_MEMORY>` expands to ordered
loads whose report bodies are stored as individually identified tool results.
Model loading never writes `<LOADED_DELAYED_MEMORY>`; that durable context block
is reserved for reports the user explicitly pins. There is no model-facing
`UNLOAD_DELAYED_MEMORY` contract because `CLEAN_TOOL_RESULTS` removes model-loaded
reports from context.
Missing/deleted IDs fail without falling back to project reading. Its result
uses the existing bubble, Session Actions, tool-result and checkpoint paths.
`ATTACH_FILE_CONTENT` remains the source-path/range reader, with its old
persistent-ID handling retained for compatibility.

`LINK FOLDER` beside `ATTACH FILE` accepts a local path (including a folder
copied into `assets/`) or a `file:///` URL. The user-facing endpoint validates
the directory and stores an ordinary `.jin-folder` descriptor in Files. Its
existing id, pin/unpin, preview, delete/restore, and session attachment paths
remain authoritative. Deleting the descriptor never deletes the project.
Remote repository URLs, project writes, execution, indexing, and ingestion
are outside this increment.

An attached folder activates the prompt-only `PROJECT_REVIEW` projection.
Brain retains recent conversation, FRAME, ACTIVE, and exact accumulated
reasoning across follow-ups. DELAYED inventory/bodies are restricted to
user-pinned reports; L-T is restricted to their linked facts. Historical
memory tool results cannot reintroduce excluded bodies. Canonical memory is
not cleared. Detaching the folder returns to ordinary context assembly.

`ASSET_ACTION` exposes `project_tree` and `project_search`. File loading uses
`ATTACH_FILE_CONTENT: file_id` or `ATTACH_FILE_CONTENT: relative/path#L1-L200`;
Relative paths
resolve against the single attached folder; multiple folders require
`folder_id/relative/path`. Known persistent IDs retain priority, and only a
known folder ID is treated as a prefix, not any six-character directory name.
The old
`project_read` subaction is only a compatibility adapter to the shared loader.
Paths remain confined to a user-attached folder. Reads are bounded exact
UTF-8 source ranges; actionable limits are reported without boilerplate.

`runtime_tool_results` owns project read snapshots, using its existing
persistence/bootstrap path; no separate loaded-file registry is added.
`FILE_CONTENT` projects each loaded body once, below compact TOOL_RESULTS.
Persistent attachments use the same projection, not USER/flow text. Explicit
ranges may be read again; the newest result owns the visible FILE_CONTENT for
that range, while a bare project path advances to the next unread window.
CLEAN_TOOL_RESULTS clears project snapshots along with tool results. Removing
a folder from the user attachment set unloads its source bodies. The normal
persistent file store and source project remain unchanged. Browser reload
restores exact loaded ranges through the existing checkpoint; unpinning a
folder does not resurrect old source bodies.

The ordinary dispatcher, bubbles, session actions and Brain follow-up loop
remain in use. Independent file markers can share one response; Brain is
briefly instructed to save useful findings, clean stale tool results, and continue reading.
Brain may save a DELAYED report during review without a separate save request;
this is a scoped exception to the ordinary report trigger. ACTIVE and L-T
updates retain their existing handlers and persistence policies.

### 7.8 Direct memory value editing

`runtime/memory_edit.py` implements explicit inspector edits without sending a model action. The browser opens the existing hover/details card as a page-local editor on double-click. Only values are editable:

- **FRAME:** only the latest frame; historical snapshots are read-only, and reserved Active/user-idle rows are rejected;
- **Active:** the record conditions/value; IDs, custom fields, pause status, creation metadata, and other suffixes are preserved;
- **L-T:** only the canonical fact value; ID/key/category/provenance and mention metadata are preserved.

The request carries the expected value, so concurrent/stale edits fail instead of overwriting a newer value. Manual FRAME edits and row deletions are rejected while live FRAME/foreground integration is busy because that same state is being replaced. Active edits remain available during Brain/FRAME work: Active owns `active_memory_records`, and FRAME snapshots project the current Active store rather than owning it. L-T edits persist to disk before publication and are unavailable when persistent writes are restricted. Active and L-T acknowledgements surface `updated_at` immediately in the open editor. Draft text remains page-local until the checkmark is acknowledged; rollback restores the last acknowledged value.

---

## 8. Memory Attention

`runtime/memory_attention.py` is a small, deterministic prompt-projection module. It implements only:

- lexical/current-context relevance ordering for Active Memory;
- temporary bubble tiers for Delayed Memory inventory matching;
- a narrow 1–3 relevant-fact focus cone for L-T.

Memory Attention is stateless. It does not call SERVICE, mutate or persist memory records, add prompt instructions, modify Brain temperature, drive avatar state, or maintain significance scores. Canonical storage/UI order remains independent from the prompt projection.

---

## 9. Persistence and session continuity

JIN deliberately splits persistence by owner/lifetime.

| State | Current storage/owner |
| --- | --- |
| live runtime FRAME for soft reconnect | `sessionStorage`: `jin.liveRuntimeMemory.v2` |
| atomic browser session checkpoint | `localStorage`: `jin.sessionCheckpoint.v2` |
| Active Memory | `memory/active/<active_memory_id>.json`; anonymous uses `<active_memory_id>_anon.json` |
| Facts Memory candidates / pending extraction | `memory/facts/pending_facts.json`; anonymous uses `pending_facts_anon.json` |
| Delayed Memory | `memory/delayed/*.json`; anonymous reports use the `_anon.json` suffix |
| L-T facts | `memory/facts/long_term_facts.json`; anonymous uses `long_term_facts_anon.json` |
| FRAME crash-recovery journal | normal rooms: `memory/frame/*.frame_pending.json`; disabled for anonymous rooms |
| persistent files | `assets/files/` + file index |
| visible chat / reasoning logs | `logs/` |
| live in-process orchestration | `RuntimeContext` |

Chat-log paths are reserved without creating directories. Prepared context and inherited FRAME snapshots wait in the live context until a dialogue row, runtime action, or non-empty reasoning is actually written; a stopped blank bootstrap leaves no session directory. Interrupted reasoning is retained without manufacturing a completed JIN row. JSONL rows omit the redundant `dialog_path`; reasoning files retain their useful backlink.

FRAME audit files live beside `reasoning/` in `frames/<HHMMSS>_frame_<N>.txt`, sharing the session log prefix and visible FRAME number (including the reconnect offset). Creation, bootstrap projection, and in-place refresh use the same writer; a refresh replaces its own frame file, including an emptied frame, while older frames remain intact. These files are inspectable logs, not a new memory/restore owner.

### 9.1 Soft runtime resume

`runtime_resume` reconnects browser runtime state to a live/new backend context without being an archived-session checkout.

### 9.2 Session bootstrap / live checkpoint

The owner-locked lifecycle is D049 in `JIN_DECISIONS.md`: greeting-only tabs
never become saved continuation sessions; any real USER send does, including
an interrupted USER-only turn. Completed real turns restore as USER then JIN
with reasoning, before the source session divider. Stop invalidates a queued
startup tick even across a FRAME wait; accepting a real USER cancels unfinished
startup before queueing that USER. An aborted pending USER batch commits through
the ordinary USER-only cancellation path without making a model request.

`ui/static/js/runtime/runtime-session.js` persists live checkpoints and sends `session_bootstrap` data when appropriate. The backend normalizes and hydrates the browser-provided snapshot in `websocket/bootstrap.py`.

For normal bootstrap, a missing source archive invalidates its whole browser
replica before hydration. The newest surviving real USER archive wins even if
older than that replica; with no surviving archive the bootstrap is empty.
Startup-only log rows/reasoning are deferred in RuntimeContext until the first
real USER, alongside the existing deferred prompt/FRAME snapshots. A live
worker cannot recreate its previously materialized directory after deletion.

Browser runtime continuity has two intentionally different lifetimes. `jin.liveRuntimeMemory.v2` exists only in the current page's `sessionStorage` and supports soft WebSocket reconnect. The module clears that key on page execution, so reload and new-tab bootstrap cannot inherit a copied live FRAME. `jin.sessionCheckpoint.v2` is the single durable, atomic `localStorage` record containing lineage, runtime memory and update count, runtime snapshot, and `session_snapshot`.

The atomic checkpoint names the last runtime session that actually moved. Merely opening/reloading a tab hydrates inherited FRAME into the fresh page's ephemeral live record and records its source lineage, but it does not promote the fresh runtime ID. A successfully emitted real USER message marks session activity immediately; a later server `completed_turn_commit` is the fallback commit signal. Retry, bootstrap, reconnect, and passive UI/runtime events do not mark activity. `conversation_committed_at` advances only for a completed turn, so it remains distinct from USER-only session movement. Nested runtime snapshots preserve their own origin session ID.

Session CLEAR replaces the durable record with a version-2 `state: "cleared"` tombstone and clears the current page's live FRAME plus all legacy runtime keys. Other already-open tabs cannot passively resurrect state. The first later checkpoint is allowed only after a successful new USER send; it carries the clear boundary forward so a still-older tab cannot overwrite the new owner after the tombstone has been replaced.

One-time normal-profile checkpoint migration follows ownership rather than freshness. Anonymous rooms never read or migrate that normal-profile checkpoint; they use a fresh tab-scoped `jin.anonymousSession.v1` snapshot instead.

The server sends a normalized `session_snapshot` at visible `message_end` and again at `agent_runtime_end`. The client merges the current room state into that snapshot and persists it before finishing the visible bubble. Completed state and room/avatar state therefore land as one checkpoint rather than racing through separate full writers.

For a predecessor/browser checkpoint, `websocket/bootstrap.py::enrich_session_bootstrap_from_archive()` may enrich dialogue, reasoning, action history, files, counters, and selected runtime state from raw logs. Anonymous rooms never archive-bootstrap. Their chat/reasoning still goes to `logs/`, but the session directory ends in `_anon`; normal restore selectors and L-T mention backfill skip those directories.

The latest raw-log selector chooses the session containing the newest real USER move. A blank bootstrap-only session with no USER row cannot win. A stopped USER-only move and a completed action-only move with an empty visible JIN row can win and remain distinguishable by whether a durable JIN row/timestamp exists. The legacy function name `find_latest_completed_session_restore_payload()` is therefore narrower than its current semantics.

Bootstrap uses two freshness clocks:

- dialogue/reasoning/counters compare the browser recent-turn tail to the archive recent-turn tail;
- runtime/resource fields still use checkpoint `saved_at` against archive tail time.

This separation prevents a harmless fresh-page hydration or room-state write from pinning dialogue to an older turn. `saved_at` must still represent a whole-checkpoint refresh, not an incidental field mutation.

Session actions are merged by stable ID when available, otherwise by structured identity, sorted by real `created_at`, and bounded. For an unchanged source session the common checkpoint owns actions at or before `saved_at`; raw logs may append only a newer tail. If raw dialogue proves that another source session has a strictly newer USER move, the stale browser source, its actions, and its color are discarded together.

`CLEAN_TOOL_RESULTS` has an explicit field-local persistence rule. On successful cleanup, the browser writes the remaining `session_snapshot.tool_results` and monotonic `tool_result_sequence` inside the existing checkpoint and preserves checkpoint timestamp/lineage verbatim. `<CLEAN_TOOL_RESULTS> T1, T2, T3 </CLEAN_TOOL_RESULTS>` removes the listed modern blocks atomically, while an empty `<CLEAN_TOOL_RESULTS></CLEAN_TOOL_RESULTS>` block removes all old results. Legacy blocks keep no ID and therefore require the empty full-clean block. Invalid or missing IDs produce a failed bubble, session action, and readable failure tool result without removing any listed data. During enrichment, the mere presence of `tool_results` (including `[]`) is authoritative, so old archived search/tool output cannot resurrect in a new tab. This exact-empty rule is intentionally **not** shared by `loaded_memory_ids` or `active_memory_records`; their empty browser collections still use the established archive fallback behavior.

Late append-only L-T tool results are the one post-checkpoint tool-result enrichment: a newer raw `runtime_tool_result` of kind `lt` may be merged after the greater of checkpoint time and `tool_results_cleared_at`. Other old tool results remain blocked by the browser checkpoint/tombstone.

Session-action parts are structured continuity data. Bootstrap normalization currently preserves `text/detail/message/id` plus recognized `colors`; color metadata is normalized to lowercase `#rrggbb` (including expansion from `#rgb`) so restored JIN_COLOR actions keep the same swatch and hex hover metadata as live actions.

Current JIN color is part of the same checkpoint. For the same source session, explicit browser `current_jin_color` wins over action history and archived trusted state. If that field is absent, the newest structured JIN_COLOR session action is the first fallback, followed by the raw archive/trusted color. Applied colors are also recorded as raw runtime events so a direct-predecessor chain can recover both final color and ordered history.

Room-state persistence is field-local. It normally refuses to write across a session-ID mismatch and never changes checkpoint `session_id`, lineage, or `saved_at`. JIN_COLOR uses one synchronous reconciliation exception: after the UI applies a live color it may merge that color into the existing common checkpoint even before the new runtime session is promoted, while preserving checkpoint ownership and freshness metadata.

Old L3-era fields can still appear in tests/compatibility paths, but there is no active L3 memory module.

### 9.3 Normal bootstrap chat tail

After backend hydration, normal bootstrap emits at most the five newest `runtime_recent_turns` to the browser. Each item may carry USER text, JIN text, saved reasoning, and original timestamps. Attachment-context boilerplate is removed from the visible USER bubble.

The client rebuilds the tail through the existing chat primitives. It keeps a real USER-only interrupted/action-only turn but does not manufacture an empty BR bubble. It then appends a divider labelled with the source session's last message time (`jin_created_at`, otherwise `user_created_at`, in the browser's local timezone; no dated divider if neither timestamp is available) and activates the live-turn viewport at that boundary, leaving the inherited five-turn history immediately above the initial screen. Explicit archived restore owns its own rendering path and suppresses this normal-bootstrap tail.

### 9.4 Archived session restore

Archived restore is a distinct path:

1. HTTP endpoint `/api/sessions/{session_id}/restore` builds payload from logs via `utils/session_restore.py`.
2. Browser renders the same bounded five-USER-move tail carried by the restore payload and sends a `session_bootstrap`/restore payload. Saved reasoning is attached to its owning JIN turn after archive-file metadata is removed; later visible JIN-only restore rows remain in order.
3. Backend sets `runtime_session_restore_priming` and stages historical resource IDs/metadata.
4. A hidden `archived_session_resume` Brain tick receives restore-specific context.
5. The hidden restore prompt projects the newest complete visible USER/JIN dialogue in `<PREVIOUS_CHAT_MESSAGES>`, with compact relative ages derived from archived timestamps, then carries the previous reasoning evidence in `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>` when available, and only then emits the mandatory automatic-restore notification. There is no separate raw reasoning dump or replay of old action markers as executable intent.
6. Historical loaded Delayed IDs and attached files are staged until after the restore greeting; room/avatar state is already restored by the bootstrap path and is not replayed as runtime actions.
7. `BrainNode` consumes the staged restore envelope and replays only those delayed-memory/file resources through the normal runtime-action dispatcher.
8. The WebSocket tail performs defensive cleanup only; it must not apply the same resources a second time.

At prompt-build time the restore instruction prepends the fresh runtime session ID and timezone-aware current time directly above `!!! USER DIDN'T SEND NEW MESSAGE! !!!`. Archived USER timestamps remain historical dialogue metadata and are never reused as the bootstrap time.

The legacy restore-reasoning dump is retired. Saved reasoning remains available to archive/UI continuity and restore-derived metadata such as the latest reasoning/fact references, but it is not serialized into a separate bootstrap dump. Restored visible dialogue uses the normal five-pair limit and, like ordinary recent-message context, does not impose a per-message character cap.

The RESTORE endpoint owns archived dialogue, reasoning, and FRAME for explicit URL checkout. A same-session browser checkpoint may contribute a newer room/avatar and Session Actions projection, but it cannot overwrite only `recent_turns`, reasoning, or runtime memory and thereby create a mixed conversation source. Legacy `<OLD_SESSION_RESTORED_STATE>` wrappers are normalized to the canonical `<PREVIOUS_CHAT_MESSAGES>` block. On the one-shot priming turn, that inherited dialogue and its carried reasoning evidence are projected before the mandatory automatic-restore notification; FRAME remains background state and may legitimately predate the final archived turn.

`utils/session_restore.py` still understands historical `SAVE_SESSION` labels in archived logs. That is restore compatibility, not proof of a current `SAVE_SESSION` runtime action.

### 9.5 Timestamp invariant

Modern records/snapshots should retain original creation timestamps across serialize -> reload -> hydrate. `now()` is only a fallback for truly legacy records without a timestamp. Rendering/loading must not rewrite historical time.

---

## 10. Anonymous room mode

Anonymous mode is an explicit JIN room state, not browser-private/incognito detection. A long press on the avatar opens a fresh room URL carrying `anonymous_mode=1` and a generated `<uuid>_anon` runtime/session id.

Backend behavior:

- runtime is marked anonymous and unrelated persistent side effects remain restricted;
- Active, Delayed, Facts Memory candidates, and L-T use the same file-backed profile machinery as normal mode but with `_anon.json` filenames;
- those anonymous memory files are shared by concurrently open anonymous rooms and are removed after the last anonymous room closes;
- the FRAME crash-recovery journal under `memory/frame` is disabled;
- `UPDATE_LT_FACTS` and `SAVE_DELAYED_MEMORY` mutate only the anonymous file-backed profile;
- Delayed sync supports restore, pin/unpin, and delete against the anonymous profile without touching normal files;
- a soft WebSocket reconnect preserves the room's reports and loaded bodies;
- persistent asset-write actions are restricted;
- chat and reasoning still log normally under `logs/<date>/<session>_anon/`;
- normal restore/bootstrap and L-T log-freshness scans ignore `_anon` sessions.

Browser behavior:

- `sessionStorage` still carries tab-local room/bootstrap state, but it is not the source of truth for Active/L-T/Delayed/Facts Memory;
- server `memory_profile_snapshot` replaces browser memory projections from the `_anon.json` files;
- normal `localStorage` Active/L-T/Delayed/Facts Memory data is not allowed to seed the anonymous profile;
- a dedicated scene tint visually marks the room.

---

## 11. Stop, interruption, and recovery

`websocket/tasks.py::cancel_current_task()`:

- marks the active turn interrupted;
- can distinguish discard vs interrupted-memory update;
- aborts active runtime actions;
- closes active model streams;
- cancels the task;
- can schedule the interrupted FRAME update.

`process_message()` later routes interrupted turns through `schedule_interrupted_runtime_memory_update()` instead of pretending the turn completed normally.

The Brain/stream layer also contains recovery for reasoning repetition and model/context output limits. Follow-up ticks preserve sequence identity rather than starting a new user request. They explicitly suppress the ordinary previous-reasoning projection and carry the relevant current-turn or loop-recovery reasoning through their dedicated builder. The corresponding session-action interruption entry is emitted before that recovery/follow-up starts, not deferred until the final answer.

---

## 12. UI synchronization and Live Avatar

The browser is a projection of runtime state, not an independent semantic authority.

Important shared identities include:

- Active Memory IDs;
- Delayed report IDs;
- L-T fact IDs;
- file IDs;
- runtime action IDs;
- turn/sequence IDs.

The Live Avatar and memory panels consume the same identities but may show different **strength** depending on cause:

- object actually loaded into context -> active/strong state;
- object merely referenced/cited by ID -> weak linked state;
- object only inspected in a modal -> no implied context load.

Do not collapse these into a generic highlight state.

The L-T panel deliberately separates compact browsing from surfaced evidence: ordinary fact rows use a 50-character value preview, while a row bubbled by runtime reference, explicit reasoning citation, or context-loaded state renders its full value. The storage value is never truncated; this is projection-only behavior.

The memory panel exposes five persistent navigation tabs: `FRAME` (live runtime-memory snapshots), `ACTIVE`, `DELAYED`, `L-T`, and `FILES`. Their shared count control is projected below the active tab; only FRAME exposes previous/next snapshot controls. The temporary unprocessed-facts projection is intentionally omitted from the tab bar. Delayed rows use the same floating detail-card primitive for a bounded report preview (title/summary, creation time, tags, report ID, anchor/fact IDs, and up to 200 body characters). Unpinning a Delayed report emits the shared `memory_unpinned` logger event instead of becoming an invisible panel-only mutation.

L-T facts are partitioned into Live Avatar lanes of at most 100 records; additional facts create additional outer L-T rings with a small radius step. The Active ring is laid out relative to the resulting outermost L-T radius so it remains between L-T and persistent files. Memory-row hover reuses the existing avatar hover-zoom/reference path rather than rebuilding ring state.

Completed assistant messages expose an explicit `Copy all` control under the avatar/message host. The old invisible bubble gesture surface is removed; answer-rating code remains present but release-disabled.

L-T merge telemetry keeps a structured `lt_merge_applied` trace with operation details. Console Apply/Show inspection renders update/create/merge/ignore rows and token-level diffs from the structured trace; legacy human-text parsing is fallback compatibility only.

FRAME summarizer logging uses one `[MEMORY:FRAME]` card (`extract -> apply`, plus `show`) per request. The request uses the non-streaming Service API; clicking the pending extract label opens the request immediately. After application, `show` and `apply` open `FRAME SUMMARIZER RESPONSE` with one `EXTRACTED FRAME` context-style key/value card. Failed, skipped, and cancelled requests terminate the pending state without presenting a successful apply. L-T extraction and merge request labels are likewise inspectable while pending.

Session-action logger rows are also a projection of structured history. The compact logger keeps the most recent five items in chronological order with their original numbering and reuses the existing attached-files header/button primitive for `FULL`. JIN_COLOR parts render one swatch per applied color and expose the normalized hex on hover; bootstrap must preserve the `colors` payload for this to work after reload. Runtime-action bubble details are retained across counter-only updates so a count refresh cannot erase existing hover metadata.

JIN visual-action chat bubbles are currently release-gated off, but parsing, execution, avatar updates, raw event persistence, and Session Actions logging remain active. A UI visibility flag must not be mistaken for a disabled runtime action.

Color has one visual transition owner in the avatar API. The initial bootstrap application consumes the one 2000 ms transition; later/live JIN_COLOR applications use 333 ms. The API writes the same temporary duration to avatar-center and scene-tint CSS variables before applying the color, so both projections move together. The old color queue and separate bootstrap tint-shift helper are absent.

Normal session bootstrap applies the color from the common local checkpoint during early room restoration, then accepts one server `session_actions_update` reconciliation with `bootstrap_restore=true`. There is no client-side color resolver scanning competing sources.

### Chat bubble skins and context-pressure scaffold

Chat bubbles currently support `dark`, `light`, and `bamboo` skins through `ui/static/js/win95-theme.js` and `ui/static/css/chat-bamboo.css`. Normal theme defaults to `dark`; Win95 defaults to `light`. `jin_bubble_skin` stores the selected skin and `jin_bubble_skin_pinned` records whether it should survive theme changes. Choosing the current theme default leaves the skin unpinned; choosing a different skin pins it. The Context/trace settings surface exposes all three choices.

The Live Avatar scaffold is also part of the context-pressure UI. `runtime-panel.js` writes `--jin-context-pressure-color` and `--jin-context-pressure-percent` from the Brain context meter (hue 150 -> 15 as usage goes 0 -> 100). Static scaffold circles do not rotate and use that pressure color. Sixteen rays breathe on a fixed 30-second cycle, fully fading to zero; pressure raises the active subset from 3 toward 7 rays and raises peak opacity from 0.10 toward 0.50 before each ray's local-strength multiplier. Center hide fades scaffold/runtime/memory/file layers for 420 ms and then switches them to dormant display/animation state; the central light remains visible.

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

Do not infer current architecture from compatibility/history alone:

- `USE_SERVICE_AS_BRAIN`, archived `RUNTIME_MODE=SERVICE`, archived `role=service`, or old `[SERVICE]` logger-card code;
- `SAVE_SESSION` references in tests/log parsing;
- comments/log filters mentioning the old numbered-layer glow names;
- pre-L3-removal storage migration keys/fields;
- stale repository indexes or historical test assumptions;
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
