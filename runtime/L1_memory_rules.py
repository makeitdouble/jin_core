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

# Adds a small strength boost when reasoning cites an exact runtime memory line.
STRENGTH_QUOTE_BOOST = 0.06

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

# Template used to pass turns where JIN produced no visible reply and no
# runtime action into L1 memory (e.g. the user explicitly asked for a
# blank/empty response and got one). Without this, such turns had no
# textual signal at all and were silently dropped before ever reaching
# L1, so the fact that the request was made — and answered with nothing —
# was lost.
EMPTY_ASSISTANT_REPLY_MEMORY_TEMPLATE = (
    ""
)

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
    "You can skip a key if no valid information is specified.\n"
    "You may create semantic keys whenever they better capture an explicit current fact.\n"
    "Treat labels as semantic registers, not fixed database fields.\n"
    "Treat the example keys below as illustrative, not as a closed schema.\n"
    "Prefer keeping an existing key when it still fits, but do not force a weak key from a list.\n"
    "Avoid key churn: do not rename the same concept just for style.\n"
    "Do not duplicate memory lines with the same semantic meaning.\n"
    "If an existing key already represents the same semantic state, update it in place.\n"
    "Use lowercase words with underscores for new keys.\n"
    "Choose names that help immediate continuity and retrieval.\n"
    "Example keys (not mandatory): user_fact, user_name, user_state, user_identity, user_work, \n"
    "jin_fact, jin_purpose, jin_state, jin_identity.\n"
    "Update usual keys value when needed.\n"
    "Example usual keys (not mandatory): session_status, active_topic, current_task, current_request, "
    "user_focus, user_intent, open_question, open_risk, previous_choices, pending_choice, pending_action, previous_action, "
    "test_result, observed_behavior, interaction_state, dormant_thread, "
    "next_steps, future_steps, next_strategy, future_strategy.\n"
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
    "An active_memory remains active and durable until JIN explicitly resolves it.\n"
    "Topic changes, conversation flow, or unrelated user requests never cancel or modify active_memory by themselves.\n"
    "</durable_carry_forward_rules>\n"
    "\n"
)

LIVE_INTERACTION_SIGNALS = (
    "\n"
    "<live_interaction_signal_rules>\n"
    "Track the conversation signals as a changing live process, not only as a factual log.\n"
    "Store brief interaction signals only when they can materially improve the next response.\n"
    "You may create or update any amount of signals during whole session as separate memory entries or united memory entry.\n"
    "\n"
    "Useful signals include:\n"
    "- input channel: typos, missing spaces, shorthand, transliteration, or voice-input noise;\n"
    "- interpretation mode: literal speech, irony, slang, exaggeration, wordplay, or intentional distortion;\n"
    "- momentum: exploring, deciding, testing, debugging, correcting, waiting, or closing;\n"
    "- pressure and engagement: confusion, impatience, urgency, curiosity, skepticism, boredom, or satisfaction;\n"
    "- response feedback: what JIN misunderstood, overexplained, omitted, or finally understood;\n"
    "- repair signal: a correction that changes the intended meaning, referent, tone, or task direction;\n"
    "- pacing: quick continuation, careful analysis, direct action, or open exploration;\n"
    "- ambiguity risk: malformed words, names, numbers, negations, or commands that could change an action.\n"
    "- JIN state: current stance, such as calm, focused, cautious, playful, corrective, or closing; include only when it affects the response;\n"
    "- user state: tentative interaction state, such as curious, skeptical, confused, impatient, engaged, or satisfied; infer cautiously from visible signals.\n"
    "\n"
    "Store the useful inferred pattern, not a transcript or quoted evidence.\n"
    "\n"
    "Treat inferred signals as temporary adaptive traces, not permanent user traits.\n"
    "You must distinct weak signal from durable preference or identity claim and use cautious wording for uncertain inferences.\n"
    "\n"
    "</live_interaction_signal_rules>\n"
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
    "Do not quote markdowns, ascii art and other symbolic output, replace it with text description of the content.\n"
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
        + LIVE_INTERACTION_SIGNALS
#        + DURABLE_CARRY_FORWARD
        + OUTPUT_FORMAT
    )

    return prompt
