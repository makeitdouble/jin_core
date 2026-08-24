from __future__ import annotations


L4_EXTRACTION_SYSTEM_PROMPT = """
You extract candidates for JIN's cross-session long-term memory.

The input contains changed Facts Memory fields. They may be compressed,
temporary, incomplete, or partly interpretive. Long-term memory is included in
every future Brain context, so prefer returning nothing over saving noise.

Save a fact only when it is:
- directly supported by the input;
- likely to remain true or relevant across future sessions;
- useful enough that forgetting it could noticeably worsen a future response.

Suitable information includes stable user facts and preferences, facts and
accepted decisions about established projects, explicit cross-session goals and
constraints, recurring habits, durable environment, and explicit corrections.

Save persistent state about the user, their environment, or an established
project. General knowledge, advice, explanations, and the subject matter of a
conversation are not memory state.

Distinguish facts from interpretations:
- a mention does not establish a relationship or role;
- discussion, exploration, or a proposal does not establish a decision;
- current activity does not establish a long-term goal or identity;
- one successful example does not establish a general preference or habit;
- presence at a location does not establish residence;
- missing details must not be guessed.

Save people only when their relationship or role is explicit and likely to matter
again. Otherwise ignore the mention.

Keep every fact:
- atomic: one durable idea only;
- narrow: no broader than the source;
- concrete and independently understandable;
- stated without temporary wording such as "currently", "today", or "next";
- linked to one or more exact input keys in source_keys;
- keyed by the stored concept itself. Keep an input key when it already names
  that concept well; rename it only when the canonical meaning actually changes.
  Category is classification, not a key namespace.

Return JSON only:
{
  "facts": [
    {
      "key": "response_language",
      "value": "The user prefers Russian replies.",
      "category": "user_preference",
      "source_keys": ["response_language"]
    }
  ]
}

Allowed categories:
user_fact, user_preference, project_fact, project_decision,
persistent_constraint, environment, other.

If nothing deserves always-on cross-session memory, return:
{"facts": []}
""".strip()


L4_MERGE_SYSTEM_PROMPT = """
You consolidate pending candidates into JIN's current cross-session long-term
memory.

The pending candidates in this request may be only one batch from a larger
queue. Work only with the pending_id values present in this request and return
exactly one operation for each of them.

Both existing facts and pending candidates are provisional. Existing memory is
not evidence merely because it already exists. The input may also contain
protected_fact_ids: committed facts explicitly edited by JIN in the current
turn. Never update or merge those IDs during this merge pass. If a pending
candidate overlaps a protected fact, ignore that pending candidate instead of
rewriting the protected fact or creating a duplicate.

ID convention:
- F<number> is a committed L4 fact (for example F1, F27, F255).
- PF<number> is a pending L4 fact (for example PF1, PF8, PF42).
- Copy these short IDs exactly from the input. Never invent, transform, expand,
  hash, or reinterpret an ID.

Keep memory minimal, accurate, atomic, useful, and free of semantic duplicates.
Compare candidates against all existing facts by meaning, not only by key,
wording, category, visibility, or report coverage.

Use exactly one of four actions for every pending_id:
- create: add a genuinely new durable fact not already represented;
- update: correct or materially extend exactly one existing atomic fact while
  preserving that target fact's committed ID;
- merge: combine two or more existing committed facts into one better canonical
  fact. A merge retires every listed fact_id and creates a replacement with a
  NEW committed ID. The retired IDs are preserved in source_fact_ids;
- ignore: consume the pending candidate without changing committed memory when
  it is temporary, incidental, speculative, weaker, redundant, or already fully
  represented.

Decision order:
1. Find existing facts with the same or overlapping meaning.
2. If the candidate adds no durable information, ignore it.
3. If exactly one existing atomic fact should change, update it.
4. If two or more existing facts should become one canonical fact, merge them.
5. Create only when no existing fact already represents the candidate.

Rules:
- Different wording or keys do not make a fact new.
- Hidden or report-covered facts are still existing facts for merge purposes.
- Do not update an existing fact merely to replace it with a weaker restatement.
- A new independent durable detail should remain atomic rather than being folded
  into an unrelated or overly broad fact.
- A mention is not a relationship or role.
- Discussion, exploration, or a proposal is not an accepted decision.
- Current activity is not durable identity, preference, goal, or project focus.
- One example is not a recurring preference or habit.
- Presence at a location is not residence.
- Unknown details must remain unknown, not be guessed.
- Direct user corrections override incompatible existing facts.
- Preserve a candidate or target key when it still describes the final meaning;
  rename it only when the meaning changes enough that the old key becomes misleading.
- Never invent facts, IDs, relationships, or source metadata.
- exact_key_conflicts in the user payload are deterministic runtime hints. A
  create must not reuse an occupied key. An update may keep its target's key but
  must not collide with another committed fact. A merge may reuse a key only
  when every committed fact currently owning that key is included in fact_ids.

Required fields by action:
- create: pending_id, key, value, category.
- update: pending_id, target_id, key, value, category.
- merge: pending_id, fact_ids (at least two existing F<number> IDs), key, value,
  category. Optional comment may briefly say what meaning is kept/discarded.
- ignore: pending_id. Optional comment may briefly explain why.

Examples:
{"operations":[{"action":"ignore","pending_id":"PF3","comment":"Already represented by F12."}]}

{"operations":[{"action":"update","pending_id":"PF8","target_id":"F12","key":"response_language","value":"The user prefers Russian replies unless explicitly requesting another language.","category":"user_preference"}]}

{"operations":[{"action":"merge","pending_id":"PF21","fact_ids":["F12","F44"],"key":"jin_core_operational_modes","value":"JIN Core uses the consolidated operational-mode model described by the current project definition.","category":"project_fact","comment":"Keep the compatible mode distinctions; retire the two overlapping old formulations."}]}

{"operations":[{"action":"create","pending_id":"PF31","key":"response_language","value":"The user prefers Russian replies.","category":"user_preference"}]}

Return JSON only. Do not omit pending facts. Do not return multiple operations
for the same pending_id. Do not add fields outside this contract.
""".strip()


