# JIN Core Engine — Durable Decisions

**Decision baseline:** reconciled on 2026-09-01 against `jin_core(20260901-112006).zip` and the accumulated project context. The latest reconciliation traced production source and ran targeted tests for the newly documented memory/UI behavior.

This file records product/architecture intent that should survive refactors. It is not a changelog and not a dump of historical experiments.

Status vocabulary:

- **Accepted / implemented** — intent and current code agree.
- **Accepted / transitional** — decision is current, but compatibility/old representation still exists.
- **Accepted / not fully implemented** — product decision exists, but current source does not completely realize it.
- **Rejected** — do not reintroduce without an explicit new decision.

---

## D001 — The runtime is the product

**Status:** Accepted / implemented

JIN Core Engine is a model-agnostic cognitive runtime. The foreground BRAIN model and optional dedicated background SERVICE model are configuration choices, not product architecture.

**Why:** continuity, visible memory, actions, restore, UI semantics, and runtime state must survive model replacement.

**Rejected alternative:** designing the codebase around one named model or treating JIN as a thin chatbot wrapper.

---

## D002 — Direct foreground Brain path

**Status:** Accepted / implemented

The normal foreground path remains:

```text
user -> AgentRuntime -> BrainNode
```

No generic planner/router is inserted before Brain by default.

**Why:** lower latency, fewer hidden decisions, easier causality, less framework overhead.

**Rejected alternative:** adopting a large external agent harness/framework before v1.0 simply because it has similar abstractions.

---

## D003 — Inspectability and continuity are core product semantics

**Status:** Accepted / implemented

Memory/context/reasoning/actions/state must be inspectable enough that the user can understand what shaped a response and where continuity came from.

**Why:** “Without context, there is no JIN.” JIN should re-enter a conversation as a continuing runtime, not as a fresh chatbot with a generic summary.

**Rejected alternative:** opaque hidden RAG/state injection with no visible causality.

---

## D004 — L2 and L3 are removed architectural layers

**Status:** Accepted / implemented, with heavy legacy residue

L2 and L3 are no longer live architectural layers. The current conceptual set is:

- live FRAME;
- L-T durable facts;
- Active Memory;
- Delayed Memory;
- Files;
- runtime/session checkpoints.

**Why:** L2/L3 created overlapping ownership and stale conceptual layers after newer continuity/memory mechanisms evolved.

**Rejected alternative:** resurrecting L2/L3 because old README/tests are more complete than current docs.

---

## D005 — Durable FRAME is rejected; durable facts go to L-T

**Status:** Accepted / implemented

FRAME is live/operational state. Durable user/project facts belong in L-T rather than a persistent FRAME-like layer.

**Why:** one durable fact owner is easier to reconcile, inspect, age, link, and clean.

**Rejected alternative:** another long-lived “live memory” store parallel to L-T.

---

## D006 — Memory systems remain purpose-specific

**Status:** Accepted / implemented

Active Memory, Delayed Memory, L-T, FRAME, Files, and checkpoints are not interchangeable layers.

**Why:** they have different lifetimes, loading rules, UI semantics, and mutation paths.

**Rejected alternative:** one growing generic memory transcript/store.

---

## D007 — Runtime-action schemas belong in contracts

**Status:** Accepted / transitional

Concrete action syntax, fields, and action-specific rules belong in `contracts/*.json`. General runtime rules should describe only cross-action sequencing/invariants.

**Why:** one model-facing source of truth prevents contradictory prompts and makes action evolution testable.

**Rejected alternative:** duplicating the same action schema in `rules/runtime.py`, handlers, README, and prompt snippets.

---

## D008 — Delayed Memory save uses JSON under `<SAVE_DELAYED_MEMORY>`

**Status:** Accepted / implemented with legacy parser compatibility

Canonical form:

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

**Why:** explicit structured schema, safer validation, clearer ID relationships.

