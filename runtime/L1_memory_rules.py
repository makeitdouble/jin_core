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

# Describes how to react after the user disliked the last response.
RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE = (
    "User disliked your last response. "
    "Before answering, find and understand why it failed using context or memory, then start the next reply with a brief acknowledgement of that miss, then continue with a concrete corrected answer."
)

# Describes how to react after the user gave neutral feedback.
RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE = (
    "User gave neutral feedback to your last response. "
    "Continue carefully without changing course too much and treat it as a signal for response improvement."
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

# Defines stricter memory compression rules when context usage is high.
RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES = (
    "[CONTEXT PRESSURE OVERRIDE]\n"
    "Context usage is critically high.\n"
    "L1 must switch from normal summarization to survival compression.\n"

    "Rules:\n"
    "- Compress harder than usual.\n"
    "- Keep only information needed to continue the session after context loss.\n"
    "- Prefer durable state: decisions, active task, bugs, next steps, user preferences, project changes, unresolved risks, and active recall contracts.\n"
    "- Drop examples, jokes, emotional texture, repeated explanations, and wording that does not change future behavior.\n"
    "- Do not restate memory that already exists unless it changed.\n"
    "- Context pressure may shorten temporary state, but must not remove stored_memory, open_contract, countdown_contract, durable facts, pending contracts, unresolved implementation tasks, or explicit user decisions.\n"
    "- Merge related temporary details into fewer atomic key:value lines.\n"
    "- If a durable line is long, shorten its value without changing its meaning.\n"
    "- Use short values. No markdown. No commentary.\n"
)
