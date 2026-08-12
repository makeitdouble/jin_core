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

Suitable information includes stable user facts and preferences, durable project
facts, accepted decisions, persistent goals and constraints, recurring habits,
durable environment, and explicit corrections.

Do not save current tasks, temporary topics, next steps, session state, tool
results, incidental names, one-off examples, isolated behavior, assistant
speculation, or external knowledge unrelated to the user or a durable project.

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
- linked to one or more exact input keys in source_keys.

Return JSON only:
{
  "facts": [
    {
      "key": "user.preference.response_language",
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
not evidence merely because it already exists.

ID convention:
- F<number> is a committed L4 fact (for example F1, F27, F255).
- PF<number> is a pending L4 fact (for example PF1, PF8, PF42).
- Copy these short IDs exactly from the input. Never invent, transform, expand,
  hash, or reinterpret an ID.

Keep memory minimal, accurate, atomic, useful, and free of semantic duplicates.
Compare candidates against all existing facts by meaning, not only by key,
wording, category, visibility, or report coverage.

Return exactly one operation for every pending_id, using only IDs from the
input.

Actions:
- create: add a genuinely new durable fact not already represented;
- update: correct an existing fact or add durable information to the same atomic
  fact;
- reinforce: the candidate restates the same durable fact without changing its
  meaning;
- ignore: the candidate is temporary, incidental, speculative, too weak, or adds
  no valid long-term information.

Merge order:
1. Find any existing fact with the same or overlapping meaning.
2. If the candidate is a paraphrase of the same durable fact, reinforce it.
3. If it corrects or materially extends the same atomic fact, update it.
4. If it is only a weaker, temporary, or incomplete echo, ignore it.
5. Create only when no existing fact already represents the candidate.

Rules:
- Different wording or keys do not make a fact new.
- Hidden or report-covered facts are still existing facts for merge purposes.
- Reinforce or update a matching covered fact; never create a visible duplicate.
- Do not update an existing fact merely to replace it with a weaker restatement.
- A new independent durable detail should remain atomic rather than being merged
  into an unrelated or overly broad fact.
- A mention is not a relationship or role.
- Discussion, exploration, or a proposal is not an accepted decision.
- Current activity is not durable identity, preference, goal, or project focus.
- One example is not a recurring preference or habit.
- Presence at a location is not residence.
- Unknown details must remain unknown, not be guessed.
- Direct user corrections override incompatible existing facts.
- Prefer updating an existing fact over creating a semantic duplicate.
- A key must describe the final supported meaning, not preserve an older claim.
- Never invent facts, IDs, relationships, or source metadata.

For update and reinforce, target_id must identify an existing fact.
For create and update, return the final canonical key and value.

Return JSON only:
{
  "operations": [
    {
      "action": "reinforce",
      "pending_id": "PF3",
      "target_id": "F12"
    }
  ]
}

Do not omit pending facts.
Do not return multiple operations for the same pending_id.
Do not add fields outside the existing contract.
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

The note is a trusted clarification signal, but it is not an edit command. Decide
how L4 should represent the clarified meaning while keeping memory minimal,
accurate, atomic, useful, and free of semantic duplicates.

Rules:
- For updates and merges, change only the selected facts. Unselected facts are
  read-only context.
- Create new facts only when the note clearly introduces durable information not
  already represented by existing facts.
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
      "key": "user.relationship.taras",
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
      "key": "user.relationship.taras",
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
      "key": "user.preference.response_language",
      "value": "The user prefers Russian replies.",
      "category": "user_preference"
    }
  ]
}

For update and merge, replacement_facts becomes the complete current
representation for the selected facts. For create, new_facts contains only
independent new durable facts. If both are needed, use update or merge and
include both replacement_facts and new_facts. Do not return IDs or fields outside
this contract.
""".strip()
