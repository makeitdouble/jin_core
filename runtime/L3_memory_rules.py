# Provides the initial L3 session memory text before any session summary exists.
DEFAULT_RUNTIME_L3_SESSION_MEMORY = ""

# Sets the target maximum input token budget for L3 session summarization.
L3_INPUT_TOKEN_TARGET_MAX = 6000

# Reserves input tokens for prompt framing around L3 summarization content.
L3_INPUT_TOKEN_RESERVE = 768

# Limits output tokens for L3 session summarization.
L3_OUTPUT_MAX_TOKENS = 2048

# Limits how many prompt snapshots are kept in session memory context.
MAX_SESSION_PROMPT_SNAPSHOTS = 6

# Limits how many prompt diffs are kept in session memory context.
MAX_SESSION_PROMPT_DIFFS = 8

# Limits how many recent session events are included in memory context.
MAX_SESSION_PROMPT_EVENTS = 3

# Limits the text length for each captured session event.
MAX_SESSION_EVENT_TEXT_CHARS = 300

# Limits the total session memory text included in prompts.
MAX_SESSION_MEMORY_TEXT_CHARS = 1800

# Limits the latest memory text included in prompts.
MAX_SESSION_LATEST_MEMORY_TEXT_CHARS = 2200

# Limits older snapshot text included in prompts.
MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS = 500

# Limits the length of each generated session memory line.
MAX_SESSION_LINE_CHARS = 220
