# JIN Core Engine — Current State / Migration Notes

**Snapshot inspected:** `jin_core(20261001-090403).zip`<br>
**Inspection date:** 2026-10-01<br>
**Context reference:** current production source is the implementation baseline; durable decisions and historical correction notes are retained only where they remain compatible with that source.

This is the document to read before touching transitional code. It lists what is true in the inspected snapshot, what is legacy residue, and where product intent and implementation currently differ.

---

## 1. Executive state

The production runtime is on the post-L2/L3, Brain-first architecture and the root documentation is now synchronized with it.

Current high-signal state:

- transport continuity: the physical WebSocket no longer owns/cancels the runtime queue. `RuntimeContext.runtime_transport` retains accepted work and unacknowledged output in process RAM; a soft reconnect attaches to that live task and does not re-upload stale memory stores. Explicit page departure retires the runtime, while an unexplained disconnect has a 600-second reconnect grace before cancellation/release. Process restart still loses this in-memory transport state, and a discarded page's full DOM is not reconstructed server-side.

- foreground user turns always execute through `AgentRuntime -> BrainNode -> context.clients["brain"]`; no production branch can switch visible responses to Service;
- Service is background-only. With `SERVICE_API_BASE` empty, `clients["service"]` intentionally aliases the Brain client; configuring a dedicated Service endpoint changes only background execution;
- `USE_SERVICE_AS_BRAIN` survives only as a localized old-config migration input in `config_loader.py` plus launcher detection. Normalization promotes old Service settings to Brain, clears the dedicated Service URL, then deletes the legacy flag;
- archived `role=service` / `RUNTIME_MODE=SERVICE` handling and the logger's old `[SERVICE]` output-card presentation are historical reader compatibility only; there is no current writer/foreground route for that mode;
- L2/L3 remain removed architectural layers. Remaining production references are compatibility comments/log filters/storage migration residue, not active modules;
- the panel exposes five memory views (`FRAME`, `ACTIVE`, `DELAYED`, `L-T`, `FILES`) plus the `LOGS` session-archive projection; the internal Facts Memory candidate buffer is not a user-facing tab;
- FRAME is the canonical name for live runtime memory across documentation, implementation modules, state fields, events, the pending journal, UI identifiers, and tests.
- direct value editing is live for the latest FRAME, Active conditions/value, and L-T fact values; keys/IDs remain read-only, drafts are page-local until acknowledged, and Active/L-T edits surface `updated_at`.
- the L-T panel defaults to active facts, can toggle `show all` to reveal report-absorbed facts in normal sort order, and keeps report-linked fact IDs clickable.
- L-T recall now tracks `mention_count`/`last_mentioned_at`: facts untouched for 24 hours are compacted to 100-character sentence previews in Brain context until JIN references them again.
- pinned outgoing files appear as composer attachment chips; click previews, hold detaches from context without deleting the persistent file.
- Brain recent-message context is adjacent to `<FRAME_MEMORY_N>` and keeps the newest five pairs in full, with newline/XML normalization but no per-message character crop;
- ordinary Brain turns include the previous successful reasoning block with explicit middle-crop semantics, while follow-ups keep their dedicated reasoning context;
- empty action/recovery follow-up provider USER bodies use the internal `<system_follow_up_tick>` sentinel without creating a conversation USER move;
- reload/new-tab continuity is disk-owned (JSONL/runtime events plus saved `frames/` snapshots). Browser cognitive records are page-local projections only: `jin.liveRuntimeMemory.v2` is cleared at page load and the retired durable `jin.sessionCheckpoint.v2` browser value is removed before bootstrap;
- Session CLEAR is a durable tombstone that blocks passive resurrection across already-open tabs until a new USER message is successfully sent;
- `SAVE_SESSION` is not a current runtime-action contract; archived-session restore is handled by the bootstrap/restore path;
- the current action set includes `JIN_REACTION`, internal `RECALL_FACT_CONTEXT`, `CHAT_LOG_SEARCH`, generic skill-gated `CALL_MCP`, and the single `ATTACH_FILE_CONTENT` attachment marker; whole-file BY_ID/BY_PATH are ASSET_ACTION operations; fact recall, delayed-memory loading, Active deletion, skill loading, and skill unloading use paired list markers;
- runtime actions execute in exact model-emitted source order (`prepare -> run` per call); `runtime_order` only orders advertised contracts, and the former visual-sequence collector/stage path is absent;
- `BRAIN_MAX_FOLLOWUPS=0` is unlimited; positive values cap executable workflow ticks and then allow one final response tick with actions disabled. Malformed output gets at most one separate repair tick outside that budget;
- `CONCERNS` and its generation logic are removed (owner update 2026-10-25); independent `CONTEXT_MAINTENANCE` remains;
- bubble skins are `dark`, `light`, and `bamboo`, with dark/light following normal/Win95 theme defaults unless a non-default skin is explicitly pinned;
- Live Avatar scaffold circles/rays now mirror the context-pressure color, ray peak opacity scales approximately 0.10 -> 0.70 over a 30-second fade-to-zero breathing cycle, and center hide includes the file ring before switching hidden layers to dormant mode after the fade.

New agents must not “repair” compatibility residue by restoring the old topology.

---

## 2. Verified current topology

### Backend/runtime

Present and active:

- `app.py`
- `websocket/`
- `agent/runtime.py`
- `agent/nodes/brain.py`
- `runtime/runtime_context.py`
- `runtime/stream.py`
- live FRAME implementation modules under `runtime/`, including `frame_memory.py`, `frame_memory_rules.py`, `frame_memory_utils.py`, and `frame_memory_pending.py`
- `runtime/LT_memory.py`, `LT_memory_rules.py`, `LT_memory_utils.py`
- `runtime/memory_attention.py`
- `runtime/anonymous_mode.py`
- `contracts/*.json`
- `utils/actions/*`
- `utils/context/*`
- `utils/session_restore.py`
- `utils/mcp_skill_utils.py`, `utils/mcp_client.py`, and `utils/actions/mcp_actions.py`

Foreground/model-role invariants verified in production source:

- `utils/brain_client_utils.py::get_brain_runtime_config()` returns only runtime id/label `brain`;
- `agent/nodes/brain.py::BrainNode.run()` resolves that label directly from `context.clients`;
- `clients/registry.py` aliases Service to Brain by default and replaces only the background Service client when `SERVICE_CONFIGURED` is true;
- `websocket/messages.py` gates user sends on Brain availability only; an absent dedicated Service runtime does not block foreground chat.

Not present:

- `runtime/L2_memory.py`
- `runtime/L2_memory_utils.py`
- `runtime/L2_memory_rules.py`
- `runtime/L3_memory.py`
- `runtime/L3_memory_utils.py`
- `runtime/L3_memory_rules.py`

Filesystem/source audit confirms those L2/L3 modules are absent from the inspected archive.

---

## 3. L2/L3 and old-role residual compatibility

### Product intent

L2 and L3 were removed as architectural layers. Brain is the only foreground model role.

### Current production source

The runtime package agrees: L2/L3 modules are absent and the visible Brain path does not branch to Service.

### Production compatibility residue still present

- `runtime-storage.js` has one-time compatibility for checkpoints created before L3 removal;
- a few UI memory-log filters/comments still recognize historical L2/L3 labels;
- `config_loader.py` and `jl.ps1` recognize `USE_SERVICE_AS_BRAIN` only to migrate old local configs;
- `utils/session_restore.py` / `ui/static/js/session-restore.js` can render archived `service` roles and `RUNTIME_MODE=SERVICE`;
- `ui/static/js/logger/log-entries.js` can present old `[SERVICE]` model-output cards, although current backend code has no `log_service_output` writer.

These paths are localized compatibility readers/adapters. None changes current foreground routing.

### Test residue

Some tests still mention `CAN_SAVE_SESSION`, `<SAVE_SESSION>`, or other retired names as negative/compatibility fixtures. Treat those occurrences as test intent that must be read in context, not evidence that the action/topology is live. Current contract and prompt tests also cover the plural skill-context markers, five-pair dialogue window, structured Active update payload, chat/fact recall, and context/avatar client contracts. This documentation pass does not modify tests.

### Rule for agents

Classify every old-role/L2/L3 reference as one of:

1. required backward compatibility;
2. stale test/documentation;
3. harmless historical UI/log reader;
4. accidental live dependency.

Only category 4 is a production runtime bug. Do not turn categories 1–3 back into live architecture.

---

## 4. Session continuity / `SAVE_SESSION` transition

### Current implementation

Current session continuity is split across:

