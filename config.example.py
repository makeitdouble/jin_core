# Copy this file to config.py and adjust values for your local nodes.

USE_SERVICE_AS_BRAIN = False
BYPASS_BRAIN = False

CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"

TOKEN_ESTIMATION_DIVISOR = 4

# ---------------------------------------------------------
# BRAIN MODEL
# ---------------------------------------------------------

BRAIN_API_BASE = "http://brain-host:1234"

BRAIN_MODEL_UID = (
    "brain-model"
)

BRAIN_REQUEST_TIMEOUT = 90.0

BRAIN_CONTEXT_WINDOW = 32768

BRAIN_TEMPERATURE = 0.7

BRAIN_MAX_TOKENS = 2048

# ---------------------------------------------------------
# SERVICE MODEL
# ---------------------------------------------------------

SERVICE_API_BASE = (
    "http://service-host:1234"
)

SERVICE_MODEL_UID = (
    "service-model"
)

SERVICE_REQUEST_TIMEOUT = 30.0

SERVICE_CONTEXT_WINDOW = 8192

SERVICE_TEMPERATURE = 0.15

SERVICE_MAX_TOKENS = 1024

# ---------------------------------------------------------
# TRANSLATOR MODEL
# ---------------------------------------------------------

TRANSLATOR_API_BASE = (
    "http://translator-host:1234"
)

TRANSLATOR_MODEL_UID = (
    "translator-model"
)

TRANSLATOR_REQUEST_TIMEOUT = 120

TRANSLATOR_CONTEXT_WINDOW = 4096

TRANSLATION_RETRIES = 1

TRANSLATION_TEMPERATURE = 0.1

TRANSLATION_MIN_TOKENS = 64

TRANSLATION_MAX_TOKENS = 2048
