# JIN Core Engine — Current State / Migration Notes

**Snapshot inspected:** `jin_core(20260829-114751).zip`<br>
**Inspection date:** 2026-08-29<br>
**Context reference:** current production source plus the accumulated 2026-08-23--29 project decisions. Tests were explicitly excluded from this audit and were not executed.

This is the document to read before touching transitional code. It lists what is true in the inspected snapshot, what is legacy residue, and where product intent and implementation currently differ.

---

## 1. Executive state

The production runtime is on the post-L2/L3, Brain-first architecture and the root documentation is now synchronized with it.

Current high-signal state:

- foreground user turns always execute through `AgentRuntime -> BrainNode -> context.clients["brain"]`; no production branch can switch visible responses to Service;
- Service is background-only. With `SERVICE_API_BASE` empty, `clients["service"]` intentionally aliases the Brain client; configuring a dedicated Service endpoint changes only background execution;
- `USE_SERVICE_AS_BRAIN` survives only as a localized old-config migration input in `config_loader.py` plus launcher detection. Normalization promotes old Service settings to Brain, clears the dedicated Service URL, then deletes the legacy flag;
- archived `role=service` / `RUNTIME_MODE=SERVICE` handling and the logger's old `[SERVICE]` output-card presentation are historical reader compatibility only; there is no current writer/foreground route for that mode;
- L2/L3 remain removed architectural layers. Remaining production references are compatibility comments/log filters/storage migration residue, not active modules;
- the memory UI exposes exactly `FRAME`, `ACTIVE`, `DELAYED`, `L-T`, and `FILES`; the internal Facts Memory candidate buffer is not a sixth tab;
- Brain recent-message context is adjacent to `<FRAME_MEMORY_N>` and keeps the newest three pairs in full, with newline/XML normalization but no per-message character crop;
- ordinary Brain turns include the previous successful reasoning block with explicit middle-crop semantics, while follow-ups keep their dedicated reasoning context;
- browser continuity uses page-ephemeral `jin.liveRuntimeMemory.v2` plus one atomic `jin.sessionCheckpoint.v2`; legacy per-session FRAME selection is migration-only and never freshness-scanned;
- Session CLEAR is a durable tombstone that blocks passive resurrection across already-open tabs until a new USER message is successfully sent;
- `SAVE_SESSION` is not a current runtime-action contract; archived-session restore is handled by the bootstrap/restore path;
- tests still contain historical Brain-as-Service / `SAVE_SESSION` assumptions, but this audit intentionally skipped all test code and made no test changes.

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
- `runtime/L1_memory.py`, `L1_memory_rules.py`, `L1_memory_utils.py`
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

Tests still contain historical assumptions around `USE_SERVICE_AS_BRAIN`, `CAN_SAVE_SESSION`, and old `<SAVE_SESSION>` parsing. Per the 2026-08-29 audit scope, test code was not inspected for correctness, executed, or modified beyond identifying those references by search.

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

The contract assembler currently maps these actions:

```text
DEEP_WEB_SEARCH
WEB_SEARCH
CLEAN_TOOL_RESULTS
JIN_COLOR
JIN_SIZE
JIN_POSITION
JIN_SPEED
UPDATE_LT_FACTS
LOAD_SKILL
UNLOAD_SKILL
ASSET_ACTION
LIST_FILES
ATTACH_FILE
DETACH_FILE
CREATE_TODO_LIST
RESOLVE_TODO
CHECK_TODO
SAVE_DELAYED_MEMORY
LOAD_DELAYED_MEMORY
UNLOAD_DELAYED_MEMORY
SAVE_ACTIVE_MEMORY
DELETE_ACTIVE_MEMORY
UPDATE_ACTIVE_MEMORY
```

`utils/actions/dispatcher.py` contains execution branches for the same action family.