- live in-process `RuntimeContext.runtime_transport` soft reconnect/resume;
- disk-owned normal `session_bootstrap` selection from saved USER archives plus the latest committed FRAME;
- page-local browser projection (`runtime-session.js` / `runtime-storage.js`) that never selects or uploads reload state;
- explicit archived-session payloads built from logs (`utils/session_restore.py`);
- hidden `archived_session_resume` priming tick;
- staged resource replay through the normal runtime-action dispatcher.

### Current action layer

`contracts/rules_assembler.py::ACTION_CONFIG_KEYS` contains no `SAVE_SESSION`, and there is no `contracts/save_session.json`.

### Legacy residue

`SAVE_SESSION` still appears in:

- old tests;
- old behavior-probe expectations;
- `utils/session_restore.py::ACTION_LABELS` so historical archived logs can be interpreted;
- old L3/session terminology in test fixtures.

### Rule for agents

Treat `SAVE_SESSION` as historical/restore compatibility in this snapshot. Do not re-add a model action just to make old tests pass.

---

## 5. Current action contract set

`CHAT_LOG_SEARCH` now adds local literal chat-history search with OR queries,
source/date/time filters, attachment metadata and anchored reasoning excerpts.
It uses the existing action/result/error/bubble pipeline and does not require
web-search credentials. Raw archive restore accepts this structured runtime
result and its T ID; disk bootstrap preserves full matched messages without
slicing the result JSON at 32K. Details: [CHAT_LOG_SEARCH.md](CHAT_LOG_SEARCH.md).

Search verification (2026-09-08): 20 focused search, unclosed-action and readable
tool-result tests pass; the headless Edge socket-to-DOM test and existing tool-ID
history/checkpoint JS test pass. Extending the run with archived restore and
bootstrap-tail tests yields 54/58 passing. The four archived-restore failures
also reproduce with the original changed reader functions and original action
flags: old `runtimeMemory.saved_at` client expectation, one-shot restore prompt,
the then-current restore-dialog bound, and bounded URL-restore UI tail. Those were historical failures from the 2026-09-08 search work; the current shared dialogue bound is five pairs and the restore/follow-up prompt ordering has since changed. Older cleanup tests may still name removed function/log strings. This paragraph is historical evidence, not the current verification status.

The contract assembler currently advertises these actions in `runtime_order` order (this is prompt-contract ordering, not execution priority):

```text
DEEP_RESEARCH
WEB_SEARCH
CLEAN_TOOL_RESULTS
JIN_COLOR
JIN_REACTION
JIN_SIZE
JIN_POSITION
JIN_SPEED
UPDATE_LT_FACTS
RECALL_FACT_CONTEXT
CHAT_LOG_SEARCH
LOAD_SKILL
UNLOAD_SKILL
ASSET_ACTION
POSTING_BOARD
CALL_MCP
LIST_ALL_USER_SHARED_FILES
ATTACH_FILE_CONTENT
SAVE_DELAYED_MEMORY
LOAD_DELAYED_MEMORY
SAVE_ACTIVE_MEMORY
DELETE_ACTIVE_MEMORY
```

`LOAD_SKILL` and `UNLOAD_SKILL` are singular internal runtime action names. Their canonical public/model markers are `<LOAD_SKILLS_CONTEXT> skill1, skill2 </LOAD_SKILLS_CONTEXT>` and `<UNLOAD_SKILLS_CONTEXT> skill1, skill2 </UNLOAD_SKILLS_CONTEXT>`; each valid comma-separated item becomes one ordered internal action.

`utils/actions/dispatcher.py` is source-ordered: it fully prepares and runs each emitted call before touching the next one. The action registry has no execution stage field. Every concrete contract carries a separate `schema` string array before `rules`; `contracts/rules_assembler.py::get_runtime_action_schema()` feeds both model-facing contract text and failed-action diagnostics. Failed tool results are rendered as readable text (status/reason, supplied payload when relevant, `Correct action schema:`), and `ACTION_FAILURE_FOLLOWUP_MESSAGE` explicitly tells Brain not to assume the failed action completed.

`POSTING_BOARD` is a native action exposed only after `<LOAD_SKILLS_CONTEXT> posting_board </LOAD_SKILLS_CONTEXT>`. The side skill documents the minimal inner actions (`feed`, `inbox`, `read`, `search`, `post`, `reply`, `ack`, `delete`); the runtime executes them against Get Posting Board and records the exact public request preview plus response as a runtime tool result. Chat bubbles use one stable action ID from running to completed/failed, then fade and become clickable for the reused trace modal. Session Actions intentionally keep only compact markers such as `POSTING_BOARD: action:feed` or `POSTING_BOARD: action:post - failed`; request/response bodies stay out of session-action text. Public writes, including deletion, are blocked when persistent writes are restricted, while board reads remain available. `delete` targets one owned message by exact `post_id`; deleting a root removes the entire thread, so the skill requires explicit authorization and warns Brain to preserve roots unless whole-thread deletion is intended. The bearer token is resolved through the environment override helper from `GETPOSTINGBOARD_API_KEY` (or its supported `JIN_GETPOSTINGBOARD_API_KEY` alias) and is never projected into model/UI context.

`CALL_MCP` is generic and skill-gated. A loaded skill with valid `<MCP_SERVER>...</MCP_SERVER>` config is discovered with `tools/list`; the live server/tool schema is appended only to that loaded in-memory skill as `<MCP_RUNTIME>`, and then `CALL_MCP` can route `{skill, tool, arguments}` to an exact loaded skill/tool. One MCP connection is kept per loaded skill across follow-ups, calls are excluded from result reuse, and unload/runtime retirement closes the connection. Returned image blocks are capped at 20 MiB each, stored as pinned JIN files, stripped of base64, and attached to the current sequence so the next Brain tick can inspect them. Generic MCP bubbles open a structured request/result modal; `get_viewport_screenshot` reuses the standard attachment preview. Full contract: [MCP_SKILLS.md](MCP_SKILLS.md).

The mapped Brain feature flags in `rules/brain_context_builder.py` are enabled. `WEB_SEARCH` is filtered again by `settings.CAN_SEARCH`, while `DEEP_RESEARCH` remains visible for bounded multi-agent analysis and suppresses worker-requested web queries when search is unavailable. Provider `serper` requires a non-empty, non-placeholder process-environment key. `jl.ps1` imports an ignored repository-root `.env` before resolving configuration and starting Python; `.env.example` documents the supported secret names without containing credentials. Direct `python app.py` starts still rely on variables exported by the calling shell. The local availability check intentionally does not impose an invented key-length/shape regex; Serper remains the credential authority.

Canonical short action syntax is paired: `<WEB_SEARCH> query </WEB_SEARCH>`,
`<LOAD_DELAYED_MEMORY> id1, id2 </LOAD_DELAYED_MEMORY>`,
`<DELETE_ACTIVE_MEMORY> id1, id2 </DELETE_ACTIVE_MEMORY>`. Attachment uses `<ATTACH_FILE_CONTENT: id_or_path, id_or_path >`. A model-issued delayed
load records each report as a separately identified tool result and does not
populate `<LOADED_DELAYED_MEMORY>`. Only explicit user pinning populates that
block. `UNLOAD_DELAYED_MEMORY` is no longer a model-facing contract; tool-result
cleanup is the removal path.

`CLEAN_TOOL_RESULTS` is a strict paired-block action. The canonical targeted form is `<CLEAN_TOOL_RESULTS> T1, T2, T3 </CLEAN_TOOL_RESULTS>`; one or more exact `T<number>` IDs are listed in the body, separated by commas. Targeted cleanup validates the whole list before mutating state, so an invalid or missing ID removes nothing. An empty `<CLEAN_TOOL_RESULTS></CLEAN_TOOL_RESULTS>` block performs the explicit full cleanup, including legacy ID-less results. The old bare marker and `<CLEAN_TOOL_RESULTS: T1 >` inline form are no longer executable syntax.

`JIN_SIZE` contract version 2 currently advertises `<JIN_SIZE> w:120 h:120 </JIN_SIZE>`; a single value such as `<JIN_SIZE> 120px </JIN_SIZE>` means square size. Positive decimal values may use `px`, `vw`, `vh`, or `%`, with unitless values defaulting to `px`. The backend preserves those units in the canonical action payload. The browser resolves them against the live viewport when the action is applied: width `%` uses viewport width, height `%` uses viewport height, `vw` always uses viewport width, and `vh` always uses viewport height. The applied/clamped room geometry is then persisted in pixels. Unsupported suffixes such as `em` are rejected instead of being silently reinterpreted as pixels.

`JIN_COLOR` contract version 2 likewise advertises `<JIN_COLOR> #00f2ff </JIN_COLOR>`. Both actions put payload in a paired tag body. Localized parsing still accepts old colon/space inline variants, but those are not model-facing syntax. Current parser/formatter tests require ordinary `before`/`after` answer text to survive marker removal and cover split-chunk completion.

