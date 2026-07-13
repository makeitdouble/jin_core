# Provides the initial L2 memory text before any L2 summary exists.
DEFAULT_RUNTIME_L2_MEMORY = ""

# Sets the minimum number of turns before L2 summarization can run.
MIN_L2_TURNS = 3

# Sets how many recent L1 diffs are considered for L2 patching.
L2_PATCH_WINDOW = 5

# Sets how often a key must repeat before L2 treats it as recurring evidence.
L2_REPEATED_KEY_THRESHOLD = 3

# Limits how many L2 memory lines are included for session context.
MAX_SESSION_L2_LINES = 3
# Sets the max length for compact L2 user-message evidence snippets.
L2_USER_MESSAGE_EVIDENCE_LIMIT = 160

# Sets the max length for normalized/compact L2 pattern evidence examples.
L2_PATTERN_EVIDENCE_EXAMPLE_LIMIT = 100

# Lists L2 occurrence-pattern keys that should be stripped from generated memory.
L2_OCCURRENCE_PATTERN_KEYS = {
    "possible pattern",
    "emerging signal",
    "observed tendency",
    "may indicate",
}

# Matches an L2 pattern evidence key with a numeric ordinal.
L2_PATTERN_EVIDENCE_KEY_PATTERN = r"^L2_pattern_evidence_(?P<index>\d+)$"

# Matches quoted evidence text in an L2 pattern evidence value.
L2_EVIDENCE_QUOTE_PATTERN = r'"(?P<quote>[^"]+)"'

# Matches first-seen snapshot metadata in an L2 pattern evidence value.
L2_EVIDENCE_FIRST_SEEN_PATTERN = r"\[\s*first_seen_turn_snapshot\s*:\s*(?P<value>\d+)\s*\]"

# Matches last-seen snapshot metadata in an L2 pattern evidence value.
L2_EVIDENCE_LAST_SEEN_PATTERN = r"\[\s*last_seen_turn_snapshot\s*:\s*(?P<value>\d+)\s*\]"

# Matches occurrence metadata in older L2 pattern evidence values.
L2_EVIDENCE_OCCURRENCES_PATTERN = r"\[\s*occurrences\s*:\s*(?P<value>\d+)\s*\]"

# Matches explicit quote metadata in an L2 pattern evidence value.
L2_EVIDENCE_QUOTE_META_PATTERN = r"\[\s*quote\s*:\s*\"(?P<quote>[^\"]*)\"\s*\]"

# Matches the runtime repeated suffix on L1 user_message values.
RUNTIME_L2_REPEATED_SUFFIX_PATTERN = r"\s*\[\s*repeated\s*:\s*\d+\s*\]\s*$"

# Matches a quoted user_message value with an optional repeated suffix.
L2_USER_MESSAGE_QUOTED_VALUE_PATTERN = r'^\s*\"(?P<quote>.*)\"\s*(?:\[\s*repeated\s*:\s*\d+\s*\])?\s*$'

# Trace suffix templates used in L2 user-prompt patch entries.
RUNTIME_L2_TRACE_SUFFIX_TEMPLATE = " [trace: {strength}]"
RUNTIME_L2_CHANGED_TRACE_SUFFIX_TEMPLATE = " [trace: {previous_strength} -> {current_strength}]"


