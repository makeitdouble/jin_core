# JIN Core Engine — Durable Decisions

**Decision baseline:** reconciled on 2026-08-23 against `jin_core(20260823-114203).zip` and the accumulated project context.

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

Stop/cancel/repetition/context-limit interruption must preserve separate lifecycle semantics. Partial reasoning/answer plus user silence must not be silently serialized as a normal finished exchange.

**Why:** bootstrap continuity must reflect what actually happened.

---

## D014 — Historical timestamps are data, not render-time defaults

**Status:** Accepted / implementation must be protected

Serialize/deserialize must preserve entity/snapshot timestamps. `now()` is only a fallback for a truly legacy record with no timestamp.

**Why:** ordering, age, metabolism, and visible history become false if reload mutates time.

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

**Status:** Accepted / implementation-specific

Consecutive color/size/position/speed actions should be visually sequenced rather than looking like unrelated mechanical phases. Position movement should ease in/out while respecting semantic speed.

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