The runtime now also has a strict response-prefix fallback for missing angle brackets. Before visible answer text starts, an exact standalone `ACTION_NAME: payload` line may execute only for the current eligible set: `ATTACH_FILE_CONTENT` plus `JIN_COLOR`, `JIN_REACTION`, `JIN_SIZE`, `JIN_POSITION`, and `JIN_SPEED`. Paired/block actions such as `WEB_SEARCH`, `LOAD_SKILL`, `LOAD_DELAYED_MEMORY`, and `RECALL_FACT_CONTEXT` remain non-executable when written only as a bare internal action name. Invalid or prose-like payloads stay visible and immediately end the bare fallback; later bare lines stay text, while ordinary `<...>` markers continue to work. Streaming holds an unterminated candidate until newline or final flush, and accepted standalone action lines are removed without leaving a blank line.

The whole-response extractor and streaming filter now share the same `allow_bare_prefix_fallback` behavior/default, so chunked and non-stream parsing no longer disagree on this case.

JIN visual actions no longer use a dedicated sequence collector. Color/size/reaction/position/speed calls are ordinary actions executed in exact model-emitted order. Color and size filtering removes only a true no-op against the last applied value in the same runtime-message scope; alternation remains valid, and the same value can be requested again in another message.

---

## 6. Delayed Memory transition

### Current canonical contract

`contracts/save_delayed_memory.json` is version 5 and requires a JSON body inside `<SAVE_DELAYED_MEMORY> ... </SAVE_DELAYED_MEMORY>`.

Required fields:

- `title`
- `summary`
- `tags`
- `body`

Relationship fields:

- `anchor_lt_facts_ids`
- `lt_facts_ids`
- `attachments_ids`

The contract explicitly requires exact existing IDs and `anchor_lt_facts_ids` as a subset of `lt_facts_ids`.

### Legacy

Old key/value bodies and `<SAVE_DELAYED_MEMORY_CONTENT>` may still be normalized by compatibility code/data history but must not be documented as the preferred form.

---

## 7. Active Memory transition

### Current model-facing contract

`SAVE_ACTIVE_MEMORY` version 5 creates or updates Active Memory:

```json
{"conditions":"CONDITIONS","custom_field_name":"VALUE"}
```

When `id` is present, the same contract updates the existing record:

```json
{"id":"AM-abcdef","conditions":"NEW CONDITIONS","existing_custom_field":"NEW_VALUE"}
```

The create parser now treats custom fields as explicit JSON structure only. A non-JSON body is preserved as the complete `conditions` value; parenthesized prose such as `(date: tomorrow)` is no longer reinterpreted as a custom field. JSON custom fields are capped at three after normalized duplicate keys use last-value-wins behavior.

The model-facing create/update boundary is now one paired `<SAVE_ACTIVE_MEMORY>...</SAVE_ACTIVE_MEMORY>` block. Root `id` switches the action into update mode; without `id`, it creates. Update fields stay flat at the JSON root. `conditions` can always be updated; other keys must be exact custom fields already declared on the target record.

Only the flat JSON shape shown above is accepted for Active Memory updates. Old `UPDATE_ACTIVE_MEMORY` payload shapes and old six-character IDs are rejected.

### Current internal representation

Active records are still stored/transported in a string-oriented record format with metadata suffixes. Prompt assembly refreshes metadata, removes paused items, and may rank the prompt view by lexical/context relevance.

### Risk

Do not “finish the migration” by replacing the internal storage shape in an unrelated task. The structured JSON action boundary is settled separately from the string-oriented internal record representation; storage migration needs its own end-to-end plan.

---

## 8. Prompt assembly — verified order

Current `build_brain_context()` order is intentionally structured. Important anchors:

- ordinary turns put `RUNTIME_SETTINGS` first when non-empty, then trusted runtime XML; the former user-waiting and separate context-usage prompt blocks are removed;
- the legacy 50% previous-answer warning and resource-count concern builder are removed;
- tool results precede Session Actions, attached-file/Delayed inventories, and the always-present `SKILLS_LIST`; loaded skill bodies are part of the tool-results projection rather than a second independent prompt section;
- the runtime-context group orders Active Memory before FRAME, and moves `<PREVIOUS_CHAT_MESSAGES>` to the tail after identity; loaded Delayed/L-T follow later in the same group;
- ordinary `<PREVIOUS_CHAT_MESSAGES>` keeps the newest five pairs without per-message character cropping; physical newlines become literal `\n` and XML-sensitive characters are escaped;
- ordinary initial turns include previous successful reasoning in `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>`; blocks over 2000 characters keep the first and last 25% with an explicit middle-cut marker;
- archived restore priming begins with `<MANDATORY_SYSTEM_NOTIFICATION>`; inherited dialogue and reasoning follow identity, before tool results;
- action/recovery follow-ups start with their notification and failure/recovery/action history; the base prompt ends in identity, dialogue, carried reasoning and tool results without duplicate continuity blocks;
- action contracts remain present even on restore ticks, subject to effective capability filtering;
- `WEB_SEARCH` disappears when `settings.CAN_SEARCH` is false; `DEEP_RESEARCH` remains available but cannot execute worker-requested web queries;
- loop rules precede identity; identity is followed by dialogue, reasoning evidence and tool results.

Any prompt-order change can alter behavior materially. Do not reorder sections for aesthetics.

---

## 9. Bootstrap / archived restore — verified behavior

### 9.1 Server-owned bootstrap and reconnect (D057, 2026-09-26)

Normal connection sends an empty `session_bootstrap` request. The server selects the newest surviving real USER archive, ignoring every browser snapshot field, timestamp and owner ID. An explicit archive checkout sends only `archived_session_restore` and `source_session_id`; the server rereads that archive. Read errors are surfaced, never used as permission to import browser state.

The existing archive builder combines USER/JIN rows and reasoning, structured action history, server `session_checkpoint` events and later cleanup/tool-result events. Latest `frames/<prefix>_frame_<N>.txt` wins over the earlier prompt's FRAME. New frame files embed the complete snapshot metadata beside the readable FRAME; legacy files retain their text fallback. Explicit empty FRAME and tool inventories stay empty. A single server `bootstrap_state` response feeds the existing UI projection, followed by the established FRAME/actions/chat-tail events and hidden continuation tick.

`RuntimeContext` remains the live owner. Soft reconnect with a surviving transport sends no browser state. After server restart, an already-open page reconnects silently: the server hydrates its exact session ID from disk (including anonymous audit logs) before accepting work, without emitting bootstrap state/chat/FRAME replacements or starting a hidden Brain turn. Missing logs do not select another room. New-page bootstrap remains unchanged. `runtime_resume` snapshots are ignored. Active/Delayed/Facts/L-T remain disk-profile-owned; automatic legacy browser Facts imports are disabled.

Normal cognitive caches use page RAM, with the existing ephemeral FRAME record cleared on every page load. The `jin.sessionCheckpoint.v2` and older durable cognitive records are retired and removed on startup, without migrating their contents. UI preferences remain in localStorage. An in-page checkpoint API remains for existing projection callers; it cannot become a reload source.

### 9.2 Lifecycle, clear and disk persistence

D049 remains unchanged: greeting-only tabs are not saved continuation sessions; a real USER send qualifies immediately, including interrupted USER-only/action-only turns. Latest-source selection and explicit archive restore retain their existing separate semantics. Dialogue/reasoning keep original timestamps and the five-USER-move bound.

The transport archives the same server `session_snapshot` projection it emits, only after a session log exists. New tool results are recorded at the canonical tool-result writer; cleanup events preserve the exact remaining inventory and monotonic tool ID sequence. FRAME keeps its existing deferred writer. None of these writers can recreate a physically deleted materialized archive.

Session CLEAR writes an atomic `logs/.continuation-cleared.json` barrier of USER row counts, without deleting archives. Later passive output, room updates or other tabs cannot lift the barrier. A newly logged USER row can. This avoids timestamp precision races and keeps explicit archive checkout available.

### 9.5 Normal bootstrap chat tail

The backend emits at most five newest real USER moves from `runtime_recent_turns`, with JIN, reasoning, and original timestamps where available. The browser rebuilds them through existing chat primitives, strips synthetic attached-context boilerplate from USER display, keeps USER-only moves without an empty BR bubble, appends the current date/session divider, and activates the live viewport at that divider. Explicit archived restore suppresses this duplicate normal-bootstrap tail.

### 9.6 Archived restore

Current restore code deliberately prevents the “double apply” class of bugs.

Verified behavior:

