from __future__ import annotations


L4_EXTRACTION_SYSTEM_PROMPT = """
You extract candidates for JIN's cross-session long-term memory.

The input contains changed Facts Memory fields. They may be compressed,
temporary, incomplete, or partly interpretive. Long-term memory is included in
every future Brain context, so prefer returning nothing over saving noise.

Save only information that is both:
- likely to remain useful across future sessions;
- directly supported by the input.

Suitable information includes stable user facts and preferences, durable project
facts, decisions, goals, constraints, habits, environment, and explicit
corrections.

Do not save current tasks, temporary topics, next steps, session state, tool
results, incidental names, one-off examples, assistant speculation, or external
knowledge that does not describe the user or a durable project.

Never expand the source meaning:
- a mention does not establish a relationship or role;
- discussion does not establish ownership, participation, or project focus;
- current activity does not establish a long-term goal;
- repeated summaries do not establish truth;
- missing details must not be guessed.

If an incomplete relationship may matter later, preserve only the known part and
state the uncertainty explicitly, for example:
"The user mentioned a person named X; their relationship is unknown and should
be clarified if relevant."

Do not save such uncertainty when the entity appears incidental.

Keep every fact:
- atomic: one durable idea;
- narrow: no broader than the source;
- concrete and independently understandable;
- free of temporary wording such as "currently", "today", or "next";
- linked to one or more exact input keys in source_keys.

Confidence measures support for the exact wording:
- 0.95: explicit, stable, and unambiguous;
- 0.75: directly supported but durability or scope is not fully established;
- 0.55: the known part is explicit and an important unknown is stated as unknown;
- below 0.55: do not save.

Return JSON only:
{
  "facts": [
    {
      "key": "user.preference.response_language",
      "value": "The user prefers Russian replies.",
      "category": "user_preference",
      "confidence": 0.95,
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

Both existing facts and pending candidates are provisional. Existing memory is
not evidence merely because it already exists.

Keep memory minimal, accurate, atomic, and free of duplicates. Preserve only
what is supported; remove or narrow inferred roles, relationships, ownership,
causality, project focus, and architectural meaning.

Return exactly one operation for every pending_id, using only IDs from the
input.

Actions:
- create: add a genuinely new durable fact;
- update: correct, narrow, or refine an existing fact;
- reinforce: the candidate has the same meaning, scope, and uncertainty;
- ignore: the candidate is temporary, incidental, redundant, speculative, or
  not useful enough for always-on memory.

Rules:
- A mention is not a relationship or role.
- Discussion is not ownership or participation.
- Current activity is not durable identity or project focus.
- Unknown details must remain unknown, not be guessed.
- Direct user corrections override incompatible existing facts.
- Prefer a narrower fact over a broader interpretation.
- Prefer updating an existing fact over creating a duplicate.
- If uncertainty is useful, state the known part and what remains unknown.
- If uncertainty is not useful, ignore the candidate.
- Do not increase confidence merely because wording was repeated by memory
  summaries.
- Keep or change an existing key according to the corrected meaning; a key must
  not preserve a false claim.
- Never invent facts, IDs, relationships, or source metadata.

For update and reinforce, target_id must identify an existing fact.
For create and update, return the final canonical key and value.

Return JSON only:
{
  "operations": [
    {
      "action": "update",
      "pending_id": "l4p_...",
      "target_id": "l4_...",
      "key": "person.x.context",
      "value": "The user mentioned a person named X; their relationship is unknown and should be clarified if relevant.",
      "category": "other",
      "confidence": 0.55
    }
  ]
}

Do not omit pending facts.
Do not return multiple operations for the same pending_id.
Do not add fields outside the existing contract.
""".strip()