**Rejected alternative:** advertising `<SAVE_DELAYED_MEMORY_CONTENT>` key/value body as current syntax.

---

## D009 — Active Memory model boundary is flat JSON

**Status:** Accepted / transitional

Create and update payloads should be plain root-level JSON. `conditions` is the default required create field; update uses `active_memory_id` plus changed fields at the root.

**Why:** simpler model contract and less parser ambiguity.

**Compatibility rule:** old nested `fields`/`updates`, older line-based updates, and a self-closing UPDATE attribute form may be accepted by localized compatibility code but should not be taught as the primary format. SAVE custom fields come only from explicit JSON root fields; plain prose/parenthesized text must not be silently promoted into schema.

---

## D010 — Compatibility adapters stay local

**Status:** Accepted / partially implemented

When legacy data must still load, normalize it at a narrow boundary. Do not spread legacy conditionals through prompt assembly, UI, persistence, and action rules.

**Why:** transition debt otherwise becomes permanent architecture.

**Rejected alternative:** keeping multiple live formats everywhere “just in case.”

---

## D011 — Current session continuity does not depend on a model `SAVE_SESSION` action

**Status:** Accepted / implemented in current snapshot

Live/session continuity is built around browser/runtime checkpoints, reconnect/bootstrap, archived chat/reasoning logs, and restore metadata. There is no current `SAVE_SESSION` contract.

Historical `SAVE_SESSION` labels/fields can still be read for old archives/tests.

**Why:** session continuity is runtime infrastructure and should not depend on the model remembering to emit a special save marker.

**Rejected alternative:** reintroducing `SAVE_SESSION` from old docs/tests without a new product decision.

---

## D012 — Archived restore uses a staged one-shot priming path

**Status:** Accepted / implemented

Archived restore first gives Brain bounded exact historical context, then reactivates historical resources through the normal action pipeline. Resource state is not applied independently again at the WebSocket tail.

**Why:** prevents duplicate apply/races and preserves a natural continuity greeting before old resources become normal live state.

**Rejected alternative:** multiple independent restore writers that all “ensure” final state.

---

## D013 — Interrupted turn is not a completed turn

**Status:** Accepted / implemented

Stop/cancel/repetition/context-limit interruption must preserve separate lifecycle semantics. A real USER move is retained in the latest-session/bootstrap tail even when no JIN row exists, but it must remain USER-only rather than being rewritten as a completed exchange. An action-only completed turn may also have no visible JIN text; its durable empty JIN row/timestamp is the completion marker.

**Why:** bootstrap continuity must reflect what actually happened.

---

## D014 — Historical timestamps are data, not render-time defaults

**Status:** Accepted / implementation must be protected

Serialize/deserialize must preserve entity/snapshot timestamps. `now()` is only a fallback for a truly legacy record with no timestamp.

**Why:** ordering, age, context relevance, and visible history become false if reload mutates time.

**Rejected alternative:** stamping restored rows with current time for convenience.

---

## D015 — Anonymous mode is an explicit empty room, not browser-private detection

**Status:** Accepted / implemented

Long-pressing the avatar opens a fresh JIN room with a generated `-anon` session id. The room gets only tab-scoped FRAME/Active/L-T/Delayed browser state, does not hydrate durable L-T/Delayed memory, and saves memory mutations only in its own tab-scoped snapshot. Global memory/asset writes remain restricted. Chat and reasoning remain auditable in ordinary `logs/` under the suffixed session id, while normal bootstrap and L-T freshness scanners ignore those logs.

**Why:** anonymous experimentation must not inherit or contaminate the durable memory room, and browser Incognito detection is not a reliable product primitive.

**Rejected alternative:** inferring browser private mode or maintaining a second `logs_anon` archive root.

---

## D016 — UI must reuse JIN's existing visual language

**Status:** Accepted / mandatory

Before adding a bubble, banner, highlight, tooltip, hover state, button, or feedback effect, find the closest existing JIN primitive and reuse it.

