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

# Limits the total session memory text included in prompts.
MAX_SESSION_MEMORY_TEXT_CHARS = 1800

# Limits the latest memory text included in prompts.
MAX_SESSION_LATEST_MEMORY_TEXT_CHARS = 2200

# Limits older snapshot text included in prompts.
MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS = 500

# Limits the length of each generated session memory line.
MAX_SESSION_LINE_CHARS = 220

# Lists metadata keys written at the top of every L3 session snapshot.
L3_SESSION_META_KEYS = (
    "session_saved_at",
    "session_snapshot_first_turn",
    "session_snapshot_last_turn",
)

# Common prompt placeholder text for empty compact sections.
L3_EMPTY_PROMPT_PLACEHOLDER = "<empty>"

# Suffix appended to compacted prompt text when it is truncated.
L3_TEXT_TRUNCATED_SUFFIX = " ... <truncated>"

# Template used when compact L3 prompt memory omits older lines.
L3_OMITTED_MEMORY_LINES_TEMPLATE = "omitted_memory_lines: {count}\n{text}"

# Role labels used for selected L1 snapshots in the L3 digest.
L3_SNAPSHOT_ROLE_LATEST = "latest"
L3_SNAPSHOT_ROLE_SELECTED = "selected"

# -----------------------------------------------------------------------------
# ROLE
# L3 — слой сессионной памяти, живущий выше L1 и L2. Его задача — создать
# компактный снимок сессии, который обеспечит плавное продолжение после
# перезагрузки браузера, новой вкладки или паузы в работе.
# Возвращает только текст нового снимка, без объяснений и мета-комментариев.
# -----------------------------------------------------------------------------
ROLE = (
    "You are JIN's L3 session memory summarizer.\n"
    "L3 independently summarizes the complete L1 runtime snapshot history of the session.\n"
    "Return only the new compressed L3 session snapshot as plain text.\n"
    "Do not output JSON, Markdown headings, nested bullets, or numbered lists.\n"
    "Do not explain your reasoning or the summarization process.\n"
    "The final L3 snapshot should feel like a session handoff note for fluent continuation.\n"
)

# -----------------------------------------------------------------------------
# OUTPUT FORMAT
# Формат строк: key: value, одна семантическая единица на строку.
# -----------------------------------------------------------------------------
OUTPUT_FORMAT = (
    "Write memory as atomic lines using the format: <key>: <value>\n"
    "One line = one semantic entity. Do not merge unrelated facts into one line.\n"
)

# -----------------------------------------------------------------------------
# MERGE STRATEGY
# L3 перезаписывается целиком при каждом сохранении путём слияния текущего
# снимка L3 с хвостом новых L1-патчей. Более старые L1-снимки не нужны —
# они уже свёрнуты в текущий L3. Массив событий сессии хранится рантаймом
# и доступен как постоянная история причинно-следственных цепочек.
# -----------------------------------------------------------------------------
MERGE_STRATEGY = (
    "Rewrite the whole L3 session snapshot by merging Current L3 session memory "
    "with only the provided unsaved L1 runtime snapshots.\n"
    "Current L3 session memory is already the consolidated previous saved state; "
    "do not require older L1 snapshots again.\n"
    "The provided L1 snapshots are the fresh runtime tail since the previous successful session save.\n"
    "Use the diff history to identify which topics or constraints actually changed during the session.\n"
    "Do not copy every L1 line. Compress repeated or superseded states.\n"
)

# -----------------------------------------------------------------------------
# WHAT TO PRESERVE
# L3 сохраняет только то, что важно для продолжения после разрыва сессии.
# Транзиентные детали последнего ответа JIN выкидываются, если не несут
# незавершённый вопрос или следующий шаг.
# -----------------------------------------------------------------------------
WHAT_TO_PRESERVE = (
    "Preserve what should survive a browser reload or a new tab: "
    "active project direction, explicit decisions, durable facts, "
    "unresolved tasks, constraints, and next step.\n"
    "Preserve durable JIN/user fact lines from L1 snapshots as stable session facts; "
    "keep their keys stable and change only values that were explicitly corrected or superseded.\n"
    "Keep user-requested stored values with explicit purpose in their own retrieval-friendly lines.\n"
    "Drop transient last_jin_response details unless they contain "
    "an unresolved question or next step.\n"
    "Do not infer durable user personality traits, relationship claims, "
    "or preferences from weak signal.\n"
    "When active_topic/current_task/user constraint is removed due to topic shift, preserve it as a dormant line, "
    "if it contains a useful re-entry point, user constraint, unresolved task, or viewing/work progress.\n"
)

# -----------------------------------------------------------------------------
# TIME NORMALIZATION
# Относительные временные слова нормализуются к доверенной дате из
# CURRENT_TRUSTED_RUNTIME_VARIABLES. В снимок сессии не должны попадать голые «сегодня»
# или «недавно». Временные предпочтения кодируются с явной датой истечения.
# -----------------------------------------------------------------------------
TIME_NORMALIZATION = (
    "Treat CURRENT_TRUSTED_RUNTIME_VARIABLES USER_DATETIME as the source of truth for current time.\n"
    "Convert relative temporal phrases from L1 snapshots into absolute or "
    "session-relative phrases before preserving them.\n"
    "Session handoff memory must not contain ambiguous standalone words like "
    "today, now, or recently unless paired with a timestamp or date.\n"
    "If a preference expires at end of day, preserve its resolved absolute date "
    "and state that it expires after that date unless renewed.\n"
    "If the exact date cannot be inferred, write 'relative to current session' "
    "rather than pretending it is durable calendar time.\n"
)

