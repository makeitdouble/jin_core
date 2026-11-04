# Self Reflection — increment 2

JIN may emit `<RUN_SELF_REFLECTION>` on an initial autonomous heartbeat when
there is unprocessed archived history. The heartbeat notification offers this
as an option if nothing else needs doing; it assigns no task. The contract and
hint disappear when no eligible archive remains. USER turns, follow-ups,
anonymous rooms and restricted-write contexts cannot execute it.

One marker makes one non-streaming `clients["service"]` request through
`ask_service_model`, including existing usage accounting and summarizer request /
response logging. The result parser tolerates a Markdown JSON fence or short
text around one JSON object, then applies the strict reflection schema. There is
no extra Brain turn, chat session, scheduler or USER message. An error or Stop
produces a failed action/Tool Result and leaves the cursor unchanged; neither
success nor failure requests a Brain follow-up.

## Evidence and progress

- All retained live server session IDs are excluded, including disconnected
  runtimes that can still finish writes. Anonymous archives are always excluded.
- Date-directory fragments are grouped by session ID and ordered by timestamp,
  then source path and line. Exact duplicate dialogue across fragments is removed.
- Empty dialogue is skipped before indexing; action-only turns remain evidence.
  Snapshot actions retain compact `detail` and `context_detail`, with bulky payloads
  removed and each detail bounded to 700 characters plus an omission marker.
- USER/JIN records have consecutive indexes. Turns containing only actions get
  an indexed ACTION record. Action requests, actual tool outcomes and deduplicated
  action snapshots are associated by their owning turn, using tool IDs when present.
- Context/checkpoint/FRAME/reasoning payloads, binary data, HTML and long embedded
  file bodies are excluded. Tool summaries preserve success/failure fields.
- Service receives only indexed records strictly after the saved cursor, plus
  every existing characteristic's stable ID, original description and counters.
  It semantically chooses CREATE or UPDATE; topic or literal-text overlap alone
  is not an UPDATE rule.
- The first successful transaction saves the normalized source snapshot, keeping
  indexes stable on later calls. Later source edits do not rewrite that analysis
  snapshot. Deleted archives are not scheduled again; accumulated experience stays.
- `event_found` atomically stores the event, creates a stable `IC-xxxxxx`
  characteristic or updates the exact Service-selected ID, and moves the cursor
  to the event end. UPDATE never rewrites the original description. `no_event`
  records SKIP and completes the entire supplied remainder.
  An event reaching the last index also completes the session without an empty
  extra Service request.
  The next heartbeat can consider the next oldest eligible session.
- Corrupt unread archives are skipped with a diagnostic, never marked processed.

`memory/self_reflection/state.json` owns snapshots, cursors, completion flags,
event ranges, characteristics and aggregate statistics. One atomic replacement
commits all of them. A process-wide nonblocking claim prevents concurrent Service
requests and lost updates across rooms. A competing tick does not queue work.
The store has no browser-owned copy and no model-action write API.

State version 2 keys characteristics by stable `IC-xxxxxx` IDs. Version 1
text-keyed rows are deterministically migrated and atomically persisted when the
next reflection action claims the store; counters, snapshots and event history
are retained. Descriptions use any language convenient for Service. Success and
Failure remain unsmoothed fractions of their combined counters, displayed to two
decimal places. They are evidence, not behavioral commands.

## Context and UI

The Brain context builder reads `<JIN INTUITION BLOCK>` from disk on ordinary
turns and follow-ups, including anonymous rooms. The context viewer places it in
SYSTEM as a collapsible four-column table using existing card, text, border and
spacing primitives. The table now includes the stable ID before Behavior,
Success and Failure. Empty experience does not create an empty block.

The ordinary runtime-action path emits running/completed/failed bubbles, tool
IDs, Session Actions with status and result detail, and JSONL request/result/tool
events. Final stream reconciliation updates the early marker history after the
Service request finishes. Normal session snapshots preserve that result on reload.
The result detail states the source session, sent and selected ranges,
CREATE/UPDATE/SKIP, characteristic ID, outcome and cursor transition.

## Manual verification

1. Leave at least one non-anonymous saved session that is not live in the server.
   Open a normal room. Wait for the existing heartbeat (default: 300 idle seconds
   plus its 600-second interval). No separate night setting exists.
2. Inspect the initial Brain request: it should advertise RUN_SELF_REFLECTION and
   offer the optional hint. JIN may choose not to use it.
3. When JIN emits the marker, inspect its running and terminal action bubble,
   SELF_REFLECTION Service request/response, Tool Result and Session Actions.
4. After an event, inspect the next Brain request's SYSTEM tab: the intuition
   table should show the learned description and ratios. Reload and verify it remains.
5. Stop during Service execution: the action fails without advancing the cursor
   or starting a recovery turn. A later heartbeat can retry.
6. After a `no_event` completes the last eligible archive, the next heartbeat
   should omit the reflection contract and hint, retaining learned intuition.

## Scope and limits

The normalized session is assumed to fit the Service context. Token chunking,
semantic merging, recursive analysis, counterfactual evaluation and subagents
are deliberately absent. The analysis claim coordinates tabs within the existing
single server process, not separate servers sharing a memory directory.

No live provider request is needed for the automated tests; they use isolated
temporary archives and deterministic Service responses.


## Changed files

New runtime, persistence and contract files:

- `contracts/run_self_reflection.json`
- `runtime/self_reflection.py`
- `runtime/self_reflection_rules.py`
- `utils/self_reflection_history.py`
- `utils/self_reflection_store.py`
- `memory/self_reflection/.gitkeep`

Integration with existing paths:

- `agent/nodes/brain.py`
- `rules/brain_context_builder.py`
- `runtime/heartbeat.py`
- `runtime/runtime_context.py`
- `runtime/stream.py`
- `utils/actions/action_registry.py`
- `utils/actions/action_events.py`
- `utils/actions/common_action_utils.py`
- `utils/actions/result_reuse.py`
- `utils/tool_results.py`
- `utils/session_actions_history.py`
- `ui/static/js/logger/trace-modal.js`
- `ui/static/css/runtime-memory.css`

Tests and documentation:

- `tests/test_self_reflection.py`
- `tests/test_self_reflection_client.js`
- `AGENTS.md`
- `docs/JIN_ARCHITECTURE.md`
- `docs/JIN_DECISIONS.md`
- `docs/JIN_CURRENT_STATE.md`
- `docs/SELF_REFLECTION.md`

The pre-existing modification to `rules/runtime.py` is outside this delivery
and remains intact.
