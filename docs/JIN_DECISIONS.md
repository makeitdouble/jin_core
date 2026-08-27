# JIN Core Engine — Durable Decisions

**Decision baseline:** reconciled on 2026-08-26 against `jin_core(20260826-090339).zip` and the accumulated project context.

This file records product/architecture intent that should survive refactors. It is not a changelog and not a dump of historical experiments.

Status vocabulary:

- **Accepted / implemented** — intent and current code agree.
- **Accepted / transitional** — decision is current, but compatibility/old representation still exists.
- **Accepted / not fully implemented** — product decision exists, but current source does not completely realize it.
- **Rejected** — do not reintroduce without an explicit new decision.

---

## D001 — The runtime is the product

**Status:** Accepted / implemented

JIN Core Engine is a model-agnostic cognitive runtime. BRAIN/SERVICE model choices are configuration, not architecture.

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

- live L1/runtime frame;
- L4 durable facts;
- Active Memory;
- Delayed Memory;
- Files;
- runtime/session checkpoints.

**Why:** L2/L3 created overlapping ownership and stale conceptual layers after newer continuity/memory mechanisms evolved.

**Rejected alternative:** resurrecting L2/L3 because old README/tests are more complete than current docs.

---

## D005 — Durable L1 is rejected; durable facts go to L4

**Status:** Accepted / implemented

L1 is live/operational state. Durable user/project facts belong in L4 rather than a persistent L1-like layer.

**Why:** one durable fact owner is easier to reconcile, inspect, age, link, and clean.

**Rejected alternative:** another long-lived “live memory” store parallel to L4.

---

## D006 — Memory systems remain purpose-specific

**Status:** Accepted / implemented

Active Memory, Delayed Memory, L4, live L1, Files, and checkpoints are not interchangeable layers.

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

## D015 — Anonymous/shadow mode can read durable context but restricts persistent writes

**Status:** Accepted / implemented

Anonymous windows keep isolated session-facing state while still being able to read global durable context where intended. Persistent L4/Delayed/asset mutation is restricted by the backend.

**Why:** private experimentation should not contaminate durable user memory, while still keeping JIN useful.

**Rejected alternative:** either making anonymous mode completely blind or letting it silently mutate global stores.

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

## D024 — `FRAME` is the preferred conceptual direction over generic `STATE`, but rename is not automatic

**Status:** Accepted / not fully implemented

The owner prefers `FRAME` for the concrete question -> answer -> live-context cycle because `STATE` is too broad.

**Constraint:** do not perform a blind RUNTIME/STATE -> FRAME rename. First identify the exact UI label and its semantic scope.

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

## D030 — Surfaced L4 evidence expands; ordinary rows stay compact

**Status:** Accepted / implemented

The ordinary L4 panel uses a compact 50-character value preview. A fact bubbled by runtime reference, explicit reasoning citation, or context-loaded state displays the full value with no truncation.

**Why:** the panel should remain scan-friendly by default, while evidence JIN actually surfaced must be readable in full. The expansion is a UI projection and must not mutate canonical L4 storage/order.

**Rejected alternatives:** truncating surfaced citations; expanding every L4 row all the time.

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

The common browser checkpoint identifies the last runtime session that actually moved. Opening a tab may clone inherited L1 but does not promote the new runtime ID. A real USER send may promote the session before a visible answer finishes; a server completed-turn commit is the fallback signal. A blank bootstrap-only tab never outranks its predecessor.

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

For explicit URL restore, the server archive owns dialogue, reasoning, and L1 as one causal bundle. A same-session browser checkpoint can recover presentation state (room/avatar and Session Actions), but cannot replace individual conversation fields inside that bundle. `RESTORED_SESSION_DIALOG` is the newest conversation authority during the one-shot priming turn; restored L1 is background and may be one update behind the final visible turn.

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

Action/recovery follow-ups do not append this ordinary block again. They construct the relevant current-turn or loop-recovery reasoning context explicitly, and the visible TODO context snapshot follows the same distinction.

**Why:** the opening and conclusion preserve the previous line of thought without spending the entire context window on its middle, while dedicated follow-up context avoids stale or duplicated reasoning.

**Rejected alternatives:** exposing previous reasoning only during session-restore priming; dropping the block from ordinary turns; duplicating it inside action/recovery follow-ups; trimming only one edge.

---

## D038 — Memory Attention replaces metabolism

**Status:** Accepted / implemented

The metabolism subsystem is removed. The retained `runtime/memory_attention.py` module performs only prompt-local Active lexical/context relevance, Delayed inventory bubble matching, and a narrow 1–3 fact L4 focus.

Memory Attention is deterministic and stateless: it does not call SERVICE, change Brain temperature, generate hidden instructions, learn phrase associations, mutate memory while building context, persist significance, or drive avatar chemistry.

**Why:** the useful behavior was retrieval/ranking. The causal homeostat duplicated model work, obscured sampling, and leaked event-wide significance through L1 into durable L4.

**Rejected alternatives:** keeping observer-only chemistry; keeping significance as an independent durable score; preserving the metabolic UI without the backend.