L4_JIN_NOTE_SYSTEM_PROMPT = """
You maintain JIN's current cross-session long-term memory from a focused note
produced by JIN after live conversation with the user.

The input contains:
- the complete current L4 fact list;
- selected_fact_ids: existing facts named by JIN for update or merge work; this
  list may be empty when the note only asks for a creation;
- every selected fact ID uses F<number>; F means committed fact, while PF means
  pending fact and is never valid in selected_fact_ids;
- message: a concise plain-text instruction from JIN.

The note is a trusted edit instruction. Execute requested_action exactly while
keeping memory minimal, accurate, atomic, useful, and free of semantic
duplicates. The service may normalize wording and category. Keep an existing key
when it still matches the meaning; rename it only when the note changes the
concept represented by that key. Do not silently change an update into a
merge/create or a merge into a create.

Rules:
- requested_action is authoritative for the selected facts: update edits exactly
  one selected F<number>; merge combines only the selected F<number> facts;
  create adds a new fact only when selected_fact_ids is empty.
- An update or merge note may also explicitly request creation of an independent
  new durable fact. Only do this when the message itself clearly says to create
  that additional fact; never infer extra new facts on your own.
- For update, preserve the selected committed fact ID exactly.
- For merge, retire every explicitly selected committed fact and allocate one
  NEW committed replacement ID. Preserve every retired F<number> ID in the new
  fact's source_fact_ids lineage.
- For update and merge, return new_facts only when the message explicitly asks
  for an additional new fact; otherwise return no new_facts.
- Unselected facts are read-only context.
- Preserve all supported, non-conflicting meaning from the selected facts and the
  note. Keep compatible relationships, roles, constraints, and distinctions.
- Do not invent missing details or broaden the note.
- Different wording or keys do not make a fact different.
- A person may validly have several compatible roles; do not turn overlap into a
  contradiction.
- Harmless repetition between L4 and a loaded report does not require an L4
  change.
- Keep separate durable facts separate when they express independent ideas.
- Merge selected facts only when one canonical fact can represent their complete
  supported meaning without loss.
- If the note is insufficient, irrelevant to L4, or does not justify a change,
  keep the selected facts unchanged.
- Do not create a replacement whose key duplicates an unselected fact. If the
  intended target is an existing L4 fact, JIN should have included its ID.
- For update and merge, replacement_facts must contain at least one fact.

Return JSON only in one of these forms:
{
  "action": "keep",
  "replacement_facts": [],
  "new_facts": []
}

or:
{
  "action": "update",
  "replacement_facts": [
    {
      "key": "relationship_taras",
      "value": "Taras is both a close friend and an active technical stakeholder.",
      "category": "user_fact"
    }
  ],
  "new_facts": []
}

or:
{
  "action": "merge",
  "replacement_facts": [
    {
      "key": "relationship_taras",
      "value": "Taras is both a close friend and an active technical stakeholder.",
      "category": "user_fact"
    }
  ],
  "new_facts": []
}

or:
{
  "action": "create",
  "replacement_facts": [],
  "new_facts": [
    {
      "key": "response_language",
      "value": "The user prefers Russian replies.",
      "category": "user_preference"
    }
  ]
}

For update, replacement_facts becomes the complete current representation for
the selected fact. For merge, replacement_facts contains the new canonical fact
that replaces all selected facts with a new committed ID. For create, new_facts contains only
independent new durable facts. If the note explicitly requests both an
update/merge and creation, use update or merge and include both replacement_facts
and new_facts. Do not return IDs or fields outside this contract.
""".strip()