- archived visible dialogue is rebuilt from logs;
- the newest five real USER moves are used for the restore context in chronological order, with empty JIN retained where the turn was interrupted/action-only;
- no separate restore-reasoning dump is generated; the hidden bootstrap prompt instead carries the prior reasoning through `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>` after `<PREVIOUS_CHAT_MESSAGES>` in the tail after identity;
- loaded Delayed IDs and attached files are staged; room/avatar state is restored by bootstrap and is not replayed as runtime actions;
- restore Brain response occurs before normal resource reactivation;
- `BrainNode.replay_session_restore_resource_actions()` consumes the staged Delayed/file envelope and applies only those resources through the real action dispatcher;
- WebSocket tail only clears defensive state and explicitly warns against mutating/emitting resource state a second time.

This is a strong architectural clue for future restore fixes: find duplicate writers before adding another apply.

---

## 10. L-T / Facts Memory current path

### Facts Memory

Browser runtime storage creates per-session facts-memory candidate buckets from persisted runtime snapshots and synchronizes them to backend with `facts_memory_store_sync`.

### L-T

L-T has a real staged pipeline with:

- pending candidate collection;
- extraction;
- merge/rebase;
- validation/recovery/backoff;
- explicit-edit protection;
- report-reference remapping;
- archive/anchor logic;
- delete/restore;
- file-store persistence.

### L-T UI projection

Ordinary L-T rows display a 50-character value preview. When a fact is bubbled because it was referenced, explicitly cited from reasoning, or loaded into context, the row displays the complete value with no preview truncation. This does not mutate or reorder the stored fact; it is a visibility rule for surfaced evidence.

The default L-T panel view excludes facts absorbed by Delayed reports unless they are currently context-loaded. Clicking the L-T count toggles `show all` / `show active`; the all view uses the same normal numeric fact sorting rather than appending hidden rows at the bottom. A fact linked to a Delayed report renders its number as the existing report-link control and opens that report modal. Anchor facts remain visible rather than being classified as absorbed.

### Recall / mention decay

Canonical L-T facts carry `mention_count` and `last_mentioned_at`. One valid fact reference from JIN reasoning or visible output increments the canonical fact at most once per turn. The timestamp is persisted and exposed in hover metadata. A background log backfill repairs historical mention dates without overwriting a newer live mention.

Brain context uses the full fact value while its last mention/update/create timestamp is newer than 24 hours. Once stale, each sentence is compacted to at most 100 characters. Referencing the fact refreshes `last_mentioned_at`, so subsequent turns can receive the full value again.

### Scheduling

L-T background work is started by browser `lt_memory_idle_tick`. Server refuses to begin it while a foreground task is active or the pending request queue is non-empty.

This is the current performance/ordering contract. Do not move L-T onto every foreground turn to “make facts faster” without proving latency and ordering behavior.

---

## 11. Memory Attention status

The metabolism subsystem has been removed. `runtime/memory_attention.py` retains only prompt-local retrieval behavior:

- Active lexical/context relevance;
- Delayed bubble matching;
- L-T 1–3 fact focus.

There is no metabolic SERVICE pass, homeostat, learned association state, temperature modulation, Brain instruction, FRAME strength bias, significance persistence, bootstrap chemistry, logger trace, or avatar chemistry. Historical significance fields are discarded while normalizing old Active/Facts/L-T records.

### Not proven

The older concept of a full nightly self-review cycle that reads cropped reasoning/context and emits a morning cleanup report is **not proven complete** by this snapshot. Do not describe it as finished architecture without finding the actual scheduler/storage/report path; Memory Attention is unrelated to that cycle.

---

## 12. Anonymous room status

Anonymous mode is now explicit JIN behavior and does not attempt to detect Chrome/Incognito/private browsing. Long-pressing the avatar opens a fresh anonymous room with a generated `_anon` session id.

Backend `runtime/anonymous_mode.py` currently:

- marks unrelated runtime persistent side effects restricted;
- stores Active, Delayed, Facts Memory candidates, and L-T in the normal memory folders with `_anon.json` filenames;
- shares those anonymous memory files across concurrently open anonymous rooms and deletes them after the last anonymous room closes;
- allows `UPDATE_LT_FACTS` and `SAVE_DELAYED_MEMORY` only inside that anonymous file-backed profile;
- preserves Delayed reports and loaded bodies on a soft WebSocket reconnect;
- blocks persistent asset-write actions;
- prevents anonymous FRAME pending journals under `memory/frame`;
- keeps chat/reasoning logging under ordinary `logs/` with the `_anon` session suffix.

Browser `sessionStorage` still carries tab-local anonymous room/bootstrap state, but Active/L-T/Delayed/Facts Memory are server file-owned and browser values are projections. The normal profile's durable memory is never used to seed an anonymous room. Normal restore/bootstrap and L-T log-freshness scans skip `_anon` logs.

---

## 13. UI / visual state mismatches and active decisions

### 13.1 Header reveal timing

Current `ui/static/js/header-autohide.js`:

```text
SHOW_DELAY_MS = 333
HIDE_DELAY_MS = 1000
```

Owner intent from the latest UX pass was approximately 250 ms reveal and 1 s hide.

**State:** implementation/product-intent mismatch. Do not fix incidentally.

### 13.2 FRAME naming

The live runtime-memory view is `FRAME`, and FRAME is the canonical documentation/product/implementation name for this live state. FRAME integration detects the current user-message language for values, while keys remain structural English `snake_case`.

The panel always shows `FRAME`, `ACTIVE`, `DELAYED`, `L-T`, and `FILES`, even when a non-FRAME view is empty. The shared counter moves below the selected tab; FRAME keeps the existing snapshot arrows while the other tabs show only their record count. The temporary unprocessed-facts projection is not exposed as a tab.

### 13.3 Visual reuse

Hard owner rule remains active: reuse existing visual primitives; no invented highlight colors/glows/badges/strips unless explicitly approved.

### 13.4 Loaded vs referenced highlight

Strong loaded-context highlighting and weak ID-reference highlighting are separate semantics. Opening a modal is not a context load. This area has had regressions and must be traced through both panel state and avatar state.

### 13.5 Session Actions logger

The compact logger now shows the most recent five actions in chronological order while retaining their original history numbering; `FULL` uses the existing attached-files header/button visual primitive rather than a new style. JIN_COLOR entries depend on `parts[].colors` for the color square and hex hover, so that metadata is part of the bootstrap contract, not disposable presentation data.

Validator/reasoning-loop and context/output-limit entries are emitted immediately when the interruption is detected, before automatic recovery/follow-up. `context_overflow` is included in context-limit finish reasons. Provider/preflight overflow errors and native `chat.end`/`stop` with a full provider-reported context now use that path too; context/output-limit history entries remain separate rows. Context overflow uses `FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE` to request immediate targeted `CLEAN_TOOL_RESULTS`, without the ordinary deep-reasoning follow-up notice or its last-action/result suffix. Output-only limits retain their existing continuation. Recovery still obeys the workflow follow-up budget; no tool results are automatically deleted, and a provider must accept the recovery prompt for model-directed cleanup to run. This timing is intentional: the logger should reflect the loop while it is happening, not only after the final JIN response.

### 13.6 Runtime action hover stability

Runtime-action bubbles persist their detail in DOM dataset state. Counter-only updates reuse the existing detail/title instead of clearing it, so an aggregate count refresh cannot erase hover information.

### 13.7 Interaction fixes landed in this snapshot

- the latest manually chosen reasoning collapsed/expanded preference is persisted and reused by new reasoning blocks;
- live-turn top-lock releases once the user turn reaches the viewport bottom, after which normal overflow autoscroll can resume;
- clicking usable form padding focuses the JIN user input;
- answer-rating implementation remains in the client but is release-gated off; the old invisible bubble double-click/hold utility surface has been removed, and completed assistant output instead exposes an explicit `Copy all` button under the avatar/message host;
- Win95 theme localStorage reads/writes are guarded so restricted storage contexts do not break theme switching.
- Win95 renders disabled memory-sequence labels/arrows as flat status text and keeps the avatar progress border square; these are theme-specific projections, not new runtime states.

### 13.8 Chat skins and avatar context pressure

`win95-theme.js` exposes three bubble skins: `dark`, `light`, and `bamboo`. Normal theme defaults to dark and Win95 to light. `jin_bubble_skin` stores the current choice; `jin_bubble_skin_pinned` means the user's explicit non-default choice survives a theme switch. The Context/trace settings UI renders the same three options.

`runtime-panel.js` synchronizes the Brain context meter into `--jin-context-pressure-color` and `--jin-context-pressure-percent`. Static scaffold circles do not rotate; their stroke and the ray stroke use the pressure color. Sixteen rays breathe to zero on a 30-second cycle. Pressure selects roughly 3..7 stronger rays and raises their maximum unmultiplied opacity from 0.10 at empty context to 0.70 at full context. The center toggle fades scaffold, runtime/memory rings, file ring/dots, and center rings; after the 420 ms fade the hidden layers enter `is-memory-layers-dormant`, which removes them from display and disables their orbit/reasoning animations. The center light remains visible.

