# JIN Core Engine Architecture

This document maps the runtime boundaries, state ownership, data flow, persistence, and extension points in JIN Core Engine.

`README.md` covers product behavior, setup, configuration, and the public feature surface. `LIVE_AVATAR.md` covers avatar rendering and visual-state rules.

---

## 1. Runtime Structure

JIN is built around one live runtime state shared by the WebSocket session, model roles, memory engines, runtime actions, persistence, and browser projections.

The main execution path is:

```text
Browser UI ↔ WebSocket ↔ RuntimeContext → AgentRuntime → Brain
                              ↕               ↕
                           Service        Action Engine
                              ↕               ↕
                           Memory      Files / Skills / Search
```

`RuntimeContext` in `runtime/runtime_context.py` is the in-process state hub for an active runtime. It carries model clients, active streams, current memory, delayed reports, active memory, L4 state, attachments, action history, tool results, telemetry, session counters, recovery state, and background-task references.

The surrounding modules have narrow ownership:

| Area | Main responsibility |
|---|---|
| `websocket/` | connection lifecycle, bootstrap, queueing, user-turn orchestration |
| `agent/` | direct Brain execution and turn state |
| `runtime/` | live state, streams, memory engines, telemetry, recovery |
| `contracts/` | runtime-action definitions and Brain-facing action rules |
| `utils/actions/` | action payload handling and state mutations |
| `utils/context/` | Brain context serialization |
| `clients/` | OpenAI-compatible model and search clients |
| `ui/` | browser projections of runtime state |

---

## 2. Connection and Session Lifecycle

The browser uses `/ws/chat` as the live runtime channel. `websocket/bootstrap.py` creates a new `RuntimeContext` or reconnects the socket to resumable state, then hydrates memory, delayed reports, files, counters, and browser-provided session data.

Each context owns a `PendingRequestQueue`. User messages and internal continuation ticks run serially through that queue, which keeps turn order stable while generation, actions, and memory updates overlap in time.

A socket and a logical runtime have separate identities. Reconnect can attach a fresh transport to an existing context. Explicit session bootstrap can restore saved L1/L3 state and related runtime metadata.

Core files: `websocket/__init__.py`, `websocket/bootstrap.py`, `websocket/tasks.py`, `runtime/registry.py`.

---

## 3. User Turn

`process_message()` in `websocket/messages.py` coordinates a normal turn.

1. Hydrate attachment ids against the persistent file store.
2. Apply browser runtime signals such as Active Memory, idle time, counters, feedback, and avatar state.
3. Match Delayed Memory tags against text typed by the user.
4. Create the turn and action-sequence ids.
5. Build `AgentState` and run `AgentRuntime`.
6. Stream reasoning, visible content, runtime-action state, and telemetry to the browser.
7. Record the completed turn and action history.
8. Schedule the Service-model L1/L2 update.

A later user request waits for a pending memory update before entering Brain execution. This keeps the next prompt aligned with the latest accepted turn.

Interrupted turns use the interrupted-memory path in `runtime/L1_memory.py`, so partial work can still update live state with separate lifecycle metadata.

---

## 4. Agent and Model Boundary

`AgentRuntime` passes each user turn directly to `BrainNode`. Brain is the visible reasoning and response role. Service handles background memory work and supporting inference.

Roles are resolved separately from physical model endpoints. `USE_SERVICE_AS_BRAIN` can assign the Service endpoint to the Brain role while the rest of the runtime continues to address it as Brain.

Model access goes through the OpenAI-compatible clients in `clients/` and `runtime/client.py`. Provider metadata can supply the loaded context window for live budgeting and telemetry. Stream-level output protection remains inside `RuntimeStream`, where it can interrupt repetition or malformed generation during generation rather than after the Brain has finished.

Core files: `agent/runtime.py`, `agent/nodes/brain.py`, `clients/registry.py`, `utils/brain_client_utils.py`.

---

## 5. Brain Context

`rules/brain_context_builder.py` assembles the Brain system context from current runtime state.

The builder combines the state relevant to the current tick: L1, L2, L3, L4, Active Memory, loaded Delayed Memory, attachments, skills, tool results, TODO state, feedback, session counters, recent visible turns, selected previous reasoning, and enabled runtime-action rules.

The assembled prompt is a transient projection. Canonical state remains in `RuntimeContext`, browser stores, and filesystem stores.

Action follow-ups use a dedicated context path in `agent/nodes/brain.py`. The follow-up carries the original sequence request, trusted action results, current runtime state, preserved attachments, and selected reasoning edges. The sequence stays under the original turn id and action-sequence id.

