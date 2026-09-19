# JIN Core Engine — Current State / Migration Notes

**Snapshot inspected:** `jin_core(20260917-184157).zip`<br>
**Inspection date:** 2026-09-17<br>
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
- the memory UI exposes exactly `FRAME`, `ACTIVE`, `DELAYED`, `L-T`, and `FILES`; the internal Facts Memory candidate buffer is not a sixth tab;
- FRAME is the canonical name for live runtime memory across documentation, implementation modules, state fields, events, the pending journal, UI identifiers, and tests.
- direct value editing is live for the latest FRAME, Active conditions/value, and L-T fact values; keys/IDs remain read-only, drafts are page-local until acknowledged, and Active/L-T edits surface `updated_at`.
- the L-T panel defaults to active facts, can toggle `show all` to reveal report-absorbed facts in normal sort order, and keeps report-linked fact IDs clickable.
- L-T recall now tracks `mention_count`/`last_mentioned_at`: facts untouched for 24 hours are compacted to 100-character sentence previews in Brain context until JIN references them again.
- pinned outgoing files appear as composer attachment chips; click previews, hold detaches from context without deleting the persistent file.
- Brain recent-message context is adjacent to `<FRAME_MEMORY_N>` and keeps the newest five pairs in full, with newline/XML normalization but no per-message character crop;
- ordinary Brain turns include the previous successful reasoning block with explicit middle-crop semantics, while follow-ups keep their dedicated reasoning context;
- browser continuity uses page-ephemeral `jin.liveRuntimeMemory.v2` plus one atomic `jin.sessionCheckpoint.v2`; legacy per-session FRAME selection is migration-only and never freshness-scanned;
- Session CLEAR is a durable tombstone that blocks passive resurrection across already-open tabs until a new USER message is successfully sent;
- `SAVE_SESSION` is not a current runtime-action contract; archived-session restore is handled by the bootstrap/restore path;
- the current action set includes `JIN_REACTION`, `RECALL_FACT_CONTEXT`, `CHAT_LOG_SEARCH`, and whole-file `ATTACH_FILE_BY_ID`; skill loading is taught as one paired `<LOAD_SKILL_CONTEXT>...</LOAD_SKILL_CONTEXT>` block per skill while `LOAD_SKILL` remains the internal action name;
- `<CURRENT_CONCERNS>` is always present; at 50%+ previous-answer context usage it shows the live percentage, and if tool results are present it explicitly recommends cleaning redundant results;
- bubble skins are `dark`, `light`, and `bamboo`, with dark/light following normal/Win95 theme defaults unless a non-default skin is explicitly pinned;
- Live Avatar scaffold circles/rays now mirror the context-pressure color, ray peak opacity scales approximately 0.10 -> 0.50 over a 30-second fade-to-zero breathing cycle, and center hide includes the file ring before switching hidden layers to dormant mode after the fade.

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
- `config_loader.py` and `launch_jin.ps1` recognize `USE_SERVICE_AS_BRAIN` only to migrate old local configs;
- `utils/session_restore.py` / `ui/static/js/session-restore.js` can render archived `service` roles and `RUNTIME_MODE=SERVICE`;
- `ui/static/js/logger/log-entries.js` can present old `[SERVICE]` model-output cards, although current backend code has no `log_service_output` writer.

These paths are localized compatibility readers/adapters. None changes current foreground routing.

### Test residue

Some tests still mention `CAN_SAVE_SESSION`, `<SAVE_SESSION>`, or other retired names as negative/compatibility fixtures. Treat those occurrences as test intent that must be read in context, not evidence that the action/topology is live. Current contract and prompt tests also cover the renamed `LOAD_SKILL_CONTEXT`, five-pair dialogue window, structured Active update payload, chat/fact recall, and context/avatar client contracts. This documentation pass does not modify tests.

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

- browser live checkpoint persistence (`runtime-session.js` / `runtime-storage.js`);
- `runtime_resume` soft resume;
- `session_bootstrap` state hydration;
- archived session payload built from logs (`utils/session_restore.py`);
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
result and its T ID; checkpoint hydration preserves full matched messages
without slicing the result JSON at 32K. Details: [CHAT_LOG_SEARCH.md](CHAT_LOG_SEARCH.md).