**Why:** color/glow/geometry already encode runtime semantics. Random new visuals create false meanings and make the system look like mixed UI kits.

**Explicitly rejected:** inventing a new blue/turquoise/green highlight just because a feature is new; generic SaaS success/error badges; cheerful icon sets; unnecessary blur.

---

## D017 — Loaded, referenced, inspected, pinned, paused, and deleted are distinct UI semantics

**Status:** Accepted / implemented in parts, regression-sensitive

Examples:

- full object loaded into prompt -> strong/active context signal;
- ID merely cited/referenced -> weak linked signal;
- modal opened -> inspect only, not context load;
- pin/unpin -> persistence/loading preference;
- pause -> excluded from context without delete;
- delete/restore -> lifecycle mutation.

**Why:** visual causality must match runtime causality.

**Rejected alternative:** calling one generic highlight routine on every UI interaction.

---

## D018 — UI interaction language should converge, not proliferate

**Status:** Accepted / partially implemented

Memory/file items use a shared interaction language where applicable: long press for delete, half-long pause, click to restore/pending/open according to the existing component semantics.

**Why:** fewer special-case controls and a more coherent object language.

**Rejected alternative:** adding a separate conventional delete button to every item while the gesture contract already exists.

---

## D019 — Consecutive JIN visual actions should read as one sequence

**Status:** Accepted / implemented

Consecutive color/size/position/speed actions should be visually sequenced rather than looking like unrelated mechanical phases. Position movement should ease in/out while respecting semantic speed.

Only adjacent/no-op repetitions in the same runtime-message scope are removed. Alternation such as red -> blue -> red must remain ordered, and a later message may intentionally request the same color again.

**Why:** the Live Avatar is a runtime expression channel, not four disconnected CSS toggles.

**Rejected alternative:** adding a second parallel animation engine when the existing sequence runner can be extended.

---

## D020 — Do not invent a second source of truth to fix restore/UI bugs

**Status:** Accepted / mandatory

For bootstrap, tint, timestamp, linked-highlight, and session bugs, first enumerate every writer and establish ordering.

**Why:** many prior regressions were duplicate-apply problems.

**Explicitly rejected:** second listeners, second tint writes, duplicate guards without identity analysis, render-time `Date.now()`, state-only hover payloads that never reach DOM.

---

## D021 — `CURRENT_RUNTIME_SETTINGS` is the absolute first optional prompt block

**Status:** Accepted / implemented

`rules/brain_context_builder.py` owns `CURRENT_RUNTIME_SETTINGS_CONTENT`. If it is empty, the block is omitted. If present, it precedes every other prompt section, including restore-specific instructions.

**Why:** this block is an explicit runtime-level override/context injector and must have deterministic placement.

---

## D022 — Keep heavy/background work off the foreground critical path where possible

**Status:** Accepted / implemented in principle

Optimization priority:

1. delete redundant calls;
2. safely combine calls without changing ordering;
3. cache stable results;
4. move non-required work to idle/background;
5. keep only causally required operations on the foreground path.

**Why:** chat latency is a product concern.

**Constraint:** never trade ordering, memory correctness, recoverability, or observability for fewer calls.

---

## D023 — No large framework rewrite before v1.0

**Status:** Accepted

The existing JIN skeleton already has state, named prompt sections, dynamic context, actions, continuity, pruning/tool-result handling, observability, and model roles.

**Why:** a framework migration before v1.0 creates risk without proving a product gain.

**Rejected alternative:** rewriting JIN around DeepSeek-style/other agent harnesses because their vocabulary looks similar.

---

## D024 — `FRAME` is the canonical product name for live runtime memory

**Status:** Accepted / implemented in product/docs; code naming cleanup is transitional

The first memory-panel tab is labelled `FRAME`, Brain context exposes it as `<FRAME_MEMORY_N>`, and current documentation uses FRAME for the live runtime-memory concept everywhere. It retains snapshot/diff paging and remains distinct from Active, Delayed, L-T, Files, and durable checkpoints.

