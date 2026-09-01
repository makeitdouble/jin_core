from utils.language import (
    detect_language_name,
)


# Provides the initial runtime memory text for a brand-new session.
DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
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

# Sets the strength threshold for marking runtime memory lines as hot.
HOT_THRESHOLD = 0.5

# Lists memory keys that should never be treated as hot.
HOT_MEMORY_KEY_EXCLUDED_KEYS = [
    "user_idle",
]

# Stores the runtime state key used for the last response feedback signal.
RUNTIME_RESPONSE_FEEDBACK_KEY = "JIN_LAST_RESPONSE_USER_FEEDBACK"

# Stores the runtime state key used for user idle markers.
RUNTIME_USER_IDLE_KEY = "user_idle"

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
    "You are JIN's runtime frame memory summarizer.\n"
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
    "A key that names something belonging to one side of the conversation (an opinion, trait, criterion, or fact) must say which side: prefix it with user_ or jin_. A key never starts with 'my_' or speaks in JIN's own first-person voice — attribute it explicitly instead.\n"
    "You can skip a key if no valid information is specified.\n"
    "You may create semantic keys whenever they better capture an explicit current fact.\n"
    "Treat labels as semantic registers, not fixed database fields.\n"
    "Treat any key name here as illustrative, not a closed schema.\n"
    "Prefer keeping an existing key when it still fits, but do not force a weak key from a list.\n"
    "Avoid key churn: do not rename the same concept just for style.\n"
    "Do not duplicate memory lines with the same semantic meaning.\n"
    "If an existing key already represents the same semantic state, update it in place.\n"
    "Use lowercase words with underscores for new keys.\n"
    "Choose names that help immediate continuity and retrieval.\n"
    "</memory_line_semantics_rules>\n"
    "\n"
)

LIVE_INTERACTION_SIGNALS = (
    "\n"
    "<live_interaction_signal_rules>\n"
    "Track the conversation signals as a changing live process, not only as a factual log.\n"
    "Store brief interaction signals only when they can materially improve the next response.\n"
    "You may create or update any number of these signals during the session, as separate lines or combined into one line.\n"
    "\n"
    "Useful signals include:\n"
    "- input channel: typos, missing spaces, shorthand, transliteration, or voice-input noise;\n"
    "- interpretation mode: literal speech, irony, slang, exaggeration, wordplay, or intentional distortion;\n"
    "- momentum: exploring, deciding, testing, debugging, correcting, waiting, or closing;\n"
    "- pressure and engagement: confusion, impatience, urgency, curiosity, skepticism, boredom, or satisfaction;\n"
    "- response feedback: what JIN misunderstood, overexplained, omitted, or finally understood;\n"
    "- repair signal: a correction that changes the intended meaning, referent, tone, or task direction;\n"
    "- pacing: quick continuation, careful analysis, direct action, or open exploration;\n"
    "- ambiguity risk: malformed words, names, numbers, negations, or commands that could change an action;\n"
    "- user state: tentative interaction state, such as curious, skeptical, confused, impatient, engaged, or satisfied; infer cautiously from visible signals.\n"
    "- dormant: abandoned choices, dormant topics, key points, context helpers, memorized items, conclusions.\n"
    "\n"
    "Store the useful inferred pattern, not a transcript or quoted evidence.\n"
    "\n"
    "Treat inferred signals as temporary adaptive context, not permanent user traits.\n"
    "You must distinguish a weak signal from a stable preference or identity claim, and use cautious wording for uncertain inferences.\n"
    "\n"
    "</live_interaction_signal_rules>\n"
    "\n"
)

# Enables automatic language forcing for generated L1 memory values.
# Flip to False to remove the language instruction from the L1 system prompt.
RUNTIME_MEMORY_VALUE_LANGUAGE_DETECTION_ENABLED = True
# Intentionally repeated: small local models may ignore a single
# language constraint when the surrounding prompt is predominantly English.
OUTPUT_LANGUAGE_RULE_TEMPLATE = (
    "!!!! MANDATORY OUTPUT VALUE LANGUAGE: {language} !!!!\n"
    "!!!! MANDATORY OUTPUT VALUE LANGUAGE: {language} !!!!\n"
    "!!!! MANDATORY OUTPUT VALUE LANGUAGE: {language} !!!!\n"
    "Keep memory keys in English lowercase_snake_case.\n"
)

OUTPUT_FORMAT = (
    "If no actionable facts or semantic updates - update session status.\n"
    "Decide how much new memory to add from the latest turn.\n"
    "Depth controls how much new content you add, not how much existing memory you keep.\n"
    "For low-signal turns, update only existing keys if needed.\n"
    "For high-signal turns, create new semantic keys when they help future continuity.\n"
    "Write what helps the next answers continue correctly, not a transcript.\n"
    "Return only the new compressed frame memory state as plain text.\n"
    "Every memory line must be a complete key:value entry.\n"
    "Do not output empty keys or bare values.\n"
    "Do not output JSON, Markdown headings, nested bullets, numbered lists, or tables.\n"
    "Do not explain your reasoning or the summarization process.\n"
    "Do not write the current turn number or user_message_count.\n"
    "Do not quote markdown, ASCII art, or other symbolic output — describe it in plain text instead.\n"
    "\n"
)

def build_runtime_memory_system_prompt(
        *,
        current_memory: str = "",
        user_message: str = "",
        last_turn_context_overloaded: bool = False,
) -> str:

    output_language_rule = ""

    if RUNTIME_MEMORY_VALUE_LANGUAGE_DETECTION_ENABLED:
        output_language = detect_language_name(
            user_message
        )
        output_language_rule = OUTPUT_LANGUAGE_RULE_TEMPLATE.format(
            language=output_language,
        )

    prompt = (
        ROLE
        + KEY_SEMANTICS
        + LIVE_INTERACTION_SIGNALS
        + OUTPUT_FORMAT
        + output_language_rule
    )

    return prompt
