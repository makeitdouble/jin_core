# JIN Core Engine — Current State / Migration Notes

**Snapshot inspected:** `jin_core(20260823-114203).zip`
**Inspection date:** 2026-08-23  
**Context reference:** `JIN_CORE_CONTEXT_TRANSPLANT_2026-08-23.md`

This is the document to read before touching transitional code. It lists what is true in the inspected snapshot, what is legacy residue, and where product intent and implementation currently differ.

---

## 1. Executive state

The runtime is already on the post-L2/L3 architecture in the actual source tree, but the repository still contains substantial historical residue:

- old root documentation still describes four live layers;
- L2/L3 tests still exist and import modules that no longer exist;
- old session names/fields remain in compatibility/tests;
- `SAVE_SESSION` remains in historical tests/log parsing but is not a current action contract;
- Active Memory has a modern flat JSON action boundary but an older string-record internal/browser representation;
- search action exposure now follows real configured provider availability rather than feature flags alone;
- `CLEAN_TOOL_RESULTS` now has explicit cleared-state bootstrap semantics so old tool results cannot resurrect without falsifying checkpoint freshness;
- session-action logger metadata survives bootstrap, including JIN_COLOR swatches/hex hover;
- the full test suite is currently far from green on this snapshot.

New agents must not “repair” these contradictions by restoring the old architecture.

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
- `runtime/L4_memory.py`, `L4_memory_rules.py`, `L4_memory_utils.py`
- `runtime/metabolism.py`
- `runtime/anonymous_mode.py`
- `contracts/*.json`
- `utils/actions/*`
- `utils/context/*`
- `utils/session_restore.py`

Not present:

- `runtime/L2_memory.py`
- `runtime/L2_memory_utils.py`
- `runtime/L2_memory_rules.py`
- `runtime/L3_memory.py`
- `runtime/L3_memory_utils.py`
- `runtime/L3_memory_rules.py`

Direct import check on the snapshot returns `ModuleNotFoundError` for the missing L2/L3 modules.

---

## 3. L2/L3 legacy conflict

### Product intent

L2 and L3 were removed as architectural layers on 2026-08-19/20.

### Current source

The runtime package agrees: the modules are gone.

### Legacy residue still present

- root `README.md` still presents “The Four-Layer Memory Model”;
- root `ARCHITECTURE.md` still describes `runtime/L2_memory.py` and `runtime/L3_memory.py` as active;
- `tests/test_l2_memory.py` and `tests/test_l3_session_memory.py` still import the deleted modules;
- additional tests reference `runtime_l3_session_memory` and old session semantics;
- some JS comments/log filters mention L2/L3;
- `runtime-storage.js` explicitly contains one-time compatibility wording for checkpoints created before L3 removal.

### Rule for agents

Do not restore deleted modules to satisfy stale tests/docs. Classify each remaining reference as:

1. required backward compatibility;
2. harmless historical wording;
3. stale test/documentation that should eventually be removed or rewritten;
4. accidental live dependency.