Search verification (2026-09-08): 20 focused search, unclosed-action and readable
tool-result tests pass; the headless Edge socket-to-DOM test and existing tool-ID
history/checkpoint JS test pass. Extending the run with archived restore and
bootstrap-tail tests yields 54/58 passing. The four archived-restore failures
also reproduce with the original changed reader functions and original action
flags: old `runtimeMemory.saved_at` client expectation, one-shot restore prompt,
the then-current restore-dialog bound, and bounded URL-restore UI tail. Those were historical failures from the 2026-09-08 search work; the current shared dialogue bound is five pairs and the restore/follow-up prompt ordering has since changed. Older cleanup tests may still name removed function/log strings. This paragraph is historical evidence, not the current verification status.

The contract assembler currently maps these actions in runtime order:

```text
DEEP_WEB_SEARCH
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
LIST_FILES
ATTACH_FILE_CONTENT
ATTACH_FILE_BY_ID
SAVE_DELAYED_MEMORY
LOAD_DELAYED_MEMORY
UNLOAD_DELAYED_MEMORY
SAVE_ACTIVE_MEMORY
DELETE_ACTIVE_MEMORY
UPDATE_ACTIVE_MEMORY
```

`LOAD_SKILL` is the internal runtime action name only. Its canonical public/model marker is `<LOAD_SKILL_CONTEXT> name of skill </LOAD_SKILL_CONTEXT>` and exactly one skill is loaded per block. Old `LOAD_SKILL`/`LOAD_SKILLS` tags do not become executable aliases simply because the internal action retains that name.

`utils/actions/dispatcher.py` contains execution branches for the same action family. Every concrete contract now carries a separate `schema` string array before `rules`; `contracts/rules_assembler.py::get_runtime_action_schema()` feeds both model-facing contract text and failed-action diagnostics. Failed tool results are rendered as readable text (status/reason, supplied payload when relevant, `Correct action schema:`), and `ACTION_FAILURE_FOLLOWUP_MESSAGE` explicitly tells Brain not to assume the failed action completed.

`POSTING_BOARD` is a native action exposed only after `<LOAD_SKILL_CONTEXT> posting_board </LOAD_SKILL_CONTEXT>`. The side skill documents the minimal inner actions (`feed`, `inbox`, `read`, `search`, `post`, `reply`, `ack`, `delete`); the runtime executes them against Get Posting Board and records the exact public request preview plus response as a runtime tool result. Chat bubbles use one stable action ID from running to completed/failed, then fade and become clickable for the reused trace modal. Session Actions intentionally keep only compact markers such as `POSTING_BOARD: action:feed` or `POSTING_BOARD: action:post - failed`; request/response bodies stay out of session-action text. Public writes, including deletion, are blocked when persistent writes are restricted, while board reads remain available. `delete` targets one owned message by exact `post_id`; deleting a root removes the entire thread, so the skill requires explicit authorization and warns Brain to preserve roots unless whole-thread deletion is intended. The bearer token is resolved through the environment override helper from `GETPOSTINGBOARD_API_KEY` (or its supported `JIN_GETPOSTINGBOARD_API_KEY` alias) and is never projected into model/UI context.

The mapped Brain feature flags in `rules/brain_context_builder.py` are enabled. `WEB_SEARCH` and `DEEP_WEB_SEARCH` are then filtered again by `settings.CAN_SEARCH`, so they are not model-visible unless provider `serper` has a non-empty, non-placeholder process-environment key. `launch_jin.ps1` imports an ignored repository-root `.env` before resolving configuration and starting Python; `.env.example` documents the supported secret names without containing credentials. Direct `python app.py` starts still rely on variables exported by the calling shell. The local availability check intentionally does not impose an invented key-length/shape regex; Serper remains the credential authority.

`CLEAN_TOOL_RESULTS` is a strict paired-block action. The canonical targeted form is `<CLEAN_TOOL_RESULTS> T1, T2, T3 </CLEAN_TOOL_RESULTS>`; one or more exact `T<number>` IDs are listed in the body, separated by commas. Targeted cleanup validates the whole list before mutating state, so an invalid or missing ID removes nothing. An empty `<CLEAN_TOOL_RESULTS></CLEAN_TOOL_RESULTS>` block performs the explicit full cleanup, including legacy ID-less results. The old bare marker and `<CLEAN_TOOL_RESULTS: T1 >` inline form are no longer executable syntax.