Some source filenames, field names, tests, and compatibility readers still use the previous internal name. Those are migration/code-cleanup residue and must not be documented as a separate memory layer. Rename code only in an explicit cleanup task that traces storage/events/bootstrap compatibility end-to-end.

The memory panel always exposes exactly five tabs: `FRAME`, `ACTIVE`, `DELAYED`, `L-T`, and `FILES`. The temporary unprocessed-facts view is not part of this tab bar. The shared count/paging control sits below the active tab; arrows are visible only for `FRAME`.

---

## D025 — Header auto-hide behavior: delayed reveal, slower hide

**Status:** Accepted / code currently differs on reveal delay

Product intent recorded on 2026-08-21:

- reveal only after hover dwell of roughly 250 ms;
- hide roughly 1 s after leaving;
- reveal catch zone must not fire merely because the pointer passes over the avatar/panels.

Current code uses 333 ms reveal and 1000 ms hide. This mismatch is documented, not silently resolved here.

---

## D026 — Search actions require real configured provider capability

**Status:** Accepted / implemented

`WEB_SEARCH` and `DEEP_WEB_SEARCH` are model-visible only when both their runtime feature flags and `settings.CAN_SEARCH` allow them. For the current Serper integration, local capability means provider `serper` plus a non-empty, non-placeholder configured API key. The placeholder in `config.example.py` is configuration documentation, not an enabled capability.

**Why:** advertising an action that cannot execute creates fake affordance and failed loops. Conversely, Serper does not define a stable client-side key shape, so arbitrary length/prefix regexes can incorrectly hide valid credentials.

**Rejected alternatives:** feature flags alone deciding search availability; hard-coding guessed Serper key formats instead of letting the provider validate credentials.

---

## D027 — `CLEAN_TOOL_RESULTS` is an authoritative field-local tombstone, not a checkpoint refresh

**Status:** Accepted / implemented

Successful cleanup persists `session_snapshot.tool_results = []` in the existing browser checkpoint. That explicit empty value is authoritative during predecessor bootstrap and must not be repopulated from older archived tool results.

The cleanup must preserve the checkpoint's `saved_at`, lineage, and unrelated fields. `saved_at` is the freshness boundary used to decide whether archived dialogue/reasoning/session-actions/files are safe to mix into browser state; touching it for one cleared field can suppress the rest of bootstrap.

This exact-empty rule is intentionally scoped to `tool_results`. Empty `loaded_memory_ids` and `active_memory_records` retain their existing archive-fallback behavior.

**Rejected alternatives:** calling the full live-checkpoint persistence path after CLEAN; treating every empty collection as either universally authoritative or universally missing.

---

## D028 — Session-action interruption telemetry is emitted at cause time

**Status:** Accepted / implemented

Validator/reasoning loops and context/output-limit recovery must append and emit their session-action entry immediately when the interruption is detected, before automatic continuation/follow-up runs. `context_overflow` belongs to the context-limit recovery family.

**Why:** Session Actions is causal runtime telemetry. If the event appears only after the final answer, the UI gives a false ordering of what the runtime was doing.

**Rejected alternative:** recording the interruption only during end-of-turn/final response compaction.

---

## D029 — Structured Session Action metadata is continuity data

**Status:** Accepted / implemented

Bootstrap sanitization must preserve recognized structured action-part metadata required by the logger, not only human-readable text. For JIN_COLOR, `parts[].colors` round-trips through bootstrap and is normalized to lowercase `#rrggbb` so restored rows keep color swatches and hex hover text.

**Why:** text-only restoration can look superficially correct while silently destroying UI semantics after reload.

**Rejected alternative:** reducing persisted/restored action parts to `text/detail/message/id` when additional recognized metadata drives the existing projection.

---

## D030 — Surfaced L-T evidence expands; ordinary rows stay compact

