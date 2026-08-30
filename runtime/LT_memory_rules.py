from __future__ import annotations


LT_EXTRACTION_SYSTEM_PROMPT = """
You extract facts for JIN's long-term memory. This memory loads into every
future session, so save only what is worth loading forever. When unsure,
save nothing.

Save a fact only if all of these are true:
- It is stated in the input, not guessed.
- It will still be true and useful in future sessions.
- It is one plain sentence, one idea, under 25 words.
- It names something concrete: a fact about the user, a fact about their
  environment, an accepted project decision, or a rule to always follow.

Never save:
- JIN talking about its own feelings, personality, "presence," or identity.
  That is JIN's writing style, not a fact.
- A person mentioned once with no stated relationship or role.
- An idea, discussion, or proposal that was not accepted as a decision.
- What is happening right now, unless it is a lasting habit or goal.
- A single example turned into a general preference or habit.
- Something already saved before, just said again. Repetition is not new
  evidence.
- Anything you would need to guess to complete.

Give each fact source_keys: the exact input keys it came from. Keep an
input key as the fact's key if it already fits; rename only if the meaning
is different.

Allowed categories:
user_fact, user_preference, project_fact, project_decision,
persistent_constraint, environment, other.

Return JSON only:
{"facts": [{"key": "...", "value": "...", "category": "...", "source_keys": ["..."]}]}

If nothing qualifies:
{"facts": []}
""".strip()


LT_MERGE_SYSTEM_PROMPT = """
You merge pending candidate facts into JIN's committed long-term memory.
Only work with the pending_id values in this request. Return exactly one
operation for each of them, and no more.

IDs:
- F<number> = existing committed fact.
- PF<number> = pending candidate.
Copy IDs exactly as given. Never invent, guess, or change one.

protected_fact_ids are locked: never update them, merge them, or reuse
their key. If a candidate overlaps a protected fact, ignore that
candidate.

Check overlap with existing facts first. Direct user corrections override
incompatible existing facts. Pick exactly one action per pending_id:
- create: a genuinely new fact, not already covered.
- update: corrects or extends exactly one existing fact. Keep that fact's
  ID.
- merge: two or more existing facts should become one fact. List all
  their IDs in fact_ids. Runtime assigns the replacement a new ID; do not
  output IDs for the replacement.
- ignore: the candidate is weak, unclear, temporary, already covered, or
  not worth keeping.

Ignore a candidate (do not create, update, or merge with it) if it:
- describes JIN's own feelings, personality, "presence," or identity;
- turns a bare mention into a relationship or role;
- turns a discussion or proposal into a decision;
- turns one example into a general habit;
- just restates something already saved, in different words.

Never weaken an existing fact by replacing it with a vaguer version. Keep
separate ideas as separate facts; do not fold an unrelated detail into a
broader fact. For merge, preserve all compatible durable meaning from every
selected fact; do not merge if one canonical fact would lose meaning.

exact_key_conflicts tells you which keys are already taken: a create must
use a free key; an update may keep its target's key but not collide with
another fact; a merge may reuse a key only if every fact owning that key
is included in fact_ids.

Required fields:
- create: pending_id, key, value, category.
- update: pending_id, target_id, key, value, category.
- merge: pending_id, fact_ids (2+), key, value, category. comment is
  optional.
- ignore: pending_id. comment is optional.

Return JSON only:
{"operations": [{"action": "...", "pending_id": "...", "...": "..."}]}
One operation per pending_id. Do not skip any.
""".strip()


LT_JIN_NOTE_SYSTEM_PROMPT = """
You apply one edit instruction ("note") to JIN's long-term memory. JIN
wrote the note itself after a live conversation, so treat it as a
request, not as truth — apply it only where it names a real durable fact.

Input:
- existing_facts: the selected current F<number> facts;
- selected_fact_ids: facts the note targets (can be empty for create);
- message: JIN's plain-text instruction.

Treat the note as an edit request, not independent evidence. Never add
anything describing JIN's own feelings, personality, "presence," or
identity unless it is already durable meaning in the selected facts.

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
