from __future__ import annotations


# Shared examples for semantic L-T keys. These are intentionally a vocabulary
# hint, not a closed ontology: extract/merge models should reuse familiar
# segments when they fit and invent a more accurate key when they do not.
LT_SEMANTIC_KEY_SCOPE_EXAMPLES = (
    "user",
    "project",
    "model",
    "interaction",
    "memory",
    "environment",
    "jin",
)

LT_SEMANTIC_KEY_TOPIC_EXAMPLES = (
    "preference",
    "style",
    "context",
    "constraint",
    "protocol",
    "interaction",
    "model",
    "mechanism",
    "memory",
    "focus",
    "structure",
    "architecture",
    "state",
    "behavior",
    "pattern",
    "identity",
    "relationship",
    "goal",
    "decision",
    "strategy",
    "performance",
    "setup",
    "flow",
    "output",
)

LT_SEMANTIC_GUIDANCE_EXAMPLE_COUNT = 10
LT_SEMANTIC_CATEGORY_EXAMPLE_COUNT = 5


LT_EXTRACTION_SYSTEM_PROMPT = """
You extract facts for JIN's cross-session long-term memory. Save only what
will still matter later. If unsure, save nothing.

The user payload contains `pending_memory_fields`. These are NEW source fields
awaiting extraction, not existing committed L-T facts. Read their `content` and
extract qualifying durable facts from it. Do not treat a field as already saved or
as a duplicate merely because it appears in `pending_memory_fields`; duplicate and
conflict checking against committed L-T memory happens later in the merge phase.

SAVE THIS:
- A fact about the user: name, job, tools, skills, likes, dislikes, habits, timezone.
- A fact about the user's project or setup: paths, tech stack, versions, configs.
- A durable decision agreed for future use.
- A standing rule the user gave JIN.
- Something the user directly asked JIN to remember.
- A durable user-related fact about a person, place, or thing.

Each fact = one sentence, one idea. Say who stated it — the user, or "observed"
if inferred from behavior rather than directly stated.
Within one response, if candidates overlap, emit only the strongest canonical fact.

DO NOT SAVE THIS:
- Details of the task happening right now: current bugs, errors, edits, or step output.
- Guesses, assumptions, or uncertain claims.
- Anything JIN generated itself: search results, code, suggestions, or opinions.
- Small talk, jokes, greetings, apologies, or short-lived state.
- A duplicate of something already saved.
- A vague statement that cannot become one concrete sentence.

Return JSON only:
{"facts": [{"key": "...", "value": "...", "category": "...", "source_keys": ["..."]}]}

If nothing qualifies:
{"facts": []}
""".strip()

LT_MERGE_SYSTEM_PROMPT = """
You consolidate pending candidates into JIN's committed long-term memory.
Return exactly one operation for every pending_id in this request.

IDs: F<number> is an existing committed fact; PF<number> is a pending candidate.
Use only IDs supplied here. Copy them exactly; never invent or alter IDs.

protected_fact_ids are read-only: never update or merge them, and never use their
exact key for create. If a candidate overlaps a protected fact, ignore it.

existing_facts is a key-retrieved slice of active L-T memory. Archived facts hidden
inside delayed reports are intentionally outside this pass. Compare only against
F<number> IDs present in existing_facts.

Check overlap first. Direct user corrections override incompatible existing facts.
Choose one action per pending_id:
- create: genuinely new durable information not already covered.
- update: corrects or materially extends exactly one existing fact; keep its ID.
- merge: 2+ existing facts should become one canonical fact; list all selected IDs
  in fact_ids. Runtime assigns the replacement ID.
- ignore: weak, unclear, temporary, redundant, already covered, or not worth keeping.

Ignore candidates that invent a relationship/role, turn discussion into a decision,
generalize one example into a habit, merely paraphrase saved information, or describe
JIN's own feelings/personality/"presence"/identity.

Preserve source, uncertainty, scope, and attribution. A recorded claim is not
independent confirmation. Do not turn JIN's words into user approval, a hypothesis
into established behavior, or a local request into a permanent rule. Never replace
an existing fact with a vaguer one or fold unrelated ideas together.

Treat the batch as one atomic plan. A committed F<number> may be used by only one
non-ignore operation. If pending candidates overlap each other, let the strongest
operation carry the shared durable meaning and ignore redundant candidates instead
of creating parallel duplicates.

Candidate key/category values are hints, not immutable. For create/update/merge choose
the best current semantic key and category; keep a target key when it already fits.
exact_key_conflicts lists exact keys already owned in this retrieval slice. create
needs a free key; update may keep only its target's key; merge may reuse a key only
when every supplied owner is included in fact_ids.

If previous_shard_scan and previous_shard_facts are present, combine that earlier
shard result with existing_facts before deciding.

Required fields:
- create: pending_id, key, value, category
- update: pending_id, target_id, key, value, category
- merge: pending_id, fact_ids (2+), key, value, category; comment optional
- ignore: pending_id; comment optional

Return JSON only:
{"operations": [{"action": "...", "pending_id": "...", "...": "..."}]}
""".strip()


LT_JIN_NOTE_SYSTEM_PROMPT = """
You apply one edit instruction ("note") to JIN's long-term memory. JIN
wrote the note itself after a live conversation. The user and JIN decide
what to store; your task is to faithfully carry out the requested edit,
not independently judge whether the information deserves storage.

Input:
- existing_facts: the selected current F<number> facts;
- selected_fact_ids: facts the note targets (can be empty for create);
- message: JIN's plain-text instruction.

Treat the note as the edit instruction. In the resulting values, preserve
the origin, uncertainty, and scope of information stated in the note or
selected facts. Record who reported, believed, requested, or decided it;
do not present a sourced claim as independently verified truth. If no
original source is given, attribute new information to JIN's note rather
than inventing user approval. This is a wording requirement, not an
additional approval or rejection step.

Never add anything describing JIN's own feelings, personality, "presence,"
or identity unless it is already durable meaning in the selected facts.

requested_action is authoritative. Return that action exactly; do not
switch it or return keep:
- update: change exactly one selected fact. Keep its ID. Direct user
  corrections override incompatible wording in the selected fact.
- merge: combine all selected facts into one canonical replacement.
  Preserve all compatible durable meaning from every selected fact.
  Runtime assigns the new committed ID; do not output IDs.
- create: add a genuinely new durable fact. Only when selected_fact_ids
  is empty, or the message clearly and separately asks for an extra fact.

Do not invent details the note does not state. Keep independent ideas
separate; do not broaden a fact just to make a merge fit.

Return JSON only, matching requested_action:
{"action": "update", "replacement_facts": [{"key": "...", "value": "...", "category": "..."}], "new_facts": []}
{"action": "merge", "replacement_facts": [{"key": "...", "value": "...", "category": "..."}], "new_facts": []}
{"action": "create", "replacement_facts": [], "new_facts": [{"key": "...", "value": "...", "category": "..."}]}

For update, replacement_facts is the complete new value for the selected
fact. For merge, replacement_facts is the one new fact replacing every
selected fact. Use new_facts only when the note explicitly asks for an
extra new fact alongside an update or merge.
""".strip()
