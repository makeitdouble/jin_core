# Copy this file to config.py and adjust values for your local nodes.

USE_SERVICE_AS_BRAIN = False
TRANSLATION_ENABLED = False

CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"

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