**Status:** Accepted / implemented

The ordinary L-T panel uses a compact 50-character value preview. A fact bubbled by runtime reference, explicit reasoning citation, or context-loaded state displays the full value with no truncation.

**Why:** the panel should remain scan-friendly by default, while evidence JIN actually surfaced must be readable in full. The expansion is a UI projection and must not mutate canonical L-T storage/order.

**Rejected alternatives:** truncating surfaced citations; expanding every L-T row all the time.

---

## D031 — JIN color and size use paired XML at the model boundary

**Status:** Accepted / implemented with localized legacy compatibility

Canonical forms put payload in the body:

```text
<JIN_COLOR> #00f2ff </JIN_COLOR>
<JIN_SIZE> w:120 h:120 </JIN_SIZE>
```

Inline/colon/space forms may still be recognized by compatibility parsing, but contracts and prompt instructions teach only the paired form. Removing a marker must preserve ordinary visible answer text on both sides and across arbitrary stream chunk boundaries.

`JIN_SIZE` values preserve their declared unit across the model/parser/event boundary. Positive decimal `px`, `vw`, `vh`, and `%` values are supported; a missing unit means `px`. Relative units are resolved only in the live browser: `%` follows the corresponding width/height viewport axis, while `vw` and `vh` always follow viewport width and height. Persistence records the resulting rendered pixel geometry rather than the unresolved command.

**Why:** a real closing boundary prevents an inline marker parser from swallowing the answer tail and gives streaming one deterministic completion point.

**Rejected alternative:** advertising legacy `<JIN_COLOR: ...>` / `<JIN_SIZE ...>` as the preferred syntax.

---

## D032 — The newest real USER move owns normal continuation

**Status:** Accepted / implemented

The common browser checkpoint identifies the last runtime session that actually moved. Opening a tab may clone inherited FRAME but does not promote the new runtime ID. A real USER send may promote the session before a visible answer finishes; a server completed-turn commit is the fallback signal. A blank bootstrap-only tab never outranks its predecessor.

Raw-log selection follows the same rule: the newest real USER move wins even when it is interrupted and has no JIN row. `conversation_committed_at` remains a separate completed-turn timestamp.

**Why:** continuity follows the conversation the user actually touched, not whichever tab most recently initialized or flushed background state.

**Rejected alternatives:** newest runtime ID wins; newest `saved_at` wins regardless of USER activity; dropping interrupted USER-only moves.

---

## D033 — Bootstrap has separate dialogue and runtime freshness clocks

**Status:** Accepted / implemented

Dialogue/reasoning freshness is decided by comparing browser and archive recent-turn tails. Runtime/resource archive enrichment continues to use checkpoint `saved_at`. Field-local room/color/tool-result writes preserve checkpoint freshness metadata.

Session actions use stable identity plus timestamp ordering: the common checkpoint owns actions at or before its save boundary, and raw logs contribute only a newer tail unless the authoritative source session itself changes.

**Why:** a fresh runtime clone or room write must not block a newer raw dialogue tail, while an old archive must not overwrite newer browser runtime/resource state.

**Rejected alternative:** one global timestamp deciding every bootstrap field.

---

## D034 — JIN color has one checkpoint and one bootstrap reconciliation path

**Status:** Accepted / implemented

Accepted JIN_COLOR updates `RuntimeContext.jin_color`, emits the live visual event, records an ordered raw runtime event, and is folded into the common session snapshot/room state. There is no separate latest-color storage key.

On normal boot, the common local checkpoint color is applied during early room restore. The server then sends one authoritative color on `session_actions_update` with `bootstrap_restore=true`. Same-source browser color wins; structured action/raw archive color is fallback. A source change discards the stale browser color with the rest of that source.

The first bootstrap color uses the one 2-second avatar-and-scene transition. Later/live colors use 333 ms. Field-local color reconciliation may write across the fresh-tab/common-checkpoint ID mismatch only while preserving checkpoint ID, lineage, and `saved_at`.

