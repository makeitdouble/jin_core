# Copy this file to config.py and adjust values for your local nodes.

USE_SERVICE_AS_BRAIN = True
TRANSLATION_ENABLED = False
TRANSLATE_RESPONSE = False
DEBUG_RULE_CITATIONS = True

# When True, a brain generation stopped by the model/context output limit
# continues immediately in an internal follow-up tick instead of ending the
# workflow and sending the interrupted turn straight to L1 memory.
FOLLOW_UP_ON_LIMIT = True

CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"

# Optional provider-native model metadata endpoint. LM Studio exposes the
# currently loaded context length here, unlike some OpenAI-compatible
# /v1/models responses. Leave empty to disable native metadata probing.
NATIVE_MODELS_ENDPOINT = "/api/v0/models"

# Large document attachments are transported through the existing WebSocket.
# Base64 adds overhead, so 64 MiB allows roughly 45 MiB source files.
WEBSOCKET_MAX_MESSAGE_BYTES = 64 * 1024 * 1024

# ---------------------------------------------------------
# TOKEN BUDGETING
# ---------------------------------------------------------

# Reserved context space kept free when calculating dynamic response budget.
# This prevents the request from filling the whole context window exactly.
RUNTIME_OUTPUT_TOKEN_RESERVE = 512

# When True, JIN prefers the loaded model limits reported by the runtime
# server (/v1/models or provider-native metadata) over local config values.
# When False, JIN uses *_CONTEXT_WINDOW from config.py only.
RUNTIME_CONTEXT_WINDOW_FALLBACK_TO_SERVER = True

# When True, JIN prefers server-reported max output tokens for normal
# model calls. If the server exposes no explicit output limit, JIN uses
# the detected loaded context window as the upper output cap and still
# applies the dynamic prompt + reserve budget. Per-call smaller caps are
# preserved. When False, JIN uses *_MAX_TOKENS from config.py only.
RUNTIME_MAX_TOKENS_FALLBACK_TO_SERVER = True

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

BRAIN_MAX_TOKENS = 8192

BRAIN_MAX_FOLLOWUPS = 50

# ---------------------------------------------------------
# SERVICE MODEL
# ---------------------------------------------------------

SERVICE_API_BASE = "http://service-host:1234"

SERVICE_MODEL_UID = "service-model"

SERVICE_REQUEST_TIMEOUT = 1000.0

SERVICE_CONTEXT_WINDOW = 4096

SERVICE_TEMPERATURE = 0.1

SERVICE_MAX_TOKENS = 4096

# ---------------------------------------------------------
# WEB_SEARCH
# ---------------------------------------------------------

SEARCH_PROVIDER = "serper"

SEARCH_SERPER_API_KEY = "mock-serper-api-key"

SEARCH_MAX_RESULTS = 5

SEARCH_TIMEOUT = 100.0

# ---------------------------------------------------------
# TRANSLATOR MODEL
# ---------------------------------------------------------

TRANSLATOR_API_BASE = "http://translator-host:1234"

TRANSLATOR_MODEL_UID = "translator-model"

TRANSLATOR_REQUEST_TIMEOUT = 120

TRANSLATOR_CONTEXT_WINDOW = 2048

TRANSLATION_RETRIES = 1

TRANSLATION_TEMPERATURE = 0.1

TRANSLATION_MIN_TOKENS = 64

TRANSLATION_MAX_TOKENS = 2048
