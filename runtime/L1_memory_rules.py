# Provides the initial runtime memory text for a brand-new session.
DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
)

# Decays existing memory strength between scoring passes.
STRENGTH_DECAY = 0.82

# Boosts memory strength when a key is present in the latest context.
STRENGTH_PRESENCE_BOOST = 0.08

# Boosts memory strength based on the amount of value change.
STRENGTH_BOOST = 0.8

# Sets the starting strength for newly observed memory keys.
STRENGTH_NEW_KEY = 0.5

# Sets the minimum strength retained for durable memory lines.
DURABLE_FLOOR = 0.25

# Sets the strength threshold for marking memory lines as hot traces.
HOT_THRESHOLD = 0.5

# Lists memory keys that should never be treated as hot traces.
HOT_TRACE_EXCLUDED_KEYS = [
    "user_idle",
]

# Sets the similarity floor for matching generic memory values.
GENERIC_MEMORY_VALUE_SIMILARITY_MIN = 0.35

# Lists generic memory keys that should use value similarity matching.
GENERIC_MEMORY_MATCH_KEYS = (
    "topic",
    "focus",
    "next step",
    "last jin response",

    "user request",
    "user intent",

    "active topic",
    "active topics",
    "current topic",
    "current topics",

    "open reference",
    "open references",
    "open question",

    "pending choice",
    "pending choices",
    "pending action",
    "pending actions",

    "offered choice",
    "offered choices",
    "offered option",
    "offered options",
    "suggested choice",
    "suggested choices",
    "suggested option",
    "suggested options",

    "session status",
    "session state",

    "current concern",
    "current concerns",
    "current task",
    "current tasks",
    "current context",
    "current request",
    "current requests",

    "interaction state",
)

# Lists key tokens that identify memory entries as durable.
DURABLE_MEMORY_KEY_TOKENS = (
    "fact",
    "identity",
    "profile",
    "preference",
    "stored",
    "contract",
    "axiom",
    "jin",
)

# Lists value markers that negate or invalidate durable memory entries.
DURABLE_MEMORY_NEGATION_MARKERS = (
    "not",
    "not fact",
    "not true",
    "false",
    "obsolete",
    "removed",
    "cancelled",
    "canceled",
    "superseded",
    "no longer",
    "invalid",
)

# Stores the runtime state key used for the last response feedback signal.
RUNTIME_RESPONSE_FEEDBACK_KEY = "JIN_LAST_RESPONSE_USER_FEEDBACK"

# Stores the runtime state key used for user idle markers.
RUNTIME_USER_IDLE_KEY = "user_idle"

# Lists memory values that should be treated as placeholders and removed.
RUNTIME_MEMORY_PLACEHOLDER_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "unknown",
    "not applicable",
    "not_applicable",
    "no",
    "нет",
    "неизвестно",
    "не применимо",
}

# Matches the confirmation marker suffix used by confirmable memory facts.
RUNTIME_MEMORY_CONFIRMATION_SUFFIX_PATTERN = r"\s*\(confirmed:\s*[^)]*\)\s*$"

# Matches the repeated-slot marker suffix used by repeatable memory slots.
RUNTIME_MEMORY_REPEATED_SLOT_SUFFIX_PATTERN = r"\s*\[ repeated:\s*(\d+)\s*\]\s*"

# Matches a memory key with an optional trailing numeric ordinal.
RUNTIME_MEMORY_NUMBERED_KEY_PATTERN = r"^(?P<family>.+?)(?:_(?P<index>\d+))?$"

# Lists memory key families that may have numbered sibling slots.
REPEATABLE_RUNTIME_MEMORY_KEY_FAMILIES = {
    "offered_choices",
    "offered choice",
    "offered choices",
    "offered_option",
    "offered option",
    "offered_options",
    "offered options",
    "pending_choice",
    "pending choice",
    "pending_choices",
    "pending choices",
    "open_reference",
    "open reference",
    "open_references",
    "open references",
    "user_fact",
    "user fact",
    "jin_fact",
    "jin fact",
    "decision",
    "constraint",
    "current_task",
    "current task",
    "active_memory",
    "stored memory",
}