Only category 4 is a runtime bug.

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
IDLE
JIN_COLOR
JIN_SIZE
JIN_POSITION
JIN_SPEED
UPDATE_L4_FACTS
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
RESOLVE_ACTIVE_MEMORY
UPDATE_ACTIVE_MEMORY
```

`utils/actions/dispatcher.py` contains execution branches for the same action family.

Default Brain action flags currently set `CAN_RUNTIME_TODO=False`; the other mapped feature flags in `rules/brain_context_builder.py` are enabled. `WEB_SEARCH` and `DEEP_WEB_SEARCH` are then filtered again by `settings.CAN_SEARCH`, so they are not model-visible unless provider `serper` has a non-empty, non-placeholder configured key. `config.example.py` exposes the search settings with `mock-serper-api-key`; that placeholder intentionally keeps search disabled until a real local key is configured. The local availability check intentionally does not impose an invented key-length/shape regex; Serper remains the credential authority.

`CLEAN_TOOL_RESULTS` is a no-payload action. The canonical bare `<CLEAN_TOOL_RESULTS>` marker and a redundant paired-looking `<CLEAN_TOOL_RESULTS>...</CLEAN_TOOL_RESULTS>` form resolve to one cleanup; the closing tag is consumed as parser noise, including when split across stream chunks.

`JIN_SIZE` contract version 2 currently advertises `<JIN_SIZE> w:120 h:120 </JIN_SIZE>`; a single value such as `<JIN_SIZE> 120px </JIN_SIZE>` means square size. Size values may use px, percent, or vw/vh, with px as the default unit.

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

Active records are still stored/transported in a string-oriented record format with metadata suffixes. Prompt assembly refreshes metadata, removes paused items, and may rank the prompt view by metabolism salience.

### Risk

Do not “finish the migration” by replacing the internal storage shape in an unrelated task. The flat JSON decision applies to the action/model boundary; storage migration needs its own end-to-end plan.

---

## 8. Prompt assembly — verified order

Current `build_brain_context()` order is intentionally structured. Important anchors:

- `CURRENT_RUNTIME_SETTINGS` is first when non-empty;
- restore instruction is next only for restore priming;
- current concerns and trusted runtime XML precede tool/session/action state;
- file + delayed inventories sit near the top on ordinary turns;
- Active/L1/loaded Delayed/L4 live together in the runtime-context group;
- restored exact dialog replaces the normal recent-dialog window for the one-shot restore path;
- action contracts remain present even on restore ticks, subject to effective capability filtering;
- both search contracts disappear from the prompt when `settings.CAN_SEARCH` is false;
- identity and loop rules are at the bottom.

Any prompt-order change can alter behavior materially. Do not reorder sections for aesthetics.

---

## 9. Bootstrap / archived restore — verified behavior

### Browser predecessor bootstrap / archive enrichment

A browser checkpoint may be enriched from the predecessor raw log, but only when the archive is not older than the checkpoint freshness boundary. `saved_at` therefore means “this whole checkpoint is current through here,” not “some field was touched recently.” Advancing it for a one-field cleanup can suppress otherwise valid archive enrichment of dialogue/reasoning/session-actions/files.

The repaired `CLEAN_TOOL_RESULTS` path now mutates only the existing checkpoint's `session_snapshot.tool_results` to `[]`; it preserves `saved_at`, session lineage, and every unrelated checkpoint field. On bootstrap, explicit presence of `tool_results: []` is authoritative and blocks archive fallback for that field. Empty `loaded_memory_ids` and `active_memory_records` deliberately keep their prior archive-fallback semantics.

Session-action normalization also preserves structured `parts[].colors` metadata. Valid `#rgb`/`#rrggbb` colors are normalized to lowercase six-digit hex, allowing restored JIN_COLOR history to render the same color square and hex hover as live history.

### Archived restore

Current restore code deliberately prevents the “double apply” class of bugs.

Verified behavior:

- archived visible dialogue is rebuilt from logs;
- the newest complete USER/JIN pairs are used for the restore context;
- a bounded recent reasoning dump is included;
- loaded Delayed IDs, attached files, and avatar state are staged;
- restore Brain response occurs before normal resource reactivation;
- `BrainNode.replay_session_restore_resource_actions()` consumes the staged envelope and applies it through the real action dispatcher;
- WebSocket tail only clears defensive state and explicitly warns against mutating/emitting resource state a second time.

This is a strong architectural clue for future restore fixes: find duplicate writers before adding another apply.

---

## 10. L4 / Facts Memory current path

### Facts Memory

Browser runtime storage creates per-session facts-memory candidate buckets from persisted runtime snapshots and synchronizes them to backend with `facts_memory_store_sync`.

### L4

L4 has a real staged pipeline with:

- pending candidate collection;
- extraction;
- merge/rebase;
- validation/recovery/backoff;
- explicit-edit protection;
- report-reference remapping;
- archive/anchor logic;
- delete/restore;
- file-store persistence.

### L4 UI projection

Ordinary L4 rows display a 50-character value preview. When a fact is bubbled because it was referenced, explicitly cited from reasoning, or loaded into context, the row displays the complete value with no preview truncation. This does not mutate or reorder the stored fact; it is a visibility rule for surfaced evidence.

### Scheduling

L4 background work is started by browser `l4_memory_idle_tick`. Server refuses to begin it while a foreground task is active or the pending request queue is non-empty.

This is the current performance/ordering contract. Do not move L4 onto every foreground turn to “make facts faster” without proving latency and ordering behavior.

---

## 11. Metabolism status

`runtime/metabolism.py` is large and actively wired into the foreground/L1 flow.

Verified active pieces include:

- pre-Brain foreground impulse;
- post-turn settling;
- Active/Delayed/L4 significance/salience scoring;
- temperature adjustment;
- recent-turn memory;
- association learning;
- SERVICE update scheduled after successful L1 diff commit;
- bootstrap state support.