### 13.9 Direct memory editing

Double-clicking a FRAME, Active, or L-T row converts the existing details tooltip into a fixed editor rather than opening a separate styling primitive. Only values are editable. FRAME accepts edits only on the newest snapshot; Active edits conditions/value while preserving custom fields, pause status, IDs, and other metadata; L-T edits only the durable fact value and preserves identity/provenance. Keys are never editable.

Editor drafts are page-local. The checkmark sends `memory_value_edit` with `expected_value`; conflicting/stale writes are rejected without discarding the draft, and FRAME writes are additionally rejected while the live FRAME/foreground writer is busy. FRAME row deletion uses the same busy guard; because the browser applies long-hold deletion optimistically, a rejected delete immediately re-emits the authoritative latest FRAME snapshot. Active edits stay writable during Brain/FRAME work because they mutate the independent `active_memory_records` store. The rollback arrow restores the last acknowledged value. Active and L-T successful edits create/update `updated_at` immediately in the open tooltip. Active pause/resume panel writes synchronize `active_memory_store_sync` before the local changed event so a later edit cannot revive stale pause state.

### 13.10 Composer attachment chips

Pinned files attached to the outgoing message are rendered immediately to the left of the input as compact chips using the existing attachment preview primitive. New chips animate in through the established composer style. Click opens preview; hold detaches/unpins the file from the outgoing context. The persistent file remains in the library, and attaching/detaching no longer expands Console as a side effect.

### 13.11 Delayed/L-T inspection and Live Avatar scaling

Delayed panel rows now expose the shared floating detail card with title/summary, creation time, tags, report ID, anchor/fact IDs, and a body preview capped at 200 characters. Unpinning a report produces the shared `memory_unpinned` logger card/state rather than only changing the panel.

L-T merge Apply/Show inspection prefers the structured `lt_merge_applied.operation_details` trace and renders per-operation update/create/merge/ignore rows with token-level diffs; legacy text parsing remains fallback compatibility. Live Avatar L-T facts are split into lanes of at most 100 facts, with additional outer rings as needed. Active Memory is positioned outside the outermost L-T ring but inside the file ring. Hovering a memory row reuses the avatar memory-row zoom/highlight state.

### 13.12 Runtime model status/switch

The BRAIN/SERVICE status modal reads role-specific LM Studio metadata. Where the role is available, its model field opens the model picker; selection POSTs the model plus remembered load configuration to `/api/runtime-model/switch`, then reconciles from `/api/status`. This switches the physical model backing the role and does not change the Brain-first routing invariant.

### 13.13 Normal bootstrap tail

Normal bootstrap renders the inherited five-USER-move tail above a date-labelled current-session divider and places the live viewport at the divider. Saved reasoning is rendered through the existing reasoning bubble path. A USER-only interrupted/action-only move remains visible without a blank BR bubble. Archived restore has its own renderer and blocks this path.

### 13.14 JIN color projection

JIN visual-action chat bubbles are enabled in this snapshot (`ENABLE_JIN_VISUAL_ACTION_BUBBLES=true`). Each applied marker gets its own display ID/bubble; counter-only telemetry does not collapse markers into one aggregate bubble. Parsing, execution, avatar updates, raw action logging, and Session Actions remain live regardless of this UI projection flag.

Avatar center and scene tint now share one transition duration variable set. First bootstrap color uses 2000 ms once; all later/live color changes use 333 ms. There is no center-color queue, secondary bootstrap tint shift, or separate client color resolver in this snapshot.

### 13.15 MCP runtime projection

Session Actions renders `CALL_MCP` identity inline as `skill / tool` instead of hiding the useful target in title-hover metadata. Runtime bubbles retain the parsed request, result, and raw payload. Generic MCP calls open the structured MCP trace modal with fielded arguments/result data; `get_viewport_screenshot` binds the returned hydrated image to the shared attachment hover/click preview instead of inventing a second image viewer.

---

## 14. Verification status for this exact snapshot

The 2026-10-01 documentation sync uses `jin_core(20261001-090403).zip` as the source baseline. The audit traced the live action registry/dispatcher/contracts, launcher modes, disk bootstrap/restore ownership, FRAME session titles, LOGS list/preview/live-update/delete behavior, and current browser projection boundaries. Historical verification notes below this numbered current-state section remain dated history and must not be read as the status of this snapshot.

Repository-wide verification for this exact snapshot is green: `python -m tests.run_unittest` ran **1386 tests in 19.467s**, with **OK (skipped=9)**. The earlier discovery blocker around the removed visual-sequence collector is no longer present; `tests/runtime_actions/test_jin_color_bootstrap_persistence.py` now targets `utils.actions.jin_visual_actions`.

The browser-client aggregate command was also attempted in the documentation environment, but Node Playwright/Edge integration is unavailable there, so `python -m tests.run_browser_client_tests` exits with the harness dependency message rather than exercising browser tests. Do not treat that as a browser green or a product failure.

---

## 15. Documentation status

As of this snapshot, the documentation set has been synchronized with the production architecture:

- root `README.md` describes FRAME/L-T/Active/Delayed/Files plus the LOGS archive projection instead of the old numbered four-layer model;
- README model-role/setup/configuration text describes Brain as the only foreground route and Service as optional/dedicated background execution with Brain fallback;
- `AGENTS.md` records the same routing invariant and explicitly classifies old `USE_SERVICE_AS_BRAIN` / archived Service labels as compatibility;
- `docs/JIN_ARCHITECTURE.md`, `docs/JIN_DECISIONS.md`, and this file use the 2026-10-01 inspected source as the Brain-first/disk-bootstrap/FRAME/L-T baseline and include current LOGS/session-title behavior alongside the action, follow-up, MCP, memory-edit, recall, L-T-view, and attachment contracts.

There is no root `ARCHITECTURE.md` in the inspected archive. `docs/JIN_ARCHITECTURE.md` is the canonical architecture document.

---

## 16. Repository-index caveat

Search/index output is navigation evidence, not existence evidence. The inspected archive itself is authoritative for whether a production module is present; this matters especially for removed L2/L3 paths that may remain in stale indexes or historical tests.

---

## 17. Patch-scope / working-tree caveat

The supplied snapshot does not include `.git`, so repository dirty status cannot be reconstructed from the archive. Treat any pre-existing files or local changes in a real checkout as owner-controlled and do not overwrite or “clean” them unless the task explicitly includes that scope.

---

## 17.1 Self-fork instances — 2026-10-13

The current runtime exposes paired `CREATE_JIN_INSTANCES` and `FINISH_SUBTASK`
contracts. A validated group runs sequentially inside the existing Brain
follow-up loop, uses authoritative server IDs, records each finish as an
ordinary action/tool result, disables nesting, and returns once to the parent.
`JIN_MAX_INSTANCES` defaults to 32. Children are explicitly instructed to use
the existing `CLEAN_TOOL_RESULTS` action to remove obsolete predecessor results
while preserving skills and evidence needed later. No separate window, agent
framework, browser-owned queue, or FRAME writer was added.

Follow-up audit correction (2026-10-13): ordinary/recovery child ticks now keep
their assignment and 24-hour L-T projection; the parent regains unfiltered L-T
and its own reasoning/dialogue state. Follow-up exhaustion and repeated malformed
output terminalize unfinished work before the parent final tick. Stop restores
parent state again after the cancelled stream's finalizer. CREATE/FINISH bypass
tool-result reuse, so another group with identical conditions executes afresh.
Strict JSON type validation rejects floating/bool IDs and non-string conditions
or finish reasons. Server-authoritative original_conditions remains intentional.

Verification: 211 targeted tests passed (instance flow, Brain follow-ups,
action-result reuse, malformed recovery, stream boundaries/lifecycle, and L-T
context/budget). Python compilation and scoped diff whitespace checks passed.
The full suite and a live provider run were not performed for this correction.

---

## 18. Open / known-unknown items

Do not present these as settled without fresh code evidence:

- whether the full night self-review concept is implemented outside the inspected paths;
- which remaining L2/L3-named compatibility fields/readers are still required for real historical data;
- when stale tests that directly mutate `config.USE_SERVICE_AS_BRAIN` or expect `SAVE_SESSION` should be migrated to the Brain-first/checkpoint architecture;
- migrate `tests/runtime_actions/test_jin_color_bootstrap_persistence.py` away from the removed `jin_visual_sequence_actions` collector so repository-wide test discovery can run again;
- final intended internal storage format for Active Memory if the current string-record representation is ever migrated;
- whether reveal debounce should now be restored from 333 ms to the earlier 250 ms preference;
- final canonical list of supported noncanonical action marker aliases after compatibility cleanup;
- which stale tests are still intentional compatibility coverage versus obsolete pre-Brain-first/pre-checkpoint expectations;
- whether every less-common linked-highlight path outside the newly verified L-T/report and Active pause/edit flows is synchronized between panel, prompt-loaded state, and avatar.