**Why:** this removes the pink/gray/red flash-and-revert class caused by multiple color owners and late writers.

**Rejected alternatives:** `latestJinColor`, `colorOnly` checkpoints, a client source-scanning resolver, a second tint-shift helper, or a delayed color queue.

---

## D035 — Normal bootstrap shows a bounded inherited chat tail

**Status:** Accepted / implemented

Normal bootstrap renders the three newest real USER moves with JIN/reasoning where present, then places the current-session date divider and starts the live viewport there. USER-only turns remain visible without an empty JIN bubble. Explicit archived restore uses its own history renderer but projects the same bounded USER-owned tail, keeps later visible JIN-only continuation rows, and must not duplicate the normal-bootstrap tail. Its reasoning bubbles contain the reasoning body, not archive-file headers.

For explicit URL restore, the server archive owns dialogue, reasoning, and FRAME as one causal bundle. A same-session browser checkpoint can recover presentation state (room/avatar and Session Actions), but cannot replace individual conversation fields inside that bundle. `RESTORED_SESSION_DIALOG` is the newest conversation authority during the one-shot priming turn; restored FRAME is background and may be one update behind the final visible turn.

**Why:** the user can scroll slightly upward for immediate continuity while the current response begins from a clean, stable boundary.

**Rejected alternatives:** starting with an empty chat; dumping the whole archive; auto-scrolling inherited history below the current-session boundary.

---

## D036 — Recent model dialogue is bounded by pairs, not character-cropped

**Status:** Accepted / implemented

`<PREVIOUS_CHAT_MESSAGES>` contains the newest three recent USER/JIN pairs. Every selected message body is preserved in full after newline normalization, literal `\\n` serialization, whitespace trimming, and XML escaping. There is no per-message character cap.

**Why:** pair-count bounding already limits history breadth; silently cutting the substance of one selected message breaks exact conversational continuity.

**Rejected alternative:** restoring `RECENT_MESSAGE_MAX_CHARS` or an equivalent hidden per-message slice without an explicit prompt-budget decision and regression coverage.

---

## D037 — Ordinary turns retain the previous completed reasoning edges

**Status:** Accepted / implemented

An ordinary user turn includes the previous successful reasoning in `<PREVIOUS_REASONING_CONTENT>`. The projection preserves the whole block through 2000 characters; for a larger block it keeps the first and last 25% and replaces only the middle with an explicit `CUTTED N chars` separator.

Action/recovery follow-ups do not append this ordinary block again. They construct the relevant current-turn or loop-recovery reasoning context explicitly.

**Why:** the opening and conclusion preserve the previous line of thought without spending the entire context window on its middle, while dedicated follow-up context avoids stale or duplicated reasoning.

**Rejected alternatives:** exposing previous reasoning only during session-restore priming; dropping the block from ordinary turns; duplicating it inside action/recovery follow-ups; trimming only one edge.

---

## D038 — Memory Attention replaces metabolism

**Status:** Accepted / implemented

The metabolism subsystem is removed. The retained `runtime/memory_attention.py` module performs only prompt-local Active lexical/context relevance, Delayed inventory bubble matching, and a narrow 1–3 fact L-T focus.

Memory Attention is deterministic and stateless: it does not call SERVICE, change Brain temperature, generate hidden instructions, learn phrase associations, mutate memory while building context, persist significance, or drive avatar chemistry.

**Why:** the useful behavior was retrieval/ranking. The causal homeostat duplicated model work, obscured sampling, and leaked event-wide significance through FRAME into durable L-T.

**Rejected alternatives:** keeping observer-only chemistry; keeping significance as an independent durable score; preserving the metabolic UI without the backend.

---

## D039 — Browser runtime continuity has one atomic checkpoint

**Status:** Accepted / implemented