`JIN_SIZE` contract version 2 currently advertises `<JIN_SIZE> w:120 h:120 </JIN_SIZE>`; a single value such as `<JIN_SIZE> 120px </JIN_SIZE>` means square size. Positive decimal values may use `px`, `vw`, `vh`, or `%`, with unitless values defaulting to `px`. The backend preserves those units in the canonical action payload. The browser resolves them against the live viewport when the action is applied: width `%` uses viewport width, height `%` uses viewport height, `vw` always uses viewport width, and `vh` always uses viewport height. The applied/clamped room geometry is then persisted in pixels. Unsupported suffixes such as `em` are rejected instead of being silently reinterpreted as pixels.

`JIN_COLOR` contract version 2 likewise advertises `<JIN_COLOR> #00f2ff </JIN_COLOR>`. Both actions put payload in a paired tag body. Localized parsing still accepts old colon/space inline variants, but those are not model-facing syntax. Current parser/formatter tests require ordinary `before`/`after` answer text to survive marker removal and cover split-chunk completion.

The runtime now also has a strict response-prefix fallback for missing angle brackets. Before visible answer text starts, an exact standalone `ACTION_NAME: payload` line may execute only for enabled payload-bearing short actions and the JIN one-line compatibility actions, and only when the existing payload validator accepts it (with stricter ID-shape checks for recall/active/delayed-memory IDs). Invalid or prose-like payloads stay visible and immediately end the bare fallback; later bare lines stay text, while ordinary `<...>` markers continue to work. Streaming holds an unterminated candidate until newline or final flush, and accepted standalone action lines are removed without leaving a blank line.

The JIN visual sequence path preserves the model's marker order across color/size/speed/position. Color and size filtering removes only a no-op against the last applied value in the same runtime-message scope; an alternating sequence is not a repetition failure, and the same color can be requested in another message.

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

`SAVE_ACTIVE_MEMORY` version 4:

```json
{"conditions":"CONDITIONS","custom_field_name":"VALUE"}
```

`UPDATE_ACTIVE_MEMORY` version 2:

```json
{"active_memory_id":"existing id VALUE","fields_to_update":{"field_name":"NEW_VALUE","another_field":"NEW_VALUE"}}
```

The create parser now treats custom fields as explicit JSON structure only. A non-JSON body is preserved as the complete `conditions` value; parenthesized prose such as `(date: tomorrow)` is no longer reinterpreted as a custom field. JSON custom fields are capped at three after normalized duplicate keys use last-value-wins behavior.

The model-facing update contract has one canonical shape: paired `<UPDATE_ACTIVE_MEMORY>...</UPDATE_ACTIVE_MEMORY>` containing `active_memory_id` plus `fields_to_update`; every changed field goes inside that object, including single-field updates. Keys are exact existing field names. Creation remains paired `<SAVE_ACTIVE_MEMORY>...</SAVE_ACTIVE_MEMORY>` with `conditions` and optional custom fields at the JSON root.

The parser still accepts older flat/nested/line-based and self-closing attribute forms as reader compatibility only; they are not advertised to the model.

### Current internal representation

Active records are still stored/transported in a string-oriented record format with metadata suffixes. Prompt assembly refreshes metadata, removes paused items, and may rank the prompt view by lexical/context relevance.

### Risk

Do not “finish the migration” by replacing the internal storage shape in an unrelated task. The structured JSON action boundary is settled separately from the string-oriented internal record representation; storage migration needs its own end-to-end plan.

---

## 8. Prompt assembly — verified order

Current `build_brain_context()` order is intentionally structured. Important anchors:

- ordinary turns put `CURRENT_RUNTIME_SETTINGS` first when non-empty, then always-present `CURRENT_CONCERNS`, trusted runtime XML, optional waiting state, and `CONTEXT_USAGE`;
- at 50%+ previous-answer context usage, `CURRENT_CONCERNS` shows the percentage; with nonempty tool results it appends `check and clean redundant tool results`;
- tool results precede Session Actions, attached-file/Delayed inventories, and the always-present `SKILLS_LIST`; loaded skill bodies are part of the tool-results projection rather than a second independent prompt section;
- the runtime-context group orders Active Memory before FRAME, and `<PREVIOUS_CHAT_MESSAGES>` immediately after `<FRAME_MEMORY_N>`; loaded Delayed/L-T follow later in the same group;
- ordinary `<PREVIOUS_CHAT_MESSAGES>` keeps the newest five pairs without per-message character cropping; physical newlines become literal `\n` and XML-sensitive characters are escaped;
- ordinary initial turns include previous successful reasoning in `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>`; blocks over 2000 characters keep the first and last 25% with an explicit middle-cut marker;
- archived restore priming instead begins with inherited `<PREVIOUS_CHAT_MESSAGES>`, then carried reasoning evidence, then `<MANDATORY_SYSTEM_NOTIFICATION>`; `CURRENT_RUNTIME_SETTINGS` and the normal live scaffolding come after that continuity preamble;
- action/recovery follow-ups likewise move visible dialogue and carried reasoning ahead of `<FOLLOW_UP_RESPONSE_MESSAGE>`, then append failure/recovery/action history/current concerns/tool results and the base prompt without duplicating those continuity blocks;
- action contracts remain present even on restore ticks, subject to effective capability filtering;
- `WEB_SEARCH` and `DEEP_WEB_SEARCH` disappear when `settings.CAN_SEARCH` is false;
- identity and loop rules remain at the bottom of the base prompt.

Any prompt-order change can alter behavior materially. Do not reorder sections for aesthetics.

---

## 9. Bootstrap / archived restore — verified behavior

### 9.1 Common checkpoint and lineage

The browser common checkpoint is the last session that actually moved, not the most recently opened runtime ID. It is one atomic `localStorage` record at `jin.sessionCheckpoint.v2`. `applyPersistedSessionBootstrap()` hydrates inherited FRAME only into `jin.liveRuntimeMemory.v2` in the current page's `sessionStorage`; it does not create a durable per-session record or advance the common checkpoint on page load. The live key is cleared whenever the page module executes, so only soft reconnect inside the same running page can reuse it.

A user send marks the session dirty immediately. The next live-checkpoint write can promote that session even if generation is stopped before a visible answer. `completed_turn_commit` is a server fallback and separately advances `conversation_committed_at`; that timestamp is not the definition of every session move.

There is no normal per-session FRAME candidate scan. `runtime_snapshot.session_id` preserves the FRAME's origin rather than being rewritten to the current runtime ID. Room/avatar persistence normally rejects cross-session writes and never changes checkpoint lineage.

Session CLEAR writes `{version: 2, state: "cleared", cleared_at}` rather than merely deleting the key. Passive writers in any already-open tab remain blocked. Only a successfully emitted real USER message marks that page eligible to write the next checkpoint; retry, bootstrap, reconnect, and passive events do not. The first post-clear checkpoint retains a clear barrier so a pre-clear tab cannot overwrite the new owner later.

Migration is one-time and normal-profile-only. A legacy common snapshot selects the owner; it may join a matching saved-runtime record or only that owner's exact per-session record. Without a common snapshot, only the self-contained saved-runtime record may migrate. Orphan per-session keys create a tombstone instead of restoring. Cleanup happens only after a successful v2 write, so quota/write failures preserve legacy data for retry.

The server supplies `session_snapshot` on `message_end` and `agent_runtime_end`. The browser adds current room/avatar state and persists before finishing the visible message bubble, so completed turn data and room state are committed through one common snapshot path.

### 9.2 Raw-log source selection and split freshness

Despite its historical name, `find_latest_completed_session_restore_payload()` now selects the newest non-anonymous raw-log session containing a real USER move. A blank bootstrap-only session is ignored. A stopped USER-only move qualifies, as does an action-only completion whose durable JIN row has empty visible text. `_anon` log sessions are never restore candidates.

If raw logs prove a different session has a strictly newer USER tail than both the requested archive and browser tail, bootstrap switches `source_session_id` and discards the stale source's browser actions/color with it.

Archive enrichment now has two clocks:

- dialogue, reasoning, and dialogue counters compare archive recent-turn tail to browser recent-turn tail;
- runtime/resource fields use whole-checkpoint `saved_at` against the archive tail.