When one of these becomes the task, investigate first and record the resolved decision in `JIN_DECISIONS.md`.

---

## 19. Recommended near-term cleanup order

When the owner explicitly asks for legacy cleanup:

1. migrate stale tests away from direct `USE_SERVICE_AS_BRAIN` and old `SAVE_SESSION` assumptions;
2. audit the historical `RUNTIME_MODE=SERVICE` / archived `role=service` readers against real old archives before deleting them;
3. remove the logger's old `[SERVICE]` model-output presentation only after archive/log compatibility is proven unnecessary;
4. audit L2/L3-named UI log filters/comments and pre-L3 storage migration paths against real persisted data;
5. only then delete compatibility adapters/readers that are proven unused.

Do not combine that cleanup with unrelated runtime behavior patches.

---

## Malformed-action recovery — 2026-09-10

Three targeted envelope masks feed the shared failure-follow-up mechanism. `MALFORMED_ACTION` is internal telemetry, not a new model-invokable contract. Its result persists the detected name and original payload; ordered notifications at the top of the next prompt carry the target contract schema. Each occurrence remains independently visible.

Current 2026-09-24 control semantics supersede the original unlimited-repair note: one malformed repair tick is allowed outside the ordinary `BRAIN_MAX_FOLLOWUPS` budget. If the repair output is malformed again, the sequence stops and runs one final non-executable Brain response tick with runtime actions disabled. Positive ordinary follow-up limits use that same final-response pattern when exhausted; `BRAIN_MAX_FOLLOWUPS=0` means the ordinary workflow is unlimited.

Thirteen contracts previously had empty `schema` arrays despite the documented schema invariant. Their existing canonical syntax was moved/copied into those arrays so recovery can use the JSON field for every registered action. No action payload semantics or feature flags changed.


## Owner bootstrap lifecycle correction — 2026-09-11

D049 records the four owner-approved scenarios. The rejected generic JIN-only
bootstrap-rendering workaround has been removed. Normal restore continues to
use actual USER-owned turns and existing per-session boundaries.

Cancelled startup packets are checked again after FRAME waiting and at
process_message entry; a real USER cancels unfinished startup before queueing.
A pending USER stopped before Brain uses the same interrupted USER commit path,
so it is not silently discarded. Greeting-only checkpoint writes are rejected
also when the normal browser profile has no previous checkpoint.

The owner supplied MHTML proving the last visible USER/JIN/reasoning pair in
session 7e91148a-2077-454d-a3ec-be6028cd6aec. Its misowned JIN 138 text/reasoning
reference was moved into the existing empty JIN 139 completion, leaving the
USER and its completion timestamp intact. This is a one-time evidence-based
archive repair, not a general text-matching or timestamp-reordering heuristic.
The original log and repair details are in artifacts/bootstrap-repair-2026-09-11.
The older 19:35 session is preserved, as shown in the supplied MHTML.

Verification covers all four lifecycle scenarios, cancelled startup while
queued/running, USER-only cancellation, clean/existing browser checkpoints,
serialized archive enrichment and the real chat DOM/reasoning toggle. The
current source uses the shared five-pair budget; the old three-pair documentation
mismatch was removed by the 2026-09-17 documentation sync.

Focused verification: 60 unittest cases pass, both JavaScript lifecycle/boundary
suites pass, and Python/JS syntax plus git diff --check pass. Of 13 additional
function-style bootstrap/checkpoint checks, 12 pass; the raw-color metadata
check fails with KeyError(colors), reproduced against HEAD before these changes.

## Physical archive deletion correction — 2026-09-11

The owner confirmed two distinct photo sends interrupted by LM Studio crashes,
then physical removal of today's logs followed by a server/browser restart.
Normal bootstrap previously returned the browser payload unchanged when its
archive was missing. The persistent localStorage replica therefore restored
both deleted USER rows. New startup responses then created fresh date/session
directories (the inspected 14:33/14:34 JSONL files contain no USER rows).

Missing archives now invalidate the whole normal-bootstrap replica before
hydration; the newest surviving real USER archive wins regardless of the stale
replica's timestamp. With none surviving the bootstrap is empty. Startup logs
and reasoning stay in RAM until a real USER flushes them in order. Late writers
cannot recreate their deleted materialized session directory. This supersedes
the older test expectation that cancelled startup reasoning creates disk files;
the reasoning remains available in RAM until real activity makes it saveable.

Verification: 65 targeted unittest cases pass, including physical deletion of
two USER-only photo turns, serialized reload, repeated bootstrap, all four D049
scenarios, and late-write protection in normal/anonymous mode. Both JS lifecycle
and boundary suites, Python compilation and git diff --check pass. The additional
13 function-style checks retain the one previously established raw-color
KeyError(colors); 12 pass. A real-browser harness using the actual chat scripts
and existing archive selected Sept 10's 7e91148a session, displayed its USER/JIN
pair and reasoning before the 19:38 divider, contained no deleted photo rows,
and kept 14 DOM children after replay (14 -> 14). The running JIN server itself
was not restarted; it must load the changed Python code on restart.

## Transport lifecycle correction — 2026-09-15

Explicit page departure now retires its runtime; unexplained disconnects have
a 600-second reconnect grace. A same-origin close beacon names both client id
and transport epoch, so a stale beacon cannot stop an anonymous reload/replacement
that reused the id. Retirement clears the scheduler's cached L-T context and
cancels guard/background work. Scheduler iterations release old local references
before waiting with an empty store. RuntimeStream propagates cancellation for
retiring transports instead of returning into the ordinary completed-turn tail.
USER-only interruption semantics remain.

Verification includes shortened-clock expiry, real Edge reload during streaming
and action-guard waiting, tab close, reconnect replay, BFCache/freeze preservation,
same-origin/epoch rejection, and garbage collection of the retired context while
the global L-T scheduler remains alive. Model output is mocked in browser tests;
they do not use personal memory or call providers.

## L-T backfill lost-update correction — 2026-09-15

Backfill previously read/repaired a snapshot on the event loop, then persisted
it via `asyncio.to_thread`. That worker could overwrite a successful deletion,
value edit, or live mention committed by another runtime. Each of those losses
was reproduced before the fix in an isolated file-store regression test.

Backfill now follows the other L-T writers: its latest-state read, repair and
write have no suspension point, and RAM publishes the repaired snapshot only
after persistence succeeds. Archive scanning stays off-thread. Six interleaving
tests cover changes during scanning and immediately after snapshot preparation,
including reload into a fresh context. This relies on the current single server
event loop; multiple processes sharing the profile would need separate locking.


## Disk bootstrap refactor — 2026-09-26

D057 supersedes the older browser-authority notes above. Cognitive browser persistence is now page-local and startup selectors are resolved from disk. The latest saved FRAME retains full metadata; server snapshots/tool results are archived through existing JSONL writers. Session CLEAR uses a disk USER-count barrier. Existing unrelated dirty action-dispatch files were not changed by this refactor.

During implementation, 85 targeted unittest cases, 20 targeted pytest cases and the migrated browser-storage unit test passed. Python compilation, JavaScript syntax and diff whitespace checks also passed before the final small cleanup. The Edge harness exercised poisoned storage, empty bootstrap requests and disk chat rendering, but its complete final run was stopped at the owner's request to skip further checks. No full-suite or final-browser green claim is made. Restart the backend and reload the page to activate the new protocol.

## FRAME session titles and LOGS archive projection — 2026-09-29

FRAME now owns one protected `session_title`, refreshed through the existing summarizer on every FRAME cycle, including hidden bootstrap. The LOGS tab lists USER-owned non-anonymous archives by date and reuses explicit archived restore in a new tab. Latest committed FRAME wins for list titles; legacy untitled sessions display their session ID, which is also the hover text for every title row.

LOGS uses the common memory lazy-render pipeline with 20-row batches. The full index is fetched once per page, while successful disk commits publish `archived_session_update` so the current session can be inserted or retitled live; a per-session summary request reconciles a missed update without reloading the historical list. Session dialogue is fetched only while a row is hovered, shown in the existing memory hover-card as up to five newest USER-owned turns, and discarded on mouse leave.

Short-click restores the session in a new tab. A 1500 ms hold reuses the shared fade/delete interaction and calls the disk DELETE endpoint. Only indexed USER-owned, non-anonymous archive directories are eligible; symlink escapes are rejected, an empty date directory is removed only when truly empty, and the live writer will not recreate a physically deleted session from a still-open runtime.