Normal browser continuity uses exactly `jin.liveRuntimeMemory.v2` in `sessionStorage` and `jin.sessionCheckpoint.v2` in `localStorage`. The live record is page-ephemeral and survives only soft WebSocket reconnect. Page execution clears it before bootstrap. Reload and new tabs read the one durable checkpoint, then hydrate only an ephemeral live record; there are no durable per-session FRAME records and no freshness scan.

The durable checkpoint atomically stores session lineage, save/commit times, runtime memory and update count, runtime snapshot, and session snapshot. Session CLEAR writes a version-2 cleared tombstone. Passive writers cannot replace it; only a successfully emitted new USER move authorizes a later checkpoint, and the clear boundary continues to reject a late pre-clear tab.

Legacy migration follows ownership rather than freshness: the common snapshot selects the session and may join only a matching saved runtime or its exact per-session record. A self-contained saved runtime is the only fallback without a common snapshot. Orphan per-session records are cleared. Legacy data is deleted only after a successful v2 write, and anonymous mode does not inspect normal-profile state.

Explicit archived restore keeps dialogue, reasoning, and FRAME under server-archive ownership. A same-ID, fresh local v2 checkpoint may contribute only presentation state.

**Why:** one atomic owner eliminates torn SAVE pairs, stale-key resurrection, ambiguous newest-record selection, and hidden bootstrap sources while preserving soft reconnect.

**Rejected alternatives:** split saved-runtime/saved-session keys; durable per-session FRAME keys; newest-timestamp scans; physical deletion without a multi-tab tombstone; automatic `saved_runtime.txt` fallback.

---

## D040 — Brain is the only foreground model route

**Status:** Accepted / implemented with localized legacy readers

Foreground user work always follows:

```text
user -> AgentRuntime -> BrainNode -> clients["brain"]
```

SERVICE is a logical background role only. `clients/registry.py` aliases `clients["service"]` to the Brain client by default; an explicitly configured `SERVICE_API_BASE` replaces only that background client with a dedicated runtime. Foreground routing does not depend on Service availability or configuration.

`USE_SERVICE_AS_BRAIN` is not a current runtime option. It is accepted only as old-config migration input: the loader promotes the legacy Service endpoint/settings into canonical Brain settings, clears the dedicated Service URL, removes the flag, and exposes normalized Brain-first configuration to the rest of the process. Launcher detection exists only to preserve this migration during startup.

Archived `service` message roles, `RUNTIME_MODE=SERVICE`, and old `[SERVICE]` model-output logger cards may remain as reader compatibility until real historical data no longer needs them. They must not be used to reintroduce foreground Service execution.

**Why:** the visible model path needs one canonical owner. A one-model installation should be possible without role inversion, while a second machine/model can still accelerate background memory/research work.

**Rejected alternatives:** switching visible replies to Service; keeping `USE_SERVICE_AS_BRAIN` as a live runtime branch; requiring a dedicated Service endpoint; treating archived Service labels as evidence of current topology.

---

## D041 — Memory inspector edits values, never identity

**Status:** Accepted / implemented

Direct memory editing is an explicit UI/runtime write, not a model action. Double-click opens the existing details tooltip as an editor. FRAME permits edits only on the newest snapshot value; Active permits the conditions/value while preserving ID, custom fields, status and metadata; L-T permits only the canonical fact value while preserving key, ID, category, provenance and mention metadata. Keys and IDs are never editable.

Drafts remain page-local until the server acknowledges the checkmark. Requests carry `expected_value` so stale concurrent edits fail rather than overwrite newer state. Rollback returns to the last acknowledged value. Active and L-T successful edits surface `updated_at`; L-T writes persist before publication and mark explicit-edit protection.

**Why:** the inspector should allow surgical correction without turning editing into a second schema/action system or rewriting memory identity.

**Rejected alternatives:** editable keys/IDs; editing historical FRAME snapshots; optimistic overwrite without expected-value conflict detection; routing manual edits through Brain.

---

## D042 — L-T recall decays by last real mention

