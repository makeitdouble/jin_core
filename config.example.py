# Copy this file to config.py and adjust values for your local nodes.

# Runtime logs written to the local chat/runtime log store.
ENABLE_RUNTIME_LOGS = True

# ---------------------------------------------------------
# BRAIN MODEL
# ---------------------------------------------------------

BRAIN_API_BASE = "http://brain-host:1234"
BRAIN_MODEL_UID = "brain-model"
BRAIN_TEMPERATURE = 0.7
BRAIN_MAX_FOLLOWUPS = 50

# ---------------------------------------------------------
# OPTIONAL SERVICE MODEL
# ---------------------------------------------------------

# Leave SERVICE_API_BASE empty to run FRAME/L-T and other background model work
# through the Brain endpoint. Set it only when a dedicated Service node exists.
SERVICE_API_BASE = ""

# Empty optional values inherit their Brain equivalents. The Windows launcher
# fills SERVICE_MODEL_UID from the dedicated endpoint when only its URL is set.
SERVICE_MODEL_UID = ""
SERVICE_TEMPERATURE = 0.1

# ---------------------------------------------------------
# L-T LONG-TERM MEMORY
# ---------------------------------------------------------

# Server-side L-T cadence while at least one tab is connected. With every tab
# closed, the backend keeps running L-T at exactly one third of this interval.
LT_IDLE_SECONDS = 15

# ---------------------------------------------------------
# WEB SEARCH
# ---------------------------------------------------------

# Provider credentials are read from SEARCH_SERPER_API_KEY or
# JIN_SEARCH_SERPER_API_KEY in the process environment.
SEARCH_PROVIDER = "serper"
SEARCH_MAX_RESULTS = 5

# DEEP_WEB_SEARCH uses the service model as bounded research workers.
DEEP_WEB_SEARCH_MAX_QUERIES_PER_WORKER = 3
DEEP_WEB_SEARCH_MAX_WORKER_CALLS = 24