This fixes the case where a newly cloned runtime snapshot has a newer `saved_at` but still carries older copied dialogue. A field-local write must still preserve `saved_at`; it is not a generic last-touched value.

Session actions are merged by event ID when present or by structured identity otherwise, sorted by real timestamp, and capped. For the same source, the common checkpoint owns actions at or before `saved_at`; raw JSONL supplies only later actions. Structured color arrays are part of identity and are preserved as normalized lowercase six-digit hex.

### 9.3 Field-specific enrichment

The repaired `CLEAN_TOOL_RESULTS` path mutates only the existing checkpoint's `session_snapshot.tool_results` to `[]` and records `tool_results_cleared_at`; it preserves `saved_at`, session lineage, and every unrelated checkpoint field. Explicit presence of `tool_results: []` is authoritative. Empty `loaded_memory_ids` and `active_memory_records` deliberately keep their prior archive-fallback semantics.

A newer raw `runtime_tool_result` of kind `lt` may still append after the greater of checkpoint `saved_at` and `tool_results_cleared_at`. Other archived tool results cannot cross the tombstone.

### 9.4 JIN color bootstrap

Accepted JIN_COLOR now updates `context.jin_color` before checkpoint construction and is also appended to JSONL as an ordered `runtime_action_request` containing color, event ID, timestamp, turn ID, and structured Session Action metadata. Archive restore can recover color events through up to three direct-predecessor links. Raw color recovery and context-text L-T action recovery coexist; one no longer suppresses the other.

For the same source session, explicit browser `current_jin_color` wins. If absent, the newest structured JIN_COLOR Session Action wins, then the raw/trusted archive color. When the authoritative source session changes, stale browser color is not carried over.

Early room restore applies the common checkpoint color locally. The backend then emits one `session_actions_update` with `bootstrap_restore=true` and `current_jin_color` for reconciliation. The old client resolver/tint-shift path and separate latest-color storage are absent.

The first bootstrap color consumes a synchronized 2000 ms avatar-center + scene-tint transition. Later/live changes use 333 ms. A live color dispatch requests immediate field-local checkpoint reconciliation; this is the only room writer allowed across a fresh-tab/common-checkpoint ID mismatch, and it preserves checkpoint `session_id`, lineage, and `saved_at`.

### 9.5 Normal bootstrap chat tail

The backend emits at most five newest real USER moves from `runtime_recent_turns`, with JIN, reasoning, and original timestamps where available. The browser rebuilds them through existing chat primitives, strips synthetic attached-context boilerplate from USER display, keeps USER-only moves without an empty BR bubble, appends the current date/session divider, and activates the live viewport at that divider. Explicit archived restore suppresses this duplicate normal-bootstrap tail.

### 9.6 Archived restore

Current restore code deliberately prevents the “double apply” class of bugs.

Verified behavior:

- archived visible dialogue is rebuilt from logs;
- the newest five real USER moves are used for the restore context in chronological order, with empty JIN retained where the turn was interrupted/action-only;
- no separate restore-reasoning dump is generated; the hidden bootstrap prompt instead carries the prior reasoning through `<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>` after `<PREVIOUS_CHAT_MESSAGES>` and before the mandatory automatic-restore notification;
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

### 13.8 Chat skins and avatar context pressure

`win95-theme.js` exposes three bubble skins: `dark`, `light`, and `bamboo`. Normal theme defaults to dark and Win95 to light. `jin_bubble_skin` stores the current choice; `jin_bubble_skin_pinned` means the user's explicit non-default choice survives a theme switch. The Context/trace settings UI renders the same three options.

`runtime-panel.js` synchronizes the Brain context meter into `--jin-context-pressure-color` and `--jin-context-pressure-percent`. Static scaffold circles do not rotate; their stroke and the ray stroke use the pressure color. Sixteen rays breathe to zero on a 30-second cycle. Pressure selects roughly 3..7 stronger rays and raises their maximum unmultiplied opacity from 0.10 at empty context to 0.50 at full context. The center toggle fades scaffold, runtime/memory rings, file ring/dots, and center rings; after the 420 ms fade the hidden layers enter `is-memory-layers-dormant`, which removes them from display and disables their orbit/reasoning animations. The center light remains visible.

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

