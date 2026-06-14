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