### Not proven

The older concept of a full nightly self-review cycle that reads cropped reasoning/context and emits a morning cleanup report is **not proven complete** by this snapshot. Do not describe it as finished architecture without finding the actual scheduler/storage/report path.

---

## 12. Anonymous mode status

Backend `runtime/anonymous_mode.py` currently:

- marks runtime persistent writes restricted;
- disables Delayed file-store writes while allowing read hydration;
- blocks `UPDATE_L4_FACTS`;
- blocks `SAVE_DELAYED_MEMORY`;
- blocks persistent asset-write actions;
- leaves read-only/runtime-local paths available as appropriate.

Browser runtime storage also contains isolation logic for anonymous/private windows.

The intended product behavior remains: anonymous has its own Active/session state but can still see global L4/Delayed context. Verify both browser and backend sides before changing this.

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

Owner prefers `FRAME` over generic `STATE` for the question -> answer -> live-context cycle.

**State:** preference recorded, but this snapshot does not establish a safe complete rename target. Do not global-replace `RUNTIME`/`STATE`.

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
- answer-rating controls use directional hover titles (`Dislike answer` / `Like answer`) and do not put a count tooltip on the rated bubble;
- Win95 theme localStorage reads/writes are guarded so restricted storage contexts do not break theme switching.

---

## 14. Test suite status on this exact snapshot

Command run:

```text
python -m unittest discover -s tests
```

Result on the inspected archive:

```text
Ran 837 tests in 28.927s
FAILED (failures=67, errors=32, skipped=9)
```

Important implications:

- the repository is **not green** in this snapshot;
- some collection/import errors are directly explained by stale L2/L3 tests importing deleted modules;
- several `tests/runtime_actions/*` modules also fail import because they still depend on the removed `clients.brain_client.should_execute_save_session` symbol;
- many additional failures/errors remain beyond those stale imports, including older prompt/follow-up/session-action/search expectations;
- do not use “full suite currently fails” as permission to ignore targeted regressions;
- for any patch, run the smallest relevant target set and report exact pass/fail counts.

Do not resurrect L2/L3 merely to make stale tests import again. The test suite itself needs a deliberate cleanup/migration task.

---

## 15. Old documentation status

### Root `README.md`

Currently stale in major architecture sections:

- still describes L1/L2/L3/L4 as four active layers;
- still describes L2 pattern updates and L3 session digest;
- still describes old post-turn L1/L2 behavior;
- lists current features mixed with removed architecture.

### Root `ARCHITECTURE.md`

Also stale:

- describes `runtime/L2_memory.py` and `runtime/L3_memory.py` as active files;
- describes Brain context as including live L2/L3 state;
- describes `SAVE_SESSION`/L3 flow as current.

### Rule

Use `docs/JIN_ARCHITECTURE.md` + `docs/JIN_DECISIONS.md` + this file as the current architecture baseline. Updating/removing old docs should be a separate explicit cleanup diff so product changes and documentation cleanup are reviewable.

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
- which remaining L2/L3-named compatibility fields are still required for real historical data;
- whether all old `SAVE_SESSION` tests should be deleted or rewritten around checkpoints;
- final intended internal storage format for Active Memory after the flat-JSON boundary migration;
- exact final semantics/name for the UI `FRAME` label;
- whether reveal debounce should now be restored from 333 ms to the earlier 250 ms preference;
- final canonical list of supported noncanonical action marker aliases after compatibility cleanup;
- which current full-suite failures are regressions versus intentionally stale tests;
- whether every linked-highlight/pin/pause/delete path is currently synchronized between panel, prompt-loaded state, and avatar.

When one of these becomes the task, investigate first and record the resolved decision in `JIN_DECISIONS.md`.

---

## 19. Recommended near-term documentation cleanup order

When the owner explicitly asks for cleanup:

1. migrate/delete stale L2/L3 tests so the suite represents the post-L2/L3 architecture;
2. rewrite root `ARCHITECTURE.md` to point to or mirror `docs/JIN_ARCHITECTURE.md`;
3. update the README memory/session sections;
4. remove misleading old `SAVE_SESSION` feature claims while preserving archive compatibility code;
5. audit old comments/UI logger filters for L2/L3 wording;
6. only then remove compatibility fields that are proven unused by real archived data.

Do not combine this cleanup with unrelated runtime behavior patches.