Default Brain action flags currently set `CAN_RUNTIME_TODO=False`; the other mapped feature flags in `rules/brain_context_builder.py` are enabled. `WEB_SEARCH` and `DEEP_WEB_SEARCH` are then filtered again by `settings.CAN_SEARCH`, so they are not model-visible unless provider `serper` has a non-empty, non-placeholder configured key. `config.example.py` exposes the search settings with `mock-serper-api-key`; that placeholder intentionally keeps search disabled until a real local key is configured. The local availability check intentionally does not impose an invented key-length/shape regex; Serper remains the credential authority.

`CLEAN_TOOL_RESULTS` is a no-payload action. The canonical bare `<CLEAN_TOOL_RESULTS>` marker and a redundant paired-looking `<CLEAN_TOOL_RESULTS>...</CLEAN_TOOL_RESULTS>` form resolve to one cleanup; the closing tag is consumed as parser noise, including when split across stream chunks.

`JIN_SIZE` contract version 2 currently advertises `<JIN_SIZE> w:120 h:120 </JIN_SIZE>`; a single value such as `<JIN_SIZE> 120px </JIN_SIZE>` means square size. Positive decimal values may use `px`, `vw`, `vh`, or `%`, with unitless values defaulting to `px`. The backend preserves those units in the canonical action payload. The browser resolves them against the live viewport when the action is applied: width `%` uses viewport width, height `%` uses viewport height, `vw` always uses viewport width, and `vh` always uses viewport height. The applied/clamped room geometry is then persisted in pixels. Unsupported suffixes such as `em` are rejected instead of being silently reinterpreted as pixels.

`JIN_COLOR` contract version 2 likewise advertises `<JIN_COLOR> #00f2ff </JIN_COLOR>`. Both actions put payload in a paired tag body. Localized parsing still accepts old colon/space inline variants, but those are not model-facing syntax. Current parser/formatter tests require ordinary `before`/`after` answer text to survive marker removal and cover split-chunk completion.

The JIN visual sequence path preserves the model's marker order across color/size/speed/position. Color and size filtering removes only a no-op against the last applied value in the same runtime-message scope; an alternating sequence is not a repetition failure, and the same color can be requested in another message.

---

## 6. Delayed Memory transition

### Current canonical contract

`contracts/save_delayed_memory.json` is version 4 and requires a JSON body inside `<SAVE_DELAYED_MEMORY> ... </SAVE_DELAYED_MEMORY>`.

Required fields:

- `title`
- `summary`
- `tags`
- `body`

Relationship fields:

- `anchor_fact_ids`
- `facts_ids`
- `attachments_ids`