`BRAIN_MAX_FOLLOWUPS` bounds continuation ticks. At the ceiling, the runtime switches to a final response tick with action execution disabled.

---

## 6. Stream and Runtime Actions

`RuntimeStream` in `runtime/stream.py` separates three output channels from Brain generation: reasoning, visible answer text, and private runtime-action markers.

Action markers are matched against contracts from `contracts/*.json`. `contracts/rules_assembler.py` exposes enabled actions to the Brain, and `utils/actions/dispatcher.py` routes accepted calls to action-specific handlers.

The action path is:

```text
Brain marker → contract → payload normalization → guard → handler
             → runtime mutation / external result → action event
             → trusted tool result → optional Brain follow-up
```

Behavior guards in `runtime/action_guard.py` can require user intent or confirmation before a state-changing action proceeds. Confirmation state belongs to the runtime and survives the continuation flow.

Actions share sequence history through `runtime_action_events`, `runtime_session_action_history`, and tool-result state on `RuntimeContext`. UI action bubbles and logger entries consume the same event stream.

---

## 7. Memory State

The memory systems use separate stores and update schedules because they feed different parts of the runtime.

| Layer | Runtime role | Update path |
|---|---|---|
| **L1** | current task and interaction state | Service update after a turn |
| **L2** | repeated interaction patterns | derived from L1 diff history |
| **L3** | compact session handoff | `SAVE_SESSION` flow |
| **Facts Memory** | durable candidates collected from runtime state | L1/facts synchronization |
| **L4** | persistent long-term facts | idle extraction, merge, explicit edits |
| **Delayed Memory** | larger contextual reports loaded on demand | actions, UI, tag triggers |
| **Active Memory** | unresolved commitments and conditions | create/resolve actions and browser state |

### L1 and L2

`runtime/L1_memory.py` maintains the current compact runtime memory, versioned snapshots, diffs, pending-turn batches, and response-feedback integration. `runtime/L2_memory.py` consumes L1 change history to update slower pattern memory.

### L3

`runtime/L3_memory.py` creates the saved session handoff. `SAVE_SESSION` completes its memory work before the related Brain follow-up continues, so that continuation sees the saved state produced by the same sequence.

### Facts Memory and L4

`runtime/L4_memory.py` runs L4 as a staged pipeline. Facts Memory supplies candidates, the idle extraction phase selects durable material, and the merge phase reconciles candidates with the current long-term store. Explicit L4 edits are tracked so automatic merge work preserves edits from the active turn.

L4 records keep source lineage and links to Delayed Memory. Merge, delete, and restore operations update those references through the reconciliation helpers in `runtime/L4_memory.py`.

Delayed reports can move ordinary L4 facts behind report content through `facts_ids`. `anchor_fact_ids` keeps selected facts directly exposed. Prompt assembly, the long-term panel, and avatar state use the same archive/anchor classification.

### Delayed Memory

Delayed reports are persistent JSON objects with content, tags, fact links, attachment links, and load metadata. `utils/delayed_memory_file_store.py` owns normalization and file persistence; `websocket/bootstrap.py` hydrates them into runtime state.

Reports enter context through runtime actions, UI state, pin state, or user-text tag matches. `attachments_ids`, `facts_ids`, and `anchor_fact_ids` connect reports to the file and L4 stores.

### Active Memory

Active Memory records hold unresolved runtime commitments. They are carried into the Brain context near L1 and keep independent ids and resolve state. Browser bootstrap and runtime actions synchronize the active records with `RuntimeContext`.

---

## 8. Files, Skills, and External Work

Persistent files are managed by `utils/attached_files_store.py`. Each file has a stable id, metadata record, pin state, and filesystem entry under `assets/files/`. Store reconciliation removes references to missing physical files and keeps pin state consistent.

A file can be present directly through pin/attach state or indirectly through a loaded Delayed Memory report. The same id is used by prompt assembly, report links, file actions, memory panels, and Live Avatar state.

Skills are context resources under `assets/skills/`. Runtime actions load and unload skill instructions for a sequence. Python skill execution is limited to `.py` files inside the selected skill directory and uses bounded execution controls.

Search actions produce trusted tool results. `WEB_SEARCH` uses the configured search provider. `runtime/deep_web_search.py` runs the bounded multi-query Service workflow used by `DEEP_WEB_SEARCH`.

---

## 9. Persistence and Reconciliation

JIN splits persistence by ownership.

Browser storage keeps session-facing state used for resume and direct UI interaction. Server-side files keep durable reports, long-term facts, uploaded files, and logs.

| State | Storage |
|---|---|
| Delayed Memory | `memory/delayed/*.json` |
| L4 long-term facts | `memory/facts/long_term_facts.json` |
| persistent files | `assets/files/` plus file index |
| chat/reasoning logs | `logs/` |
| session-facing runtime state | browser storage |