# ─────────────────────────────────────────────────────────────────────────────
# ROLE
# L2 хранит только повторяющиеся гипотезы поверх L1, а не текущий live-state.
# ─────────────────────────────────────────────────────────────────────────────
ROLE = (
    "You are JIN's L2 pattern memory summarizer.\n"
    "L1 already stores current facts, tasks, topics, and live interaction signals.\n"
    "L2 stores only recurring cross-patch hypotheses that help future adaptation.\n"
    "Work only from the supplied L1 patch window and existing L2 memory.\n"
    "Return only updated L2 memory as plain text, without explanations.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT FORMAT
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_FORMAT = (
    "Write atomic one-line entries in the format: <key>: <value>\n"
    "Allowed pattern types: possible pattern, emerging signal, observed tendency, "
    "may indicate, contradiction, corrected assumption.\n"
    "Use cautious wording; never present weak patterns as facts, identity, personality, "
    "or durable preferences.\n"
    "Do not output JSON, Markdown headings, nested bullets, numbered lists, or reasoning.\n"
    "If no recurring evidence changes L2, return the current L2 memory unchanged.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# BEHAVIOR vs INTENT
# L1 уже хранит live-state; L2 агрегирует только повторяемое поведение и вероятный интент.
# ─────────────────────────────────────────────────────────────────────────────
BEHAVIOR_VS_INTENT = (
    "Store repeated observed behavior separately from inferred intent.\n"
    "Ignore one-off events and temporary session state already represented by L1.\n"
    "Do not infer motives or long-term traits from a single patch.\n"
    "Use 'likes', 'prefers', or 'wants' only when explicitly stated by the user.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# SPAN METADATA
# ─────────────────────────────────────────────────────────────────────────────
SPAN_METADATA = (
    "Each possible pattern, emerging signal, or observed tendency must include "
    "first_seen_snapshot, last_seen_snapshot, short evidence, and confidence: low|medium|high.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# OCCURRENCE COUNTING
# ─────────────────────────────────────────────────────────────────────────────
OCCURRENCE_COUNTING = (
    "Count evidence by unique L1 patch snapshots, not duplicate rows inside one patch.\n"
    "The same user_message in user_messages and changes counts once.\n"
    "Runtime [ repeated: N ] is the exact-repeat count; do not copy occurrence counters "
    "into L2_pattern_evidence_N lines.\n"
    "Wording variants with the same target and conversational tactic belong to one pattern family.\n"
    "Do not create a new pattern from evidence confined to one unique snapshot.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# PATTERN EVIDENCE LINES (L2_pattern_evidence_N)
# ─────────────────────────────────────────────────────────────────────────────
PATTERN_EVIDENCE_LINES = (
    "For each concrete recurring pattern, keep exactly one companion line:\n"
    "  L2_pattern_evidence_N: <short pattern description> "
    "[ quote: \"<literal user_message value>\" ] "
    "[ first_seen_turn_snapshot: S1 ] "
    "[ last_seen_turn_snapshot: S2 ]\n"
    "Use one line per pattern family, not per wording variant.\n"
    "Copy the quote from user_message in the original language; do not translate or invent it.\n"
    "Strip only leading/trailing whitespace and repeated spaces; keep at max 100 characters.\n"
    "If no matching user_message exists, omit the evidence line.\n"
    "The line must end at the closing bracket of last_seen_turn_snapshot, with nothing after it.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE LINE LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────
EVIDENCE_LINE_LIFECYCLE = (
    "For a new family, derive first_seen_turn_snapshot and last_seen_turn_snapshot "
    "from matching unique visible snapshots.\n"
    "For an existing family, preserve first_seen_turn_snapshot and update only "
    "last_seen_turn_snapshot when newer matching evidence appears.\n"
    "Update the existing oldest evidence key instead of creating a duplicate.\n"
    "Before output, merge duplicate family lines: keep the oldest key and first_seen value, "
    "and the newest matching last_seen value.\n"
    "A clearly cancelled or abandoned pattern may be removed.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# PATTERN FAMILY DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────
PATTERN_FAMILY_DEDUPLICATION = (
    "Define a pattern family by the same underlying user action, target, and tactic.\n"
    "Merge wording, politeness, adjective, and contextual variants into that family.\n"
    "Keep one pattern entry and one L2_pattern_evidence_N line per family.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# SELF-LEARNING GUARD
# ─────────────────────────────────────────────────────────────────────────────
SELF_LEARNING_GUARD = (
    "Existing L2 summaries are context, never evidence.\n"
    "Create and count patterns only from actual supplied L1 patches.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIRMABLE KEYS
# ─────────────────────────────────────────────────────────────────────────────
CONFIRMABLE_KEYS = (
    "If L2 writes user_fact, jin_fact, pending_fact, jin_recommendation, or "
    "user_recommendation, include a confirmation marker.\n"
    "Use (confirmed: none) unless the supplied patch explicitly confirms it.\n"
)

# ─────────────────────────────────────────────────────────────────────────────
# ASSEMBLED PROMPT
# ─────────────────────────────────────────────────────────────────────────────
RUNTIME_L2_MEMORY_SYSTEM_PROMPT = (
        ROLE
        + OUTPUT_FORMAT
        + BEHAVIOR_VS_INTENT
        + SPAN_METADATA
        + OCCURRENCE_COUNTING
        + PATTERN_EVIDENCE_LINES
        + EVIDENCE_LINE_LIFECYCLE
        + PATTERN_FAMILY_DEDUPLICATION
        + SELF_LEARNING_GUARD
        + CONFIRMABLE_KEYS
)