**Status:** Accepted / implemented

Canonical L-T facts retain `mention_count` and `last_mentioned_at`. A valid `F<number>` reference in JIN reasoning or visible output increments a canonical fact at most once per turn and persists the new mention timestamp. Historical-log backfill may repair older mention dates but must never rewind a newer live mention.

For Brain context, a fact remains fully expanded until 24 hours have elapsed since its latest mention/update/create fallback. After that boundary, each sentence is previewed at a maximum of 100 characters. A later JIN reference refreshes the mention timestamp so subsequent prompts can receive the full value again.

**Why:** old facts remain available without permanently spending full-context cost, while actually reused facts regain detail automatically.

**Rejected alternatives:** deleting old facts for context pressure; decaying canonical stored values; using render-time age without persisted mentions; model-generated importance scores.

---

## D043 — L-T active/all is a projection, not a second store

**Status:** Accepted / implemented

Facts absorbed by Delayed reports are hidden from the default active L-T view unless they are currently context-loaded. Anchor facts remain visible. Clicking the L-T count toggles `show all` / `show active`; the all view uses the same normal fact sorting and does not append archived rows as a separate block. Report-linked fact IDs remain clickable and open the existing Delayed report modal.

**Why:** report absorption should reduce panel/context noise without making facts disappear or creating a parallel archive store.

**Rejected alternatives:** physically moving absorbed facts to another store; appending hidden facts unsorted; losing report navigation when hidden facts are revealed.

---

## D044 — Composer attachment chips represent context attachment, not file ownership

**Status:** Accepted / implemented

Pinned persistent files attached to the outgoing message are projected as compact chips next to the composer. Click reuses the existing preview. Hold detaches/unpins the file from outgoing context. Detach does not delete the persistent file, and attachment changes do not open Console as a side effect.

**Why:** attachment state is temporary message/runtime context; persistent file ownership is a separate system.

**Rejected alternatives:** deleting the asset on detach; a second preview UI; automatic Console expansion merely because a file was attached.

---

## D045 — Failed runtime actions reuse the contract schema and remain incomplete

**Status:** Accepted / implemented

Each concrete runtime-action contract owns a separate human-readable `schema` list in addition to its rules. The same schema is used in model-facing instructions and in failed tool results. A failure is rendered as readable text with status/reason, supplied payload when relevant, and `Correct action schema:`; the shared failure follow-up explicitly tells Brain not to treat the action as completed.

**Why:** recovery should teach the model from the exact contract that rejected the payload instead of exposing raw JSON or duplicating schema text in error handlers.

**Rejected alternatives:** raw JSON failure blobs; independent error-only schemas; continuing the turn as though a failed state mutation succeeded.

---

## D046 — Response copy is an explicit control, not an invisible bubble gesture

**Status:** Accepted / implemented

Completed assistant output exposes `Copy all` under the avatar/message host. The previous invisible bubble utility gesture surface is removed. Answer-rating implementation may remain release-disabled in the codebase, but it does not own release interaction.

**Why:** copying should be discoverable and deterministic, and should not compete with text selection, inspection, or other long-press/double-click semantics.

**Rejected alternatives:** hidden double-click copy; long-hold replacement retry on the answer bubble; re-enabling rating merely to host utility gestures.

---

## D047 — Live Avatar L-T capacity expands by lanes without changing memory identity

**Status:** Accepted / implemented

L-T facts are projected to Live Avatar in lanes of at most 100 records. Additional facts create additional outer L-T rings; Active Memory is laid out beyond the outermost L-T lane and before the persistent-file ring. Memory-row hover reuses the existing avatar zoom/reference semantics.

**Why:** large durable stores must remain inspectable without overloading one ring or changing the underlying fact store.

**Rejected alternatives:** hiding facts solely because the first ring is full; creating a second L-T store per ring; overlapping Active/File rings; inventing a new hover highlight family for overflow lanes.