Bootstrap and mutation paths reconcile ids across stores. File deletion clears file references, L4 merge/delete/restore remaps report references, and delayed-report synchronization filters stale links. This keeps cross-layer ids usable after independent edits from the UI or runtime actions.

Core files: `ui/static/js/runtime/runtime-storage.js`, `utils/delayed_memory_file_store.py`, `utils/long_term_facts_file_store.py`, `utils/attached_files_store.py`, `websocket/bootstrap.py`.

---

## 10. Recovery and Limits

Generation state is tracked on `RuntimeContext` and `RuntimeStream`. User abort cancels the active task, closes stream state, records aborted actions, and can schedule the interrupted L1 update.

Stream validation detects repetition and malformed generation states. Context/output-limit recovery can start a continuation tick with preserved reasoning edges and the current sequence state.

Runtime loops have explicit ceilings: Brain follow-ups, Deep Web Search calls, skill execution, action retries, and related worker paths all use configured or hard limits.

Core files: `runtime/stream.py`, `utils/stream_validator.py`, `utils/runtime_action_abort.py`, `agent/nodes/brain.py`, `runtime/deep_web_search.py`.

---

## 11. UI Synchronization

The browser receives typed WebSocket events and updates the relevant projection of runtime state. Memory panels, context view, logger, action bubbles, attachment plaques, reasoning references, and Live Avatar share ids from the runtime objects they represent.

Typical synchronization paths are:

| Runtime change | Browser projections |
|---|---|
| L1 snapshot | runtime panel, context state, Live Avatar |
| L4 update | long-term panel, delayed links, Live Avatar |
| delayed load/pin | report state, context state, linked facts/files, Live Avatar |
| file pin/delete | attachment state, report links, context state, Live Avatar |
| runtime action | action bubble, logger, sequence history |
| reasoning/reference match | text highlight, matching memory/file/avatar item |

The Live Avatar uses the same memory and file identities as the panels. Its rendering rules and visual priorities live in `LIVE_AVATAR.md`.

UI state-only updates prefer in-place synchronization where stable identity matters. Full rerenders are used when the represented object set changes.

---

## 12. Change Rules

These rules describe the boundaries used by the current codebase when adding behavior.

**Persistent state gets one canonical owner.** New persistent data needs a store, stable identity, bootstrap path, mutation path, and reconciliation rules.

**Prompt sections come from canonical state.** Context builders serialize current runtime state for a Brain tick; mutations happen through the owning subsystem.

**Runtime actions cross the contract boundary.** A new action needs a contract, payload handling, guard semantics where required, dispatcher integration, result/follow-up behavior, and tests.

**Cross-entity ids are maintained during mutation.** Merge, delete, restore, pin, load, and detach operations update linked reports, facts, files, and UI projections.

**Internal continuations keep sequence identity.** Tool results, attachments, reasoning recovery, and follow-up limits stay attached to the original user sequence.

**UI primitives map to semantic states.** New backend behavior reuses existing loaded, pinned, active, archived, linked, referenced, and hover states when those states describe it accurately. A new visual primitive is added when it represents a new persistent distinction in runtime state.

**Long-running paths are bounded.** Agent continuations, workers, retries, and executable skills keep explicit ceilings.

---

## 13. Tests

The suite combines Python runtime tests with browser/client contract tests. Runtime tests cover agent routing, memory engines, actions, search, recovery, persistence, and token budgeting. `*_client_contract.py` tests protect the state and event shapes shared by Python and JavaScript.

For architecture changes, the useful test boundary is the full state path: canonical store → runtime mutation → emitted event → browser contract. Changes that alter cross-layer ids also need merge/delete/restore or load/unload coverage.

The current test commands and model-dependent probes are documented in `README.md`.

---

## 14. Main Extension Points

For a new runtime action, start in `contracts/`, then connect the handler in `utils/actions/`, add any guard or follow-up semantics, and cover the emitted event/state mutation in tests.

For a new memory behavior, start from its owner and lifetime: L1/L2/L3/L4, Facts Memory, Delayed Memory, or Active Memory. Add persistence and reconciliation only for state that survives the active context.

For a new browser projection, consume the existing semantic ids and runtime events from `ui/static/js/runtime/`. Avatar-specific rendering stays in `runtime-avatar.js` and `runtime-avatar.css`; the visual contract stays in `LIVE_AVATAR.md`.

For a new model-side context source, add serialization in `utils/context/` or `rules/brain_context_builder.py` and keep the underlying state in its owning runtime/store module.