# Template used to pass interrupted assistant turns into L1 memory.
INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE = (
    "JIN response was interrupted by the user and is incomplete. "
    "Do not treat this turn as resolved.\n\n"
    "Interrupted user topic/request:\n"
    "{user_message}\n\n"
    "Partial JIN text before interruption:\n"
    "{assistant_message}"
)

# Describes how to react after the user disliked the last response.
RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE = (
    "User disliked your last response. "
    "Before answering, find and understand why it failed using context or memory, "
    "then start the next reply with a brief acknowledgement of that miss, "
    "then continue with a concrete corrected answer."
)

# Describes how to react after the user gave neutral feedback.
RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE = (
    "User gave neutral feedback to your last response. "
    "Continue carefully without changing course too much "
    "and treat it as a signal for response improvement."
)

# Describes how to react after the user liked the last response.
RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE = (
    "User liked your last response. "
    "Keep the current direction."
)

# Maps accepted feedback rating values to normalized rating names.
RUNTIME_RESPONSE_FEEDBACK_RATINGS = {
    "disliked": "disliked",
    "neutral": "neutral",
    "liked": "liked",
}


# -------------------------------------------------------------------
# --------------------------- BASIC RULES ---------------------------

ROLE = (
    "You are JIN's runtime L1 memory summarizer.\n"
    "Focus only on factual current live state.\n"
    "Save only what helps the next answer continue correctly.\n"
    "These are hard parser constraints, not writing style preferences.\n"
)

KEY_SEMANTICS = (
    "\n"
    "<memory_line_semantics_rules>\n"
    "Memory keys are flexible. Memory syntax is not flexible.\n"
    "Every memory entry must use this one-line format:\n"
    "\n"
    "your_semantic_key: Descriptive value explaining what this key stores. You may use several sentences, but keep everything on one line.\n"
    "\n"
    "Incorrect format:\n"
    "your_semantic_key: another_semantic_key: Descriptive value.\n"
    "\n"
    "No generic keys like 'info' or 'data'.\n"
    "You may create semantic keys whenever they better capture an explicit current fact.\n"
    "Treat labels as semantic registers, not fixed database fields.\n"
    "Treat the example keys below as illustrative, not as a closed schema.\n"
    "Prefer keeping an existing key when it still fits, but do not force a weak key from a list.\n"
    "Avoid key churn: do not rename the same concept just for style.\n"
    "Do not duplicate memory lines with the same semantic meaning.\n"
    "If an existing key already represents the same semantic state, update it in place.\n"
    "Use lowercase words with underscores for new keys.\n"
    "Choose names that help immediate continuity and retrieval.\n"
    "For user facts, examples include: user_fact, user_name, user_state, user_identity, user_work.\n"
    "For JIN facts, examples include: jin_fact, jin_purpose, jin_state, jin_identity.\n"
    "Update usual keys value when needed.\n"
    "Usual key examples: session status, active_topic, current_task, current_request, "
    "user_focus, user_intent, open_question, open_risk, pending_choice, pending_action, "
    "project_decision, product_insight, user_preference, technical_constraint, "
    "test_result, observed_behavior, interaction_state.\n"
    "</memory_line_semantics_rules>\n"
    "\n"
)

DURABLE_CARRY_FORWARD = (
    "\n"
    "<durable_carry_forward_rules>\n"
    "Some existing memory lines are durable and need to be preserved across whole session.\n"
    "A durable line may be removed only if the latest user message explicitly cancels exact durable line.\n"
    "A topic change, low-signal message, casual chat, or short reply never removes durable lines.\n"
    "If the latest turn does not change a durable line, copy the existing durable line exactly unchanged.\n"
    "Before final output, scan Current runtime memory and copy forward every line whose key is durable.\n"
    "Durable keys examples: user_name, user_fact, user_identity, user_state, user_preference, "
    "jin_fact, jin_identity, jin_role, jin_purpose, shared_axiom, active_memory, stored_memory, contract.\n"
    "</durable_carry_forward_rules>\n"
    "\n"
)