JIN visual-action chat bubbles are currently gated off by `ENABLE_JIN_VISUAL_ACTION_BUBBLES=false`; parsing, execution, avatar updates, raw action logging, and Session Actions remain live.

Avatar center and scene tint now share one transition duration variable set. First bootstrap color uses 2000 ms once; all later/live color changes use 333 ms. There is no center-color queue, secondary bootstrap tint shift, or separate client color resolver in this snapshot.

---

## 14. Verification status for this exact snapshot

The 2026-09-17 documentation sync uses `jin_core(20260917-184157).zip` as the source baseline. The audit traced the live action contracts/assembler, Brain context builder, follow-up builder, bootstrap/restore paths, model-role normalization/registry, memory editors/stores, bubble-skin controller, runtime context meter, Live Avatar JS/CSS, and relevant client/server tests. Historical verification notes below this numbered current-state section remain dated history and must not be read as the status of this snapshot.

Focused verification for this documentation pass ran 65 Python tests across five-pair chat continuity, follow-up reasoning, current concerns, bootstrap tail, context/avatar contracts, bubble skins, JIN reaction, Active Memory failure follow-up, and skill assets: 64 passed and one stale bootstrap-tail assertion failed because it still expects `<OLD_SESSION_RESTORED_STATE>` while current source emits `<PREVIOUS_CHAT_MESSAGES>`. Three dependency-free JavaScript checks also passed (`recall_fact_context`, `session_bootstrap_boundary`, `bootstrap_owner_lifecycle`); the Playwright Active-Memory bubble check could not run because `playwright` is not installed in the supplied environment. This is not a claim that every model-dependent/browser integration probe in the repository was executed. The documentation-only patch changes no runtime or test code.

---

## 15. Documentation status

As of this snapshot, the documentation set has been synchronized with the production architecture:

- root `README.md` describes FRAME/L-T/Active/Delayed/Files instead of the old numbered four-layer model;
- README model-role/setup/configuration text describes Brain as the only foreground route and Service as optional/dedicated background execution with Brain fallback;
- `AGENTS.md` records the same routing invariant and explicitly classifies old `USE_SERVICE_AS_BRAIN` / archived Service labels as compatibility;
- `docs/JIN_ARCHITECTURE.md`, `docs/JIN_DECISIONS.md`, and this file use the 2026-09-17 inspected source as the Brain-first/FRAME/L-T baseline and include the latest memory-edit, recall, L-T-view, and attachment interaction contracts.

There is no root `ARCHITECTURE.md` in the inspected archive. `docs/JIN_ARCHITECTURE.md` is the canonical architecture document.

---

## 16. Repository-index caveat

Search/index output is navigation evidence, not existence evidence. The inspected archive itself is authoritative for whether a production module is present; this matters especially for removed L2/L3 paths that may remain in stale indexes or historical tests.

---

## 17. Patch-scope / working-tree caveat

The supplied snapshot does not include `.git`, so repository dirty status cannot be reconstructed from the archive. Treat any pre-existing files or local changes in a real checkout as owner-controlled and do not overwrite or “clean” them unless the task explicitly includes that scope.

---

## 18. Open / known-unknown items

Do not present these as settled without fresh code evidence:

- whether the full night self-review concept is implemented outside the inspected paths;
- which remaining L2/L3-named compatibility fields/readers are still required for real historical data;
- when stale tests that directly mutate `config.USE_SERVICE_AS_BRAIN` or expect `SAVE_SESSION` should be migrated to the Brain-first/checkpoint architecture;
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

Three targeted envelope masks now feed the shared failure-follow-up mechanism.
`MALFORMED_ACTION` is internal telemetry, not a new model-invokable contract.
Its result persists the detected name and original payload; ordered notifications
at the top of the next prompt carry the contract schema. Repeated malformed
attempts remain separately visible and are not stopped by a repair-attempt cap.
Ordinary action limits still apply to other action workflows.

Thirteen contracts previously had empty `schema` arrays despite the documented
schema invariant. Their existing canonical syntax was moved/copied into those
arrays so recovery can use the JSON field for every registered action. No action
payload semantics or feature flags changed.


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