## Linked-folder attachments and writes — 2026-10-09

Added ATTACH_FILES_BY_PATH using the existing parser/dispatcher/follow-up, image payload, tool-result and attachment preview paths. Temporary path sets replace each other without importing files into assets/files; disk restore retains history but unloads bytes. Explicit file_manager attachment selectors extend create_asset_file/append_asset_file/preview_file to current linked folders, preserving overwrite and anonymous-mode rules. This owner-requested extension supersedes the former read-only linked-folder restriction.

The dataset skill in this checkout is assets/skills/dataset_captioning.md, not the directory-style JIN_SKILL.md path cited in the task; the existing skill was updated in place.

Directory Link skill: `assets/skills/directory_link.txt` replaces the former `project.txt`. When the user links a real local folder, prompt assembly projects this skill automatically into `<TOOLS_RESULTS>`, and `<SKILLS_LIST>` marks it loaded. `project_tree`/`project_search` therefore work immediately without a `LOAD_SKILL` action; `project_read` continues to require `file_manager`. Implicit loading is recomputed from live folder links on every prompt/action and never persists as a synthetic tool result, so unlinking removes the skill. Unlinked JIN source-root access continues to require a manual directory_link load.

Attachment-result compaction: when a later model message executes
`ATTACH_FILE_CONTENT`, `ATTACH_FILE_BY_ID`, or `ATTACH_FILE_BY_PATH`, older
attachment Tool Results keep their `T*` identity and one-line outcome but lose
their detailed success/failure bodies. Results produced within the same model
message remain grouped and fully available, so files needed together must be
requested together. The compacted representation survives checkpoint/bootstrap.


## Surviving-page backend restart (2026-10-16)

An open room reconnects without clearing its DOM, replaying startup snapshots,
or starting a continuation model turn. If the backend lost its RuntimeContext,
it silently hydrates that exact room's disk archive before accepting new work,
including anonymous audit logs. It restores FRAME (including explicit empty
values and original timestamps), recent dialogue/reasoning, actions and tool
results; ordinary memory profiles keep their disk owners. The next USER request
therefore has prior context even though the page received no bootstrap replay.
Live server RAM is reused without disk rehydration. A missing/deleted room log
never falls back to another room or browser cognitive contents. Anonymous logs
remain excluded from normal bootstrap and explicit archive checkout. FRAME
numbering continues after the saved file number across repeated restarts.
New-page bootstrap and explicit archive checkout retain their existing behavior.
This corrects the earlier incomplete implementation which preserved only the UI
and left the restarted Brain without context; D057 disk authority is retained.

## Context maintenance warning (2026-10-16)

Brain preparation now prepends optional CONTEXT_MAINTENANCE after dynamic L-T
budgeting. Final estimates include warning text and image reserves. Shared
in-process threshold state covers ordinary turns, child-instance ticks and the
parent return; native preflight failure/abandoned preparation does not consume
a threshold. Empty visible results suppress it. Largest/oldest hints intersect
visible blocks with canonical removable tool IDs, excluding implicit skills.
The earlier choice to retain CONCERNS was superseded by its removal on 2026-10-25. Exact downward
boundary rearming follows the owner-approved 93 -> 85 -> 87 example. No action,
follow-up-budget, persistence or automatic cleanup mechanism was added.

Implementation files: `rules/runtime.py`, `utils/current_context_window.py`,
`utils/context/tool_results.py`, `runtime/runtime_context.py`, `runtime/client.py`,
`clients/brain_client.py`, `agent/nodes/brain.py`, `config.example.py`, and
`ui/static/js/logger/trace-modal.js`. Tests: `tests/test_context_maintenance.py`
and `tests/test_context_snapshot_tabs.js`. The architecture and decisions docs
record the request-boundary projection; legacy concerns generation is now removed.

Verification: 145 targeted Python tests passed across maintenance, current
window, L-T budget, overflow/follow-up continuity, result IDs/checkpoints,
instances, concerns, Brain/runtime client, and directory-link behavior. The
Edge DOM test passed for snapshot tabs, warning placement, counts, collapse,
settings, keyboard, reopening and narrow layout. Its stale result-age fixture
and missing offline Tailwind layout primitives were corrected; settings are
expanded before clicking the skin control. Python compilation, JS syntax and
scoped diff whitespace checks passed. Full `git diff --check` still reports
pre-existing whitespace in `tests/test_attach_file_by_id_client.js:12`, which
was not changed for maintenance. No full-suite/live-provider claim is made.


## Unified file attachment (2026-10-17)

The owner superseded the earlier BY_ID/BY_PATH marker design. Only ATTACH_FILE_CONTENT remains a model-facing attachment marker; it accepts comma-separated IDs, linked image paths, and existing text paths/ranges. ASSET_ACTION adds case-insensitive ATTACH_FILE_BY_ID and ATTACH_FILE_BY_PATH whole-file operations behind file_manager. The two old marker contracts are removed, not aliased. Internal result names and archived readers remain for disk/UI continuity. The shared loader retains confinement, size, pin, anonymous, Stop and restore behavior. Asset failures preserve their original payload before tool-result copying.

Verification: 103 targeted unittest cases passed (unified attachments, ID/path loaders, project windows, asset actions, lifecycle, streaming and malformed recovery). Both existing Edge attachment DOM suites passed, including preview/modal and failure/counter behavior. Python syntax, JSON parsing and scoped diff whitespace checks passed. Full diff checking still reports the pre-existing whitespace in tests/test_attach_file_by_id_client.js:12. No live-provider or full-suite green claim; backend restart is required to load the new contracts/runtime.

## Ephemeral child Active Memory (2026-10-19)

Owner-requested revision to D060: children read shared Active/Delayed/L-T context,
but model actions cannot mutate shared memory. They may create, update or delete
only their own temporary Active records. Runtime assigns `owner_subtask_agent_id`,
`SUB-AM-xxxxxx` IDs, and `subN_active_memory_M` labels; ownership is reserved metadata,
not a custom field. Main IDs remain `AM-xxxxxx`. ACTIVE renders child rows below
main rows with existing row/hover/edit primitives. Existing child 24-hour L-T
read projection remains unchanged.

Validated FINISH commits deletion before transitioning; invalid FINISH leaves
memory intact and failed persistence does not report success. Stop, follow-up
exhaustion and terminal request exit clean up as well. Follow-up/recovery ticks
retain the records. Profile reads reap orphan owners after restart, while checking
all live contexts in the same normal/anonymous profile. Scratchpad records/results
are removed from live projections; their tool results are excluded from checkpoint,
raw-event and prompt-based reload paths. Other tool results and finish_reason remain.
Actions after FINISH in the same response are rejected until the next instance tick.
This uses the existing single-server profile synchronization, not cross-process locks.

Implementation scope: `utils/subtask_memory.py`, instance actions, Active normalization,
ID/parser/dispatcher/reuse paths, tool-result serialization and restore, memory profile,
Brain prompt projection, terminal request/Stop integration, shared UI ID helpers and
ACTIVE row presentation. Canonical storage keys remain `active_memory_N`; labels are
presentation metadata. Contracts and D060 were updated for the new child permissions.

Verification: 32 instance tests (including disk lifecycle, failed deletion, Stop,
other live contexts, anonymous profile, ownership injection, split markers, recovery,
and serialize/reload result filtering); 310 memory tests; 61 bootstrap tests;
4 checkpoint tests; 27 archive-restore tests; 7 streaming-latency tests; 9 malformed
action tests. These suites overlap. Python compilation and scoped `git diff --check`
passed. Real headless Edge DOM test verifies SUB-AM identity, label, main-first order,
hover and removal. No live model/provider run was performed.

Broader action regression run: 197 tests, 2 failures and 1 error in existing adjacent
work: attachment marker metadata expectation, attachment capability enumeration,
and the reaction test's prepared-window stub missing `maintenance_state`. These
unrelated paths were not changed to make the suite green. Repository-wide diff check
also reports pre-existing trailing whitespace in `tests/test_attach_file_by_id_client.js`.


## Anonymous asset writes — 2026-10-19

Owner revision: ASSET_ACTION writes are now allowed in anonymous rooms, including
create/append in assets and explicitly linked folders. Dispatcher admission and
linked-folder file_manager checks share the same action restriction policy.
Skill, confinement and overwrite checks remain. Shadow contexts remain restricted;
anonymous memory isolation and other non-asset write restrictions are unchanged.
This supersedes earlier anonymous asset-write restriction notes above.


## Autonomous heartbeat — 2026-10-20

D062 adds per-room idle Brain ticks through the existing serialized WebSocket
queue. First deadline is 300 seconds of page inactivity plus the interval;
subsequent idle deadlines use only the interval after the entire activity chain
and pending FRAME finish. Page activity resets waiting, never cancels accepted
work. Stop remains the cancellation control. Empty/anonymous tabs participate;
explicit page retirement releases timers and disconnected rooms cannot start.