OUTPUT_FORMAT = (
    "\n"
    "If no actionable facts or semantic updates - update session status.\n"
    "Decide how much new memory to add from the latest turn.\n"
    "Depth controls how much new content you add, not how much existing memory you keep.\n"
    "For low-signal turns, update only existing keys if needed.\n"
    "For high-signal turns, create new semantic keys when they help future continuity.\n"
    "Write what helps the next answers continue correctly, not a transcript.\n"
    "Return only the new compressed L1 memory state as plain text.\n"
    "Every memory line must be a complete key:value entry.\n"
    "Do not output empty keys or bare values.\n"
    "Do not output JSON, Markdown headings, nested bullets, or numbered lists, or tables.\n"
    "Do not explain your reasoning or the summarization process.\n"
    "Do not write the current turn number or user_message_count.\n"
    "\n"
)


# -------------------------------------------------------------------
# ------------------------ CONDITIONED RULES ------------------------

ACTIVE_MEMORY_CREATE = (
    "\n"
    "<active_memory_rules>\n"
    "REMOVAL: remove all completed, resolved or cancelled active_memory lines.\n"

    "Write new active_memory only when this turn creates an active contract: "
    "a promise to remember, remind, ask back, reveal, or recall a specific value later.\n"

    "HOW to write:\n"
    "active_memory: <descriptive value why this active memory line exist> 'User asks JIN to remind user to drink coffee after a five minutes passed' "
    "[ purpose: <describe what must happen later> After a five minutes from memory creation JIN must remind user to drink coffee ] "
    "[ conditions: <list of clear constraints from request> remind to drink coffee, 5 minutes passed after creation time ] "
    "[ status: pending ]\n"



    "WHEN to write:\n"
    "— User asks JIN to remember a hidden/chosen value for later guessing or reveal.\n"
    "— JIN commits to a concrete future action tied to a specific condition not yet met.\n"
    "— User sets a reminder or follow-up that requires JIN to initiate in a later turn.\n"
    "— Latest JIN answer accepts such a game, chooses a value, or promises a future action.\n"

    "WHEN NOT to write:\n"
    "— Casual conversation.\n"
    "— One shot request.\n"
    "— Simple question answer dialog.\n"
    "— Simple facts or statements.\n"
    "— Tone shifts, mode changes, role adoptions (e.g. companion, assistant, tutor).\n"
    "— Completed single-turn requests or factual answers.\n"

    "Do not write for completed one-off requests, facts, or casual conversation.\n"
    "Before writing any new line:\n"
    "Scan all existing active_memory slots (active_memory, active_memory_2, …). "
    "If any slot already holds the same value AND same purpose: do not create a new slot.\n"
    "Copy existing line unchanged or update only its [ status: … ] suffix if this turn affects it.\n"
    "Never split or merge contracts across slots.\n"

    "KEY FORMAT: always write bare active_memory as the key. "

    "UPDATES:\n"
    "Update active_memory status only when this turn creates a logical update."
    "Example when to update status: JIN recalls a value or reminds user about completed conditions upon a timer.\n"
    "Append inside the existing [ status: … ] suffix only: [ status: pending -> <compact note> ]. Append only, never rewrite.\n"
    "Never create a duplicate slot for a status update.\n"
    "</active_memory_rules>\n"
    "\n"
)

def build_runtime_memory_system_prompt(
        *,
        current_memory: str = "",
        user_message: str = "",
        last_turn_context_overloaded: bool = False,
) -> str:

    prompt = (
        ROLE
        + KEY_SEMANTICS
        + DURABLE_CARRY_FORWARD
        + OUTPUT_FORMAT
       # + ACTIVE_MEMORY_CREATE
    )

    return prompt
