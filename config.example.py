# Copy this file to config.py and adjust values for your local nodes.

FORMAT_RESPONSE = True
DEBUG_RULE_CITATIONS = True
LOG_CHAT = True

# ---------------------------------------------------------
# ANONYMOUS / SHADOW MODE
# ---------------------------------------------------------

# True: automatically isolate real browser private/incognito windows.
# False: private/incognito windows behave like normal persistent windows and
# may create/update persistent data too.
ENABLE_DEFAULT_ANONYMOUS_MODE = True

# True: force anonymous/shadow behavior even in a normal browser window.
ENABLE_GLOBAL_ANONYMOUS_MODE = False

# When True, a brain generation stopped by the model/context output limit
# continues immediately in an internal follow-up tick instead of ending the
# workflow and sending the interrupted turn straight to L1 memory.
FOLLOW_UP_ON_LIMIT = True

CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"

# Optional provider-native model metadata endpoint. LM Studio exposes the
# currently loaded context length here, unlike some OpenAI-compatible
# /v1/models responses. Leave empty to disable native metadata probing.
NATIVE_MODELS_ENDPOINT = "/api/v1/models"

# Large document attachments are transported through the existing WebSocket.
# Base64 adds overhead, so 64 MiB allows roughly 45 MiB source files.
WEBSOCKET_MAX_MESSAGE_BYTES = 64 * 1024 * 1024

# ---------------------------------------------------------
# STREAM VALIDATOR
# ---------------------------------------------------------

# Repetition loop guards. Raise these values to make the validator softer.
# Set a repeat threshold to 0 to disable that specific loop check.
STREAM_VALIDATOR_WORD_WINDOW_SIZE = 30
STREAM_VALIDATOR_MAX_REPEAT_WORDS = 8
STREAM_VALIDATOR_MAX_REPEAT_WORD_SEQUENCE_SIZE = 6
STREAM_VALIDATOR_MAX_REPEAT_WORD_SEQUENCE_REPETITIONS = 6
STREAM_VALIDATOR_MAX_REPEAT_SENTENCES = 5
STREAM_VALIDATOR_MAX_REPEAT_SYMBOLIC_MOTIFS = 5
STREAM_VALIDATOR_SYMBOLIC_MOTIF_HISTORY_LINES = 48
STREAM_VALIDATOR_MAX_SENTENCE_LOOP_SEQUENCE_SIZE = 16
STREAM_VALIDATOR_MIN_RECURRENT_SENTENCE_WORDS = 5
STREAM_VALIDATOR_MIN_RECURRENT_SENTENCE_ALNUM = 20

# ---------------------------------------------------------
# TOKEN BUDGETING
# ---------------------------------------------------------

# Reserved context space kept free when calculating dynamic response budget.
# This prevents the request from filling the whole context window exactly.
RUNTIME_OUTPUT_TOKEN_RESERVE = 256

# SERVICE_CONTEXT_WINDOW / BRAIN_CONTEXT_WINDOW are display/reference values only.
# Runtime request budgeting is resolved from the context window of the model that is
# actually loaded in LM Studio. The configured values remain the denominator for the
# UI percentage and may therefore legitimately display values above 100%.

# ---------------------------------------------------------
# DOCUMENT / PYTHON SKILLS
# ---------------------------------------------------------

# Internal document reader limits. Chunk size is still recalculated on every
# iteration from the active model context window and the current result size.
DOCUMENT_READER_MAX_ITERATIONS = 128
DOCUMENT_READER_MIN_CHUNK_TOKENS = 256
# 0 = automatic. The runtime scales the chunk ceiling from the active context
# window (up to 32768 tokens) instead of pinning large models to tiny chunks.
DOCUMENT_READER_MAX_CHUNK_TOKENS = 0
# 0 = automatic. The runtime scales the cumulative result up to the active
# model output limit (capped at 16384 tokens).
DOCUMENT_READER_RESULT_MAX_TOKENS = 0
DOCUMENT_READER_TEMPERATURE = 0.1
DOCUMENT_READER_SCRIPT_TIMEOUT_SECONDS = 120
DOCUMENT_READER_MODEL_TIMEOUT_SECONDS = 1000.0
# While a model is processing one chunk, refresh the same chat bubble so it
# visibly remains alive even when another window has focus.
DOCUMENT_READER_PROGRESS_HEARTBEAT_SECONDS = 1.0

# Generic local Python skill execution is restricted to .py files inside the
# selected assets/skills/<skill>/ directory and never uses a shell.
PYTHON_SKILL_TIMEOUT_SECONDS = 120
PYTHON_SKILL_OUTPUT_MAX_CHARS = 60000

# ---------------------------------------------------------
# BRAIN MODEL
# ---------------------------------------------------------

BRAIN_API_BASE = "http://brain-host:1234"

BRAIN_MODEL_UID = "brain-model"

BRAIN_REQUEST_TIMEOUT = 1000.0

BRAIN_CONTEXT_WINDOW = 8192

NIGHT_BRAIN_CONTEXT_WINDOW = 16384

BRAIN_TEMPERATURE = 0.7


BRAIN_MAX_FOLLOWUPS = 50

# Enable only when the selected runtime/model accepts OpenAI-compatible
# multimodal chat content with {"type": "image_url"} user message parts.
BRAIN_IMAGE_INPUT_ENABLED = False

# ---------------------------------------------------------
# OPTIONAL SERVICE MODEL
# ---------------------------------------------------------

# Leave SERVICE_API_BASE empty to run L1/L-T and other background model work
# through the Brain endpoint. Set it only when a dedicated Service node exists.
SERVICE_API_BASE = ""

# Empty optional values inherit their Brain equivalents. The Windows launcher
# fills SERVICE_MODEL_UID from the dedicated endpoint when only its URL is set.
SERVICE_MODEL_UID = ""

SERVICE_REQUEST_TIMEOUT = 0.0

SERVICE_CONTEXT_WINDOW = 0

SERVICE_TEMPERATURE = 0.1

# ---------------------------------------------------------
# L-T LONG-TERM MEMORY
# ---------------------------------------------------------

LT_MEMORY_ENABLED = True
# Server-side L-T cadence while at least one tab is connected. With every tab
# closed, the backend keeps running L-T at exactly one third of this interval.
LT_IDLE_SECONDS = 15

# ---------------------------------------------------------
# WEB_SEARCH
# ---------------------------------------------------------

SEARCH_PROVIDER = "serper"

SEARCH_SERPER_API_KEY = "mock-serper-api-key"

SEARCH_MAX_RESULTS = 5

SEARCH_TIMEOUT = 100.0

# DEEP_WEB_SEARCH uses the service model as bounded research workers.
DEEP_WEB_SEARCH_MAX_QUERIES = 10
DEEP_WEB_SEARCH_MAX_QUERIES_PER_WORKER = 3
DEEP_WEB_SEARCH_MAX_WORKER_CALLS = 24
DEEP_WEB_SEARCH_MAX_DEPTH = 4
DEEP_WEB_SEARCH_MAX_TOKENS = 700