SET_HEARTBEAT_TICK_SPEED is a permanent paired-XML/JSON contract, finite seconds
>=60, default 600. It is never satisfied by result-cache reuse. RuntimeContext
owns the value; disk checkpoint/action/heartbeat records restore it per room.
Only the initial heartbeat prompt receives HEARTBEAT_TICK_MESSAGE, including
when maintenance is present; ordinary action/recovery and guard retries omit it.

This supersedes earlier USER-only archive ownership text: first visible output
or attempted ACTION promotes a marked heartbeat archive through the existing
deferred logger. Reasoning-only ticks and greeting-only tabs remain unsaved.
No USER row is invented. Bootstrap/LOGS preserve standalone JIN moves and
intervals, including action-only ownership. Selection compares activity across
archive dates. CLEAR records unique heartbeat turns beside USER counts, so late
completion cannot lift it. Browser state remains non-authoritative.

Verification: 112 combined unittest cases passed across heartbeat, bootstrap,
disk authority, transport, instances and context maintenance; one additional
guard-retry notification test and 24 Brain-guard/client/follow-up tests passed.
All 13 function-style latest-session/atomicity checks also passed, run directly
with isolated temporary-directory fixtures because pytest is not installed.
Four JS suites passed: real Edge heartbeat DOM/activity and transport tests,
plus bootstrap lifecycle and boundary tests. Python compilation, JS parsing and
git diff whitespace checks passed. No live model/provider or full-suite claim.
Restart the backend and reload open JIN pages to load the implementation.

Final heartbeat check: Active Memory uses its real lifecycle timestamps on
heartbeat turns instead of reapplying the previous USER idle credit. The focused
normal-vs-heartbeat regression passes. Interrupted-heartbeat persistence checks
also pass after the error-cleanup guard. No provider calls were made.


## Recursive Nested Instances — part 1 (2026-10-21)

The owner's new task supersedes the old D060 nesting prohibition. This delivery
adds the RuntimeContext group stack and enables child CREATE through the existing
sequential Brain loop. FINISH resumes only the immediate parent; parent reasoning,
dialogue, recovery and follow-up budgets survive nested groups. Suspended memory
owners are protected against orphan cleanup. Nested completion Tool Results are
owned by the resumed parent. CREATE uses the existing transition barrier.

Stop, provider failure and terminal budget paths unwind all suspended frames.
JIN_MAX_INSTANCE_TICKS (default 256, positive) bounds the entire self-fork workflow,
even with unlimited ordinary follow-ups; there is no fixed depth limit.

Staged scope: relative Active Memory normalization is part 2, Tool Result
normalization is part 3, and full inheritance/integration is part 4. Until those
parts, ancestor temporary Active records are protected but not inherited as AM,
and ancestor temporary tool projections are parked until parent return. This is
not a claim that the final task's inheritance acceptance criteria are complete.
No new UI, durable memory system, model executor or dependency was introduced.

Verification of this staged delivery: 371 targeted tests, 367 passed, 3 failures
and 1 error. All 10 recursive-runtime tests, 35 existing instance tests and
4 subtask Tool Result tests passed. The four remaining cases were replayed
against saved pre-task source using a read-only import overlay and failed there
too: action capability enumeration (heartbeat/retired attachment names), malformed
notification prefix, DELETE_ACTIVE_MEMORY ID casing, and missing heartbeat payload
in the stream-latency fixture. These adjacent failures are not fixed by this patch.
Syntax/JSON validation and git diff --check pass. No live provider or UI changes;
the full repository suite was not run. Archive contains a task-only diff against
the exact dirty source snapshot, plus changed files and detailed test logs.

## Deep Research — 2026-10-21

The predecessor action was replaced without a parser or archive alias by
the canonical `DEEP_RESEARCH` action and `<DEEP_RESEARCH>...</DEEP_RESEARCH>`
marker. The old names are absent from current source, tests, UI identifiers and
documentation. The action is no longer defined as search-only: its coordinator
decomposes substantial investigations into independent service-model agents.
Each agent may analyze the supplied context and image attachments, request
bounded web searches when external evidence is useful, or create narrower child
tasks. The final service pass synthesizes findings, alternatives,
contradictions, changed understanding and remaining uncertainty into one report
for Brain.

`DEEP_RESEARCH` stays model-visible without a configured search provider. In
that state requested queries are suppressed and the agents continue with
context-only analysis; direct `WEB_SEARCH` retains the `settings.CAN_SEARCH`
gate. Multimodal worker requests reuse live turn/sequence image attachments and
service usage accounting uses the textual research sequence so token tracking
does not receive a multimodal list.

Verification: 44 focused research/search/marker/session/UI-contract tests and
3 explicit streaming-marker tests pass. Relevant Python compilation, contract
JSON parsing, JavaScript syntax checks, the removed-name search and
`git diff --check` pass. No live model or search-provider call was performed.

## Telegram transport — 2026-10-23

Telegram now uses the existing loaded-skill ASSET_ACTION path for explicit
`telegram_send` delivery and one application-lifecycle Bot API long poller for
inbound private text/photos. Incoming requests select the most recently opened
connected non-anonymous tab and enter its existing serialized USER queue. The
UI receives the same USER bubble/attachment projection, while Files hydration,
Brain multimodal input and chat/session persistence remain canonical.

Inbound Telegram text is projected consistently to the UI, chat log, and Brain
inside `TELEGRAM_MESSAGE_INPUT`. Admission automatically loads the canonical
`telegram` skill into the selected room, retaining one normalized copy when it
was already loaded. The skill documents how Brain should handle that block.

Outbound `telegram_send` text is projected into the same JIN response as a
`TELEGRAM_MESSAGE_OUTPUT` block at the action marker's source position. A
successful send no longer consumes an automatic Brain follow-up; its action
bubble and Tool Result remain, and failures still use normal recovery.

2026-10-24 follow-up correction: the first implementation checked UI events
but Brain reads internal action events, and the legacy runtime_asset_results
branch still triggered a tick. Tool-result binding now carries the Telegram
outcome to the internal event; both asset-result collection and its consumed
offset exclude successful sends. A full Brain-sequence test using the real
dispatcher reproduced two calls before the fix and one afterwards; failures
and mixed batches still continue normally.

Photo albums are short-buffered by `media_group_id`, capped atomically at five,
and stored unpinned for their originating turn. Missing eligible tabs produce a
Telegram error reply. Authorization checks private `chat.type`, `chat.id`, and
`from.id`; the poller persists its accepted offset and uses a per-token process
lock. Telegram HTTP uses a dedicated untraced client so token-bearing URLs do
not enter runtime tracing. JIN output is not automatically sent back.

Verification: 163 targeted unittest cases passed across Telegram transport,
ASSET_ACTION/skills/follow-ups, attachments, heartbeat, bootstrap, reconnect,
soft restart and anonymous isolation. Python compilation, JavaScript syntax and
`git diff --check` pass. The configured token is absent from tracked files and
the local `.env` remains ignored. No live Telegram or model request was made.

## Prompt tail and CONCERNS removal (2026-10-25)

Ordinary, archive-priming and follow-up prompts now place identity immediately
before optional previous dialogue, optional carried reasoning evidence, and
TOOLS_RESULTS. Loop guidance precedes identity. Follow-up/restore notifications
remain at the front. The concerns builder and its counters are deleted; the
legacy reader only strips obsolete concern blocks from saved prompts.

Verification: 222 unique targeted tests passed using project-venv unittest,
including six function-style session-continuity tests run with FunctionTestCase.
Coverage includes prompt order, repeated follow-ups, restore, full recent-message
text, reasoning crop/suppression, action flows, project review, overflow and
independent context maintenance. One existing action-list expectation fails:
`test_agent_runtime_action_flags_follow_assembler_constants` expects standalone
ATTACH_FILE_BY_ID/BY_PATH and omits SET_HEARTBEAT_TICK_SPEED. Its assertion,
expected-list function, runtime flags and enabled-action selector are unchanged
from HEAD. Compilation and git diff --check passed. No live provider run or
full-suite green claim.


### Attachment cleanup lifecycle — owner update 2026-10-25

Each new attachment-bearing model message ages earlier attachment results and
successful `create_asset_file` / `append_asset_file` receipts once: first remove
the body and retain the tool ID plus outcome header, then remove that empty
header on the next attachment-bearing message. Multiple attaches in the same
message do not age results again. Failed writes and unrelated results retain
their existing lifetime. Cleanup persists the remaining tool inventory through
the existing disk checkpoint path. This replaces indefinite compact-header retention.