The contract explicitly requires exact existing IDs and `anchor_fact_ids` as a subset of `facts_ids`.

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
{"active_memory_id":"existing id VALUE","field_name":"NEW_VALUE"}
```

The create parser now treats custom fields as explicit JSON structure only. A non-JSON body is preserved as the complete `conditions` value; parenthesized prose such as `(date: tomorrow)` is no longer reinterpreted as a custom field. JSON custom fields are capped at three after normalized duplicate keys use last-value-wins behavior.

The update parser accepts:

- current flat root fields;
- legacy `fields` object;
- legacy `updates` object;
- older line-based payloads;
- a self-closing attribute compatibility form such as `<UPDATE_ACTIVE_MEMORY active_memory_id="abc123" field=value />`.

The self-closing attribute form is compatibility only; the model-facing contract remains paired flat JSON.

### Current internal representation

Active records are still stored/transported in a string-oriented record format with metadata suffixes. Prompt assembly refreshes metadata, removes paused items, and may rank the prompt view by lexical/context relevance.

### Risk

Do not “finish the migration” by replacing the internal storage shape in an unrelated task. The flat JSON decision applies to the action/model boundary; storage migration needs its own end-to-end plan.

---

## 8. Prompt assembly — verified order

Current `build_brain_context()` order is intentionally structured. Important anchors:

- `CURRENT_RUNTIME_SETTINGS` is first when non-empty;
- restore instruction is next only for restore priming;
- current concerns and trusted runtime XML precede tool/session/action state;
- file + delayed inventories sit near the top on ordinary turns;
- Active/L1/loaded Delayed/L-T live together in the runtime-context group;
- restored exact dialog replaces the normal recent-dialog window for the one-shot restore path;
- ordinary `<PREVIOUS_CHAT_MESSAGES>` keeps the newest three pairs without per-message character cropping; physical newlines become literal `\\n` and XML-sensitive characters are escaped;
- ordinary initial turns include the previous successful reasoning; blocks over 2000 characters keep the first and last 25% with an explicit middle-cut marker;
- action/recovery follow-ups suppress that ordinary previous-reasoning block and inject their current-turn/loop reasoning through dedicated builders;
- action contracts remain present even on restore ticks, subject to effective capability filtering;
- both search contracts disappear from the prompt when `settings.CAN_SEARCH` is false;
- identity and loop rules are at the bottom.

Any prompt-order change can alter behavior materially. Do not reorder sections for aesthetics.

---

## 9. Bootstrap / archived restore — verified behavior

### 9.1 Common checkpoint and lineage

The browser common checkpoint is the last session that actually moved, not the most recently opened runtime ID. It is one atomic `localStorage` record at `jin.sessionCheckpoint.v2`. `applyPersistedSessionBootstrap()` hydrates inherited L1 only into `jin.liveRuntimeMemory.v2` in the current page's `sessionStorage`; it does not create a durable per-session record or advance the common checkpoint on page load. The live key is cleared whenever the page module executes, so only soft reconnect inside the same running page can reuse it.

A user send marks the session dirty immediately. The next live-checkpoint write can promote that session even if generation is stopped before a visible answer. `completed_turn_commit` is a server fallback and separately advances `conversation_committed_at`; that timestamp is not the definition of every session move.

There is no normal per-session L1 candidate scan. `runtime_snapshot.session_id` preserves the FRAME's origin rather than being rewritten to the current runtime ID. Room/avatar persistence normally rejects cross-session writes and never changes checkpoint lineage.

Session CLEAR writes `{version: 2, state: "cleared", cleared_at}` rather than merely deleting the key. Passive writers in any already-open tab remain blocked. Only a successfully emitted real USER message marks that page eligible to write the next checkpoint; retry, bootstrap, reconnect, and passive events do not. The first post-clear checkpoint retains a clear barrier so a pre-clear tab cannot overwrite the new owner later.

Migration is one-time and normal-profile-only. A legacy common snapshot selects the owner; it may join a matching saved-runtime record or only that owner's exact per-session record. Without a common snapshot, only the self-contained saved-runtime record may migrate. Orphan per-session keys create a tombstone instead of restoring. Cleanup happens only after a successful v2 write, so quota/write failures preserve legacy data for retry.

The server supplies `session_snapshot` on `message_end` and `agent_runtime_end`. The browser adds current room/avatar state and persists before finishing the visible message bubble, so completed turn data and room state are committed through one common snapshot path.

### 9.2 Raw-log source selection and split freshness

Despite its historical name, `find_latest_completed_session_restore_payload()` now selects the newest raw-log session containing a real USER move. A blank bootstrap-only session is ignored. A stopped USER-only move qualifies, as does an action-only completion whose durable JIN row has empty visible text. Normal and anonymous selectors read their own log roots only.

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

The backend emits at most three newest real USER moves from `runtime_recent_turns`, with JIN, reasoning, and original timestamps where available. The browser rebuilds them through existing chat primitives, strips synthetic attached-context boilerplate from USER display, keeps USER-only moves without an empty BR bubble, appends the current date/session divider, and activates the live viewport at that divider. Explicit archived restore suppresses this duplicate normal-bootstrap tail.

### 9.6 Archived restore

Current restore code deliberately prevents the “double apply” class of bugs.

Verified behavior:

- archived visible dialogue is rebuilt from logs;
- the newest three real USER moves are used for the restore context in chronological order, with empty JIN retained where the turn was interrupted/action-only;
- a bounded recent reasoning dump is included;
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

### Scheduling

L-T background work is started by browser `lt_memory_idle_tick`. Server refuses to begin it while a foreground task is active or the pending request queue is non-empty.

This is the current performance/ordering contract. Do not move L-T onto every foreground turn to “make facts faster” without proving latency and ordering behavior.

---

## 11. Memory Attention status

The metabolism subsystem has been removed. `runtime/memory_attention.py` retains only prompt-local retrieval behavior:

- Active lexical/context relevance;
- Delayed bubble matching;
- L-T 1–3 fact focus.

There is no metabolic SERVICE pass, homeostat, learned association state, temperature modulation, Brain instruction, L1 strength bias, significance persistence, bootstrap chemistry, logger trace, or avatar chemistry. Historical significance fields are discarded while normalizing old Active/Facts/L-T records.

### Not proven

The older concept of a full nightly self-review cycle that reads cropped reasoning/context and emits a morning cleanup report is **not proven complete** by this snapshot. Do not describe it as finished architecture without finding the actual scheduler/storage/report path; Memory Attention is unrelated to that cycle.

---

## 12. Anonymous mode status

Backend `runtime/anonymous_mode.py` currently:

- marks runtime persistent writes restricted;
- disables Delayed file-store writes while allowing read hydration;
- blocks `UPDATE_LT_FACTS`;
- blocks `SAVE_DELAYED_MEMORY`;
- blocks persistent asset-write actions;
- leaves read-only/runtime-local paths available as appropriate.

Browser runtime storage also contains isolation logic for anonymous/private windows.

The intended product behavior remains: anonymous has its own Active/session state but can still see global L-T/Delayed context. Verify both browser and backend sides before changing this.

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

The live runtime-memory view is now the `FRAME` tab. The rename is deliberately limited to that visible tab; internal runtime/state names remain unchanged.

The panel always shows `FRAME`, `ACTIVE`, `DELAYED`, `L-T`, and `FILES`, even when a non-FRAME view is empty. The shared counter moves below the selected tab; FRAME keeps the existing snapshot arrows while the other tabs show only their record count. The temporary unprocessed-facts projection is not exposed as a tab.

### 13.3 Visual reuse

Hard owner rule remains active: reuse existing visual primitives; no invented highlight colors/glows/badges/strips unless explicitly approved.

### 13.4 Loaded vs referenced highlight

Strong loaded-context highlighting and weak ID-reference highlighting are separate semantics. Opening a modal is not a context load. This area has had regressions and must be traced through both panel state and avatar state.

### 13.5 Session Actions logger

The compact logger now shows the most recent five actions in chronological order while retaining their original history numbering; `FULL` uses the existing attached-files header/button visual primitive rather than a new style. JIN_COLOR entries depend on `parts[].colors` for the color square and hex hover, so that metadata is part of the bootstrap contract, not disposable presentation data.

Validator/reasoning-loop and context/output-limit entries are emitted immediately when the interruption is detected, before automatic recovery/follow-up. `context_overflow` is included in context-limit finish reasons. This timing is intentional: the logger should reflect the loop while it is happening, not only after the final JIN response.

### 13.6 Runtime action hover stability

Runtime-action bubbles persist their detail in DOM dataset state. Counter-only updates reuse the existing detail/title instead of clearing it, so an aggregate count refresh cannot erase hover information.

### 13.7 Interaction fixes landed in this snapshot

- the latest manually chosen reasoning collapsed/expanded preference is persisted and reused by new reasoning blocks;
- live-turn top-lock releases once the user turn reaches the viewport bottom, after which normal overflow autoscroll can resume;
- clicking usable form padding focuses the JIN user input;
- answer-rating implementation remains in the client but is release-gated off; assistant bubbles now reuse the neutral hover primitive on empty padding, with double-click copy and latest-completed-answer long-tap replacement retry;
- Win95 theme localStorage reads/writes are guarded so restricted storage contexts do not break theme switching.

### 13.8 Normal bootstrap tail

Normal bootstrap renders the inherited three-USER-move tail above a date-labelled current-session divider and places the live viewport at the divider. Saved reasoning is rendered through the existing reasoning bubble path. A USER-only interrupted/action-only move remains visible without a blank BR bubble. Archived restore has its own renderer and blocks this path.

### 13.9 JIN color projection

JIN visual-action chat bubbles are currently gated off by `ENABLE_JIN_VISUAL_ACTION_BUBBLES=false`; parsing, execution, avatar updates, raw action logging, and Session Actions remain live.

Avatar center and scene tint now share one transition duration variable set. First bootstrap color uses 2000 ms once; all later/live color changes use 333 ms. There is no center-color queue, secondary bootstrap tint shift, or separate client color resolver in this snapshot.

---

## 14. Verification status for this exact snapshot

This 2026-08-29 pass was intentionally a **production-code + documentation audit only**. Per task scope:

- no unit tests were run;
- no browser/client-contract tests were run;
- no model probes were run;
- no files under `tests/` were edited.

The audit used source tracing and targeted repository searches to verify the foreground model route and classify legacy compatibility. Therefore this document makes **no claim that the test suite is green**. Historical pass/fail counts from older snapshots are not evidence for this archive.

For future code changes, run the smallest relevant checks unless the task explicitly excludes tests. Do not resurrect L2/L3, foreground Service routing, or `SAVE_SESSION` merely to satisfy stale tests.

---

## 15. Documentation status

As of this snapshot, the documentation set has been synchronized with the production architecture:

- root `README.md` describes FRAME/L-T/Active/Delayed/Files instead of the old numbered four-layer model;
- README model-role/setup/configuration text describes Brain as the only foreground route and Service as optional/dedicated background execution with Brain fallback;
- `AGENTS.md` records the same routing invariant and explicitly classifies old `USE_SERVICE_AS_BRAIN` / archived Service labels as compatibility;
- `docs/JIN_ARCHITECTURE.md`, `docs/JIN_DECISIONS.md`, and this file use the 2026-08-29 Brain-first topology as the baseline.

There is no root `ARCHITECTURE.md` in the inspected archive. `docs/JIN_ARCHITECTURE.md` is the canonical architecture document.

---

## 16. Search/index caveat

During the failed Codex documentation attempt, CodeGraph continued returning deleted L2/L3 paths even after sync while the actual archive filesystem did not contain those modules.

Treat any repository index as a navigation aid only. For existence/current behavior, verify the actual file and symbol in the working tree.

---

## 17. Working-tree ownership caveat

The Codex session that preceded these documents reported unrelated existing changes in the user's working tree (including `rules/runtime.py`, `pack_for_patch.bat`, and `ui/static/images/schema_old.jpg`). The provided ZIP does not include `.git`, so dirty status cannot be independently reconstructed here.

Rule for future agents: assume pre-existing files/changes are user-owned; do not overwrite or “clean” unrelated work unless explicitly asked.

---

## 18. Open / known-unknown items

Do not present these as settled without fresh code evidence:

- whether the full night self-review concept is implemented outside the inspected paths;
- which remaining L2/L3-named compatibility fields/readers are still required for real historical data;
- when stale tests that directly mutate `config.USE_SERVICE_AS_BRAIN` or expect `SAVE_SESSION` should be migrated to the Brain-first/checkpoint architecture;
- final intended internal storage format for Active Memory after the flat-JSON boundary migration;
- whether reveal debounce should now be restored from 333 ms to the earlier 250 ms preference;
- final canonical list of supported noncanonical action marker aliases after compatibility cleanup;
- which stale tests are still intentional compatibility coverage versus obsolete pre-Brain-first/pre-checkpoint expectations;
- whether every linked-highlight/pin/pause/delete path is currently synchronized between panel, prompt-loaded state, and avatar.

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