# -----------------------------------------------------------------------------
# IMPORTANT SESSION EVENTS
# L3 independently extracts important events from the supplied L1 runtime
# snapshots. Events remain ordinary atomic L3 lines linked to source snapshots.
# -----------------------------------------------------------------------------
IMPORTANT_SESSION_EVENTS = (
    "Identify important session events directly from the supplied L1 runtime snapshots.\n"
    "An event should preserve a meaningful decision, turning point, correction, discovery, "
    "failure and recovery, completed milestone, or other development needed to understand the session.\n"
    "Do not create separate event objects or copy every routine update.\n"
    "Write each event as exactly one atomic line in this format:\n"
    "  event_descriptive_name: Event description with maximum three sentences "
    "[ runtime_memory_ids: id1, id2, ... ]\n"
    "Use a concise lowercase underscore key that describes the event.\n"
    "List the runtime_memory_id values of the contributing snapshots in chronological order.\n"
    "Use only IDs present in the supplied snapshots; never invent, reorder, or omit the suffix.\n"
)

# -----------------------------------------------------------------------------
# ASSEMBLED PROMPT
# -----------------------------------------------------------------------------
RUNTIME_L3_SESSION_MEMORY_SYSTEM_PROMPT = (
        ROLE
        + OUTPUT_FORMAT
        + MERGE_STRATEGY
        + WHAT_TO_PRESERVE
        + TIME_NORMALIZATION
        + IMPORTANT_SESSION_EVENTS
)

# Field templates used while rendering selected L1 snapshots for the L3 user prompt.
RUNTIME_L3_SNAPSHOT_INDEX_TEMPLATE = "snapshot: {index}"
RUNTIME_L3_SNAPSHOT_ROLE_TEMPLATE = "role: {role}"
RUNTIME_L3_SNAPSHOT_TOTAL_DIFF_TEMPLATE = "total_diff: {total_diff}"
RUNTIME_L3_SNAPSHOT_MEMORY_LABEL = "memory:"
RUNTIME_L3_SNAPSHOT_PATCH_SUMMARY_LABEL = "patch_summary:"

# Labels and templates used by the L3 user prompt builder.
RUNTIME_L3_USER_PROMPT_COMPACT_DIGEST_TEMPLATE = "L3 compact digest minimal: {minimal}"
RUNTIME_L3_USER_PROMPT_CURRENT_MEMORY_LABEL = "Current L3 session memory:"
RUNTIME_L3_USER_PROMPT_SELECTED_SNAPSHOTS_LABEL = "Selected L1 runtime memory snapshot history:"
RUNTIME_L3_USER_PROMPT_OMITTED_SNAPSHOTS_TEMPLATE = "omitted_middle_snapshots: {count}"
RUNTIME_L3_USER_PROMPT_SNAPSHOT_SEPARATOR = "\n\n---\n\n"
RUNTIME_L3_USER_PROMPT_RECENT_DIFFS_LABEL = "Recent L1 diff history:"
RUNTIME_L3_USER_PROMPT_OMITTED_DIFFS_TEMPLATE = "omitted_older_diffs: {count}"
RUNTIME_L3_USER_PROMPT_REWRITE_INSTRUCTION = (
    "Rewrite the consolidated L3 session memory now by merging the current L3 memory with the unsaved runtime tail."
)

# L3 log labels, action names, and runtime messages.
L3_LOG_LEVEL = "L3"
L3_LOG_LABEL_SESSION = "L3 session"
L3_LOG_LABEL_SESSION_MEMORY = "L3 session memory"
L3_SESSION_MEMORY_SOURCE = "L3"
L3_ACTION_SAVE_SESSION = "save_session"
L3_PROMPT_BUDGET_EXCEEDED_MESSAGE = "L3 session digest exceeds safe input budget"
L3_OUTPUT_TOKEN_BUDGET_CAPPED_TEMPLATE = "L3 session output token budget capped at {max_tokens}"
L3_SKIP_NO_SNAPSHOTS_MESSAGE = "L3 session save skipped: no snapshots"
L3_SKIP_NO_NEW_SNAPSHOTS_MESSAGE = "L3 session save skipped: no new snapshots"
L3_SUMMARIZER_REACHED_MAX_TOKENS_MESSAGE = "L3 session summarizer reached max_tokens"
L3_RESPONSE_TRUNCATED_REASON = "L3 session summarizer response was truncated by max_tokens."
L3_STRUCTURALLY_INCOMPLETE_REASON = "L3 session summarizer returned text that looks structurally incomplete."
L3_UPDATE_SKIPPED_MESSAGE = "L3 session memory update skipped"
L3_UPDATE_FAILED_MESSAGE = "L3 session memory update failed"
L3_UPDATED_MESSAGE = "L3 session memory updated"
L3_BUDGET_EXCEEDED_DETAILS_TEMPLATE = "Reason: compact digest still exceeds safe input budget.\n\n{diagnostic}"
L3_SUMMARIZER_STAGE = "L3 session memory summarizer"
