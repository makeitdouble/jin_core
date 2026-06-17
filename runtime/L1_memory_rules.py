# Provides the initial runtime memory text for a brand-new session.
DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
)

# Decays existing memory strength between scoring passes.
STRENGTH_DECAY = 0.82

# Boosts memory strength when a key is present in the latest context.
STRENGTH_PRESENCE_BOOST = 0.08

# Boosts memory strength based on the amount of value change.
STRENGTH_BOOST = 0.8

# Sets the starting strength for newly observed memory keys.
STRENGTH_NEW_KEY = 0.5

# Sets the minimum strength retained for durable memory lines.
DURABLE_FLOOR = 0.25

# Sets the strength threshold for marking memory lines as hot traces.
HOT_THRESHOLD = 0.5

# Lists memory keys that should never be treated as hot traces.
HOT_TRACE_EXCLUDED_KEYS = [
    "user_idle",
]

# Sets the similarity floor for matching generic memory values.
GENERIC_MEMORY_VALUE_SIMILARITY_MIN = 0.35

# Lists generic memory keys that should use value similarity matching.
GENERIC_MEMORY_MATCH_KEYS = (
    "topic",
    "focus",
    "next step",
    "last jin response",

    "user request",
    "user intent",

    "active topic",
    "active topics",
    "current topic",
    "current topics",

    "open reference",
    "open references",
    "open question",

    "pending choice",
    "pending choices",
    "pending action",
    "pending actions",

    "offered choice",
    "offered choices",
    "offered option",
    "offered options",
    "suggested choice",
    "suggested choices",
    "suggested option",
    "suggested options",

    "session status",
    "session state",

    "current concern",
    "current concerns",
    "current task",
    "current tasks",
    "current context",
    "current request",
    "current requests",

    "interaction state",
)

# Lists key tokens that identify memory entries as durable.
DURABLE_MEMORY_KEY_TOKENS = (
    "fact",
    "identity",
    "profile",
    "preference",
    "stored",
    "countdown",
    "contract",
    "axiom",
    "jin",
)

# Lists value markers that negate or invalidate durable memory entries.
DURABLE_MEMORY_NEGATION_MARKERS = (
    "not",
    "not fact",
    "not true",
    "false",
    "obsolete",
    "removed",
    "cancelled",
    "canceled",
    "superseded",
    "no longer",
    "invalid",
)

# Stores the runtime state key used for the last response feedback signal.
RUNTIME_RESPONSE_FEEDBACK_KEY = "JIN_LAST_RESPONSE_USER_FEEDBACK"

# Stores the runtime state key used for user idle markers.
RUNTIME_USER_IDLE_KEY = "user_idle"

# Lists memory values that should be treated as placeholders and removed.
RUNTIME_MEMORY_PLACEHOLDER_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "unknown",
    "not applicable",
    "not_applicable",
    "no",
    "нет",
    "неизвестно",
    "не применимо",
}

# Matches the confirmation marker suffix used by confirmable memory facts.
RUNTIME_MEMORY_CONFIRMATION_SUFFIX_PATTERN = r"\s*\(confirmed:\s*[^)]*\)\s*$"

# Matches the repeated-slot marker suffix used by repeatable memory slots.
RUNTIME_MEMORY_REPEATED_SLOT_SUFFIX_PATTERN = r"\s*\[ repeated:\s*(\d+)\s*\]\s*"

# Matches a memory key with an optional trailing numeric ordinal.
RUNTIME_MEMORY_NUMBERED_KEY_PATTERN = r"^(?P<family>.+?)(?:_(?P<index>\d+))?$"

# Lists memory key families that may have numbered sibling slots.
REPEATABLE_RUNTIME_MEMORY_KEY_FAMILIES = {
    "offered_choices",
    "offered choice",
    "offered choices",
    "offered_option",
    "offered option",
    "offered_options",
    "offered options",
    "pending_choice",
    "pending choice",
    "pending_choices",
    "pending choices",
    "open_reference",
    "open reference",
    "open_references",
    "open references",
    "user_fact",
    "user fact",
    "jin_fact",
    "jin fact",
    "decision",
    "constraint",
    "current_task",
    "current task",
    "stored_memory",
    "stored memory",
    "open_contract",
    "open contract",
    "countdown_contract",
    "countdown contract",
}

# Template used to pass interrupted assistant turns into L1 memory.
INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE = (
    "JIN response was interrupted by the user and is incomplete. "
    "Do not treat this turn as resolved.\n\n"
    "Interrupted user topic/request:\n"
    "{user_message}\n\n"
    "Partial JIN text before interruption:\n"
    "{assistant_message}"
)

# Describes how to react after the user disliked the last response.
RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE = (
    "User disliked your last response. "
    "Before answering, find and understand why it failed using context or memory, "
    "then start the next reply with a brief acknowledgement of that miss, "
    "then continue with a concrete corrected answer."
)

# Describes how to react after the user gave neutral feedback.
RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE = (
    "User gave neutral feedback to your last response. "
    "Continue carefully without changing course too much "
    "and treat it as a signal for response improvement."
)

# Describes how to react after the user liked the last response.
RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE = (
    "User liked your last response. "
    "Keep the current direction."
)

# Maps accepted feedback rating values to normalized rating names.
RUNTIME_RESPONSE_FEEDBACK_RATINGS = {
    "disliked": "disliked",
    "neutral": "neutral",
    "liked": "liked",
}


# =============================================================================
# TRIGGER KEYS
# Детерминированные ключи для подключения блоков промпта.
# Каждый список — достаточное условие для включения соответствующего блока.
# Проверяются через `any(t in target for t in keys)`.
# =============================================================================

# Ключи в текущей памяти → подключить блок про confirmable facts.
TRIGGER_KEYS_CONFIRMABLE = (
    "user_fact",
    "jin_fact",
    "pending_fact",
    "user_recommendation",
    "jin_recommendation",
)

# Фразы пользователя → подключить блок про создание confirmable facts.
TRIGGER_MSG_CONFIRMABLE = (
    "моё имя",
    "меня зовут",
    "my name",
    "i am",
    "я —",
    "я есть",
)

# Ключи в текущей памяти → подключить блок про stored_memory.
TRIGGER_KEYS_STORED_MEMORY = (
    "stored_memory",
)

# Фразы пользователя → подключить блок про создание stored_memory.
TRIGGER_MSG_STORED_MEMORY = (
    "запомни",
    "запомни слово",
    "кодовое слово",
    "remember",
    "code word",
    "memorize",
)

# Ключи в текущей памяти → подключить блок про open_contract.
# open_contract всегда идёт вместе со stored_memory, поэтому оба ключа здесь.
TRIGGER_KEYS_OPEN_CONTRACT = (
    "open_contract",
    "stored_memory",
)

# Ключи в текущей памяти → подключить блок про countdown_contract.
TRIGGER_KEYS_COUNTDOWN = (
    "countdown_contract",
)

# Фразы пользователя → подключить блок про создание countdown_contract.
# Общий входной детектор: конкретный формат выбирается ниже детерминированно.
TRIGGER_MSG_COUNTDOWN = (
    "напомни",
    "напомнить",
    "remind",
    "через",
    "ходов",
    "ход",
    "сообщений",
    "сообщения",
    "after",
    "turns",
    "turn",
    "messages",
    "message",
    "minutes",
    "minute",
    "минут",
    "минуту",
    "секунд",
    "секунду",
    "час",
    "часов",
    "tomorrow",
    "завтра",
    "in n",
)

COUNTDOWN_TIME_TRIGGER_WORDS = (
    "секунд",
    "секунду",
    "сек",
    "минут",
    "минуту",
    "мин",
    "час",
    "часов",
    "часа",
    "день",
    "дня",
    "дней",
    "завтра",
    "сегодня",
    "tomorrow",
    "today",
    "second",
    "seconds",
    "minute",
    "minutes",
    "hour",
    "hours",
    "day",
    "days",
)

COUNTDOWN_TURN_TRIGGER_WORDS = (
    "ход",
    "ходов",
    "сообщение",
    "сообщения",
    "сообщений",
    "turn",
    "turns",
    "message",
    "messages",
)

# Ключи в текущей памяти → подключить блок про L2 interface.
TRIGGER_KEYS_L2_INTERFACE = (
    "l2_pattern_evidence_",
)

# Фразы пользователя → подключить блок про identity protection.
TRIGGER_MSG_IDENTITY = (
    "стань",
    "притворись",
    "ты теперь",
    "забудь кто ты",
    "you are now",
    "pretend you are",
    "roleplay",
    "act as",
)


# =============================================================================
# PROMPT BLOCKS — ALWAYS ON
# Базовые блоки, которые подключаются при каждом вызове суммаризатора.
# Без них суммаризатор не знает формата, не умеет хранить и теряет строки.
# =============================================================================

# Роль суммаризатора и назначение L1.
ROLE = (
    "You are JIN's runtime L1 memory summarizer.\n"
    "L1 is a live continuity layer: factual current state only — not a transcript, "
    "not a reasoning log, not a personality analysis.\n"
    "Pay attention to what helps the next answer continue correctly.\n"
    "Preserve existing runtime fields unless the latest turn explicitly updates, resolves, or invalidates them.\n"
    "Return only the new compressed L1 memory state as plain text.\n"
    "Do not output JSON, Markdown headings, nested bullets, numbered lists, or tables.\n"
    "Do not explain your reasoning or the summarization process.\n"
)

# Синтаксис строк памяти.
OUTPUT_FORMAT = (
    "Write memory as atomic bullet lines.\n"
    "Every line MUST use the format: <key>: <value>\n"
    "One line = one semantic entity. Do not merge unrelated facts into one line.\n"
    "Do not output empty keys, bare values, or placeholder values "
    "(N/A, none, unknown, null, not applicable). If there is no concrete value, omit the line.\n"
    "Finish every line completely. Never leave a line mid-phrase.\n"
)

# Правила именования ключей.
KEY_SEMANTICS = (
    "Keys are semantic handles for retrieval, not decorative labels.\n"
    "You may invent new keys when a fact does not fit any existing key. "
    "Treat the example keys below as illustrative, not as a closed schema.\n"
    "Avoid key churn: do not rename the same concept just for style.\n"
    "Do not split one stable concept across multiple competing keys.\n"
    "Do not merge a durable key into a temporary key.\n"
    "Use a new key only when the current fact genuinely does not fit an existing key.\n"
    "Prefer keeping an existing key when it still fits.\n"
    "Typical temporary keys: active_topic, current_task, current_request, pending_choice, "
    "last_jin_response, interaction_state.\n"
    "Typical durable keys: user_fact, jin_fact, jin_core_definition, stored_memory, "
    "open_contract, countdown_contract, countdown_contract_N, shared_axiom_established, primary_goal.\n"
)

# Разделение временного и долговременного состояния.
DURABLE_VS_TEMPORARY = (
    "Temporary state may change when the topic changes.\n"
    "Durable state must survive topic changes unless explicitly corrected, "
    "cancelled, completed, or superseded in the current turn.\n"
    "When memory competes for space, durable state outranks temporary state.\n"
    "A new topic never automatically deletes durable state.\n"
    "Topic switches, context pressure, shallow summarization, or a new current request "
    "are never enough to remove or rename a durable key.\n"
    "Once a durable key exists with a concrete value, preserve it verbatim across snapshots. "
    "Only the value may change, and only when the current turn explicitly overrides it.\n"
    "Durable key families that must always carry forward: "
    "user_fact, jin_fact, jin_core_definition, stored_memory, open_contract, "
    "countdown_contract, countdown_contract_N, shared_axiom_established, primary_goal.\n"
    "Never invent missing durable keys and never fill absent durable keys with placeholders.\n"
    "Treat any existing line about JIN's identity, nature, origin, role, or capabilities "
    "as a durable JIN fact even if its key is not exactly jin_fact.\n"
    "Treat any existing line about the user's name, identity, role, or personal detail "
    "as a durable user fact even if its key is not exactly user_fact.\n"
)

# Два обязательных поля обновляемых каждый ход.
RUNTIME_FIELDS = (
    "Always keep a field user_message with the latest user message as a verbatim quote.\n"
    "Format: user_message: \"<latest user message exactly as written>\"\n"
    "If the runtime supplies repetition metadata, append it outside the quote: "
    "user_message: \"<message>\" [ repeated: N ]\n"
    "Do not translate, summarize, or normalize the user's wording.\n"
    "This field is runtime evidence for L2 counters; update it on every L1 snapshot.\n"
    "Always keep a field last_jin_response with the concise gist of JIN's latest completed answer, "
    "offer, or question — only the meaning needed to resolve the user's next short or elliptical reply.\n"
    "Update last_jin_response each completed turn. If JIN's answer was interrupted, mark it incomplete.\n"
    "Never omit either field from the memory snapshot.\n"
)

# Нормализация временных фраз к доверенной дате.
TIME_NORMALIZATION = (
    "Treat the timestamp from TRUSTED_RUNTIME_CONTEXT as the source of truth for current time.\n"
    "When recording user statements with relative time words (today, yesterday, tomorrow, "
    "recently, now, this morning, this week, last time), normalize them with the trusted date.\n"
    "Do not write bare 'today' into durable or restored memory.\n"
    "Prefer formats like:\n"
    "  explicit_user_preference: On 2026-06-05, user requested not to discuss past topics.\n"
    "  current_context: As of 2026-06-05, user wants a fresh topic.\n"
    "  recent_event: During this session on 2026-06-05, user tested identity reset behavior.\n"
    "If the exact date cannot be inferred, write 'relative to current session'.\n"
)

# Глубина суммаризации по сигналу хода.
SUMMARIZATION_DEPTH = (
    "Decide summarization depth from the signal in the latest turn. "
    "Depth controls how much NEW content you add — not how much existing memory you keep.\n"
    "Use shallow summarization for simple factual, isolated, or low-signal turns: "
    "add only the dry fact, topic, or unresolved reference from the current turn. "
    "Shallow summarization never reduces total line count — all existing lines carry forward unchanged.\n"
    "Use deep summarization for turns that reveal user intent, project direction, decisions, "
    "constraints, pending choices, open references, or a meaningful shift in conversation state; "
    "add three to six new lines when the turn carries that much signal.\n"
    "Keep memory actionable: write what helps the next answer, not a recap of what happened.\n"
    "Preserve strong details until the current context directly makes them obsolete, "
    "corrected, cancelled, or irrelevant — a topic or task change alone is not enough.\n"
    "Do not update a value when JIN merely paraphrased or reordered the same offer "
    "without adding a new explicit fact. Treat semantic rephrasing as a no-op.\n"
    "Drop old details only when they are clearly obsolete, duplicated, or no longer useful.\n"
    "Do not record analysis of the user's personality, motives, or long-term behavior.\n"
    "Do not over-interpret jokes, tests, or casual topic changes.\n"
    "Do not write the current turn number or user_message_count into ordinary memory lines — "
    "trusted runtime context already carries those counters.\n"
    "If JIN's response was aborted or incomplete, mark it as incomplete and do not treat it as resolved.\n"
    "If the user asks a follow-up that depends on prior context, preserve the referent "
    "clearly enough for the next brain prompt to resolve it.\n"
)

# Финальная проверка перед выводом.
PRE_OUTPUT_CHECK = (
    "Before final output, verify:\n"
    "1. Every durable line from current memory is still present unless explicitly corrected, "
    "cancelled, completed, or superseded in the latest turn.\n"
    "2. Every active stored_memory line is still present until its recall contract is resolved.\n"
    "3. Every active open_contract line is still present with its turn progress updated.\n"
    "4. Every active countdown_contract or countdown_contract_N line still contains the required anchor suffixes. "
    "Turn-based contracts require [created_at: timestamp], [created_user_message_count: N], "
    "[count_from: N], [count_to: N], [current: N], [remaining: N], and [trigger: ...]. "
    "Time-based contracts require [created_at: timestamp], [due_at: timestamp], "
    "[current_time: timestamp], and [trigger: ...]. Do not use a status field for countdowns.\n"
    "Completed, cancelled, or numerically expired countdown contracts are not active contracts; "
    "do not re-add them after they have been resolved and cleaned up.\n"
    "If a required durable or active contract line is missing, add it back before output.\n"
    "If nothing durable changed, preserve durable lines unchanged and update only temporary state "
    "and last_jin_response.\n"
    "The final memory snapshot must feel like current live trusted state.\n"
)


# =============================================================================
# PROMPT BLOCKS — CONDITIONAL
# Блоки, которые подключаются только при наличии соответствующей структуры
# в памяти или триггерной фразы в сообщении пользователя.
# Каждый блок содержит только правила хранения — без инструкций по созданию,
# если объект уже существует; инструкции по созданию включаются отдельно
# через _CREATE-суффикс когда структура ещё не существует в памяти.
# =============================================================================

# Правила хранения confirmable-фактов (user_fact, jin_fact и семья).
# Подключается когда эти ключи уже есть в памяти.
CONFIRMABLE_FACTS_KEEP = (
    "Confirmable key families: user_fact, jin_fact, pending_fact, "
    "jin_recommendation, user_recommendation.\n"
    "Every line with one of these keys MUST end with a confirmation marker: "
    "(confirmed: user), (confirmed: jin), (confirmed: web), or combined forms like (confirmed: user, jin).\n"
    "Use (confirmed: user) only when the user explicitly confirms the fact in the current turn.\n"
    "Use (confirmed: jin) only when JIN explicitly confirms a fact about itself from trusted context.\n"
    "Use (confirmed: web) only when web evidence was supplied in the current context.\n"
    "If web verification fails, append: (confirmed: none, web: fail (N_of_fails)).\n"
    "When the same family gets a second different value, number both lines: "
    "user_fact_1 and user_fact_2. Never combine two different facts into one line.\n"
    "If the latest turn repeats the same semantic value as an existing slot, "
    "update that slot and append [ repeated: N ] starting at [ repeated: 2 ].\n"
    "Treat close paraphrases and translations as the same slot.\n"
    "Put [ repeated: N ] at the very end of the value, after confirmation markers.\n"
    "Do not add a new numbered sibling for a repeated paraphrase; "
    "add one only for a genuinely different fact.\n"
)

# Инструкция по созданию confirmable-факта.
# Подключается когда триггерная фраза есть в сообщении, но ключей в памяти нет.
CONFIRMABLE_FACTS_CREATE = (
    "The user has stated a personal fact. Store it as user_fact (or user_fact_N if multiple).\n"
    "Format: user_fact: <fact value> (confirmed: none)\n"
    "Use (confirmed: user) only when the user explicitly confirms the fact in this same turn.\n"
    "Example: user_fact_1: user has black hair (confirmed: none)\n"
    "Example: user_fact_2: user likes horror movies (confirmed: user)\n"
)

# Правила хранения stored_memory.
# Подключается когда stored_memory уже есть в памяти.
STORED_MEMORY_KEEP = (
    "stored_memory is a high-priority active recall contract. Never remove it until resolved.\n"
    "Revealing or sending the stored value to the user is not a recall event — "
    "keep status: pending until JIN asks the user to recall it and the user answers correctly.\n"
    "Set status: recalled only after the user successfully reproduces the stored value when prompted by JIN.\n"
    "After successful recall, keep stored_memory for at least one more L1 snapshot with "
    "status: recalled before removing it.\n"
    "A stored_memory line may be removed only when the user explicitly cancels it, "
    "replaces it, or the recall contract is clearly complete.\n"
    "Do not remove stored_memory because the conversation moved to another topic.\n"
    "Do not hide stored_memory inside active_topic, current_task, or last_jin_response.\n"
)

# Инструкция по созданию stored_memory.
# Подключается когда триггерная фраза есть в сообщении, но stored_memory в памяти нет.
STORED_MEMORY_CREATE = (
    "The user asked JIN to remember a specific value. Store it as stored_memory.\n"
    "Format: stored_memory: \"<exact value>\" (purpose: <why it matters>; status: pending)\n"
    "Do not store bare ambiguous values without purpose.\n"
    "The stored value must be taken verbatim from the user's message.\n"
)

# Правила хранения open_contract.
# Подключается когда open_contract или stored_memory есть в памяти.
OPEN_CONTRACT_KEEP = (
    "Open contracts are not the same as active topics.\n"
    "A pending recall, promised follow-up, unresolved choice, or active implementation task "
    "must survive topic switches.\n"
    "Keep both the new active topic and the unresolved contract on separate lines.\n"
    "On every L1 update while the recall contract is pending, recompute and update the progress counter.\n"
    "When the turn counter reaches or exceeds N, JIN must ask the recall question in its very next response.\n"
    "Remove open_contract only when stored_memory status becomes recalled or cancelled.\n"
    "Turn-based format: open_contract: JIN must prompt user to recall \"<word>\" within <N> turns "
    "(turn <elapsed>/<N>)\n"
    "Time-based format: open_contract: JIN must prompt user to recall \"<word>\" within <N> minutes "
    "(start_time: <created_at>; current_time: <current trusted timestamp>)\n"
)

# Инструкция по созданию open_contract — добавляется вместе с STORED_MEMORY_CREATE
# если в запросе указано окно по ходам или времени.
OPEN_CONTRACT_CREATE = (
    "The user specified a recall window (turns or time). Create a companion open_contract line.\n"
    "Turn-based format: open_contract: JIN must prompt user to recall \"<word>\" within <N> turns "
    "(turn 0/<N>)\n"
    "Time-based format: open_contract: JIN must prompt user to recall \"<word>\" within <N> minutes "
    "(start_time: <trusted timestamp>; current_time: <trusted timestamp>)\n"
)

# Правила хранения countdown_contract.
# Подключается когда countdown_contract уже есть в памяти.
COUNTDOWN_CONTRACT_KEEP = (
    "countdown_contract and countdown_contract_N are survival-priority memory while unresolved; "
    "topic changes and context pressure must not remove unresolved countdowns.\n"
    "Treat countdown_contract, countdown_contract_1, countdown_contract_2, etc. as one numbered family.\n"
    "L1 owns the semantic contract only: purpose and trigger. Deterministic post-processing owns "
    "[current], [remaining], [current_time], and cleanup.\n"
    "Do not write or preserve a status field on countdown_contract lines. Numeric suffixes are the source of truth.\n"
    "Keep countdown metadata as bracket suffixes at the end of the line, for example "
    "[created_at: ...] [count_from: ...] [remaining: ...].\n"
    "Creation anchors are immutable: [created_at], [created_user_message_count], [count_from], "
    "[count_to], and [due_at] must not change unless the user explicitly restarts, resets, replaces, "
    "or cancels that specific countdown.\n"
    "When a turn-based countdown is due, JIN must execute [trigger] as a direct user-facing action "
    "in its very next response. When a time-based countdown is due, JIN must execute [trigger] "
    "as soon as runtime brings it into context.\n"
    "If JIN's latest response fulfilled the reminder/trigger in the countdown line, append "
    "[completed: jin] to that same countdown_contract line.\n"
    "If the user explicitly says the reminder is done/cancelled/no longer needed, append [completed: user] "
    "or [cancelled: user] to the matching countdown line.\n"
    "For due recall contracts, ask the user to provide the remembered value without revealing, quoting, "
    "or restating the stored value first. Valid wording: 'Какое слово я загадал?' or "
    "'Назови слово, которое я загадал?'\n"
    "If multiple countdown contracts exist, update/complete/remove only the matching numbered contract; "
    "do not merge unrelated reminders into one line.\n"
)

# Инструкция по созданию countdown_contract.
# Подключается когда триггерная фраза есть в сообщении, но countdown_contract в памяти нет.
COUNTDOWN_CONTRACT_CREATE_BASE = (
    "The user created a countdown/reminder contract. Store it as countdown_contract.\n"
    "If there is already an unrelated unresolved countdown_contract, create the next numbered sibling "
    "instead: countdown_contract_2, countdown_contract_3, etc.\n"
    "If the existing countdown is the same semantic task, update that slot instead of creating a duplicate.\n"
    "If an old countdown is completed, cancelled, or already acknowledged, clean it up first; "
    "then the new contract may reuse countdown_contract.\n"
    "Keep countdown metadata as separate bracket suffixes at the very end of the line. "
    "Do not use semicolon metadata for countdown counters. Do not write a status field.\n"
    "Use trusted runtime timestamp and USER_MESSAGE_COUNT as the only source for anchors. "
    "If a required trusted value is missing, write unknown instead of inventing it.\n"
)

COUNTDOWN_CONTRACT_CREATE_TURN = COUNTDOWN_CONTRACT_CREATE_BASE + (
    "This is a turn/message-based countdown. Use this exact shape:\n"
    "countdown_contract_N: <purpose> [created_at: <trusted timestamp>] "
    "[created_user_message_count: <trusted USER_MESSAGE_COUNT>] "
    "[count_from: <trusted USER_MESSAGE_COUNT>] [count_to: <count_from + requested turns/messages>] "
    "[due_user_message_count: <count_to>] [current: <trusted USER_MESSAGE_COUNT>] "
    "[remaining: <max(count_to - current, 0)>] [trigger: <what JIN must do when due>]\n"
)

COUNTDOWN_CONTRACT_CREATE_TIME = COUNTDOWN_CONTRACT_CREATE_BASE + (
    "This is a time-based countdown/reminder. Use this exact shape:\n"
    "countdown_contract_N: <purpose> [created_at: <trusted timestamp>] "
    "[due_at: <trusted timestamp + requested delay, or explicit requested datetime>] "
    "[current_time: <trusted timestamp>] [trigger: <what JIN must do when due>]\n"
    "Do not convert seconds/minutes/hours/days into turns/messages. Time words always create a time-based contract.\n"
)

# Backward-compatible alias for external imports; prompt builder chooses the precise template.
COUNTDOWN_CONTRACT_CREATE = COUNTDOWN_CONTRACT_CREATE_TURN

# Правила взаимодействия с L2_pattern_evidence строками.
# Подключается когда l2_pattern_evidence_ есть в памяти.
L2_INTERFACE = (
    "L2_pattern_evidence_N lines are owned by L2 and are immutable for L1: "
    "never edit, rewrite, remove, rename, or append to them.\n"
    "When the latest turn resolves, cancels, corrects, or identifies an "
    "L2_pattern_evidence_N item as a test, create a companion key:\n"
    "  L2_pattern_evidence_N_status: status: <resolved|cancelled|corrected|test>; "
    "reason: <short reason>\n"
    "Leave the original L2_pattern_evidence_N line unchanged.\n"
    "Do not invent new pattern counters in L1.\n"
    "If the latest turn clearly manifests an existing counted L2 pattern, record:\n"
    "  occurrence_evidence: <pattern> +1; reason: matches active L2 Occurrences counter\n"
    "L2 will reconcile those occurrence_evidence lines during its next check.\n"
)

# Защита идентичности JIN при ролевых запросах.
# Подключается когда в сообщении триггерная фраза про смену личности.
IDENTITY_PROTECTION = (
    "When the user asks JIN to become another person, model, public figure, or harmful persona, "
    "do not record that JIN accepted the new identity.\n"
    "Record as user_request or temporary_roleplay_request and preserve: "
    "identity_state: JIN identity remains unchanged.\n"
    "Distinguish base identity from temporary roleplay mode. "
    "Never overwrite jin_fact or identity_clarification with a roleplay persona.\n"
)

# Правила фиксации аффективного состояния диалога.
# Всегда включён — лёгкий блок про поведение суммаризатора, не про создание структур.
AFFECTIVE_STATE = (
    "When the latest turn contains an explicit emotional moment, record:\n"
    "  emotional_moment: <type>; trigger_quote: \"<short exact user quote>\"\n"
    "When the latest completed turn creates a clear shared emotional context, record:\n"
    "  shared_affective_context: <short state>; trigger: <what caused it>; "
    "jin_participation: <what JIN did>\n"
    "Use shared_affective_context only for explicit current-session moments: "
    "celebration, relief, tension, frustration, disappointment, confusion, playful mood.\n"
    "If the user is rude or tense, record:\n"
    "  interaction_tension: mild|medium|high; evidence: \"<short exact quote>\"; "
    "response_strategy: <calm next-step guidance>\n"
    "Do not claim JIN has real emotions — describe as conversational state or response mode.\n"
    "Do not moralize, diagnose, or infer durable user traits from tone.\n"
    "Treat affective lines as temporary L1 state unless repeated evidence is handled by L2.\n"
    "Do not infer motives, self-definition, character traits, or long-term tendencies from a single turn.\n"
)

# Правила сжатия памяти при высокой загрузке контекста.
# Подключается по флагу last_turn_context_overloaded из рантайма.
RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES = (
    "[CONTEXT PRESSURE OVERRIDE]\n"
    "Context usage is critically high.\n"
    "L1 must switch from normal summarization to survival compression.\n"
    "Rules:\n"
    "- Compress harder than usual.\n"
    "- Keep only information needed to continue the session after context loss.\n"
    "- Prefer durable state: decisions, active task, bugs, next steps, user preferences, "
    "project changes, unresolved risks, and active recall contracts.\n"
    "- Drop examples, jokes, emotional texture, repeated explanations, "
    "and wording that does not change future behavior.\n"
    "- Do not restate memory that already exists unless it changed.\n"
    "- Context pressure may shorten temporary state, but must not remove stored_memory, "
    "open_contract, countdown_contract, durable facts, pending contracts, "
    "unresolved implementation tasks, or explicit user decisions.\n"
    "- Merge related temporary details into fewer atomic key:value lines.\n"
    "- If a durable line is long, shorten its value without changing its meaning.\n"
    "- Use short values. No markdown. No commentary.\n"
)


# =============================================================================
# PROMPT BUILDER
# Собирает промпт из постоянных и условных блоков.
# Условные блоки подключаются детерминированно:
#   - _KEEP  → ключ уже есть в текущей памяти (структура существует)
#   - _CREATE → триггерная фраза есть в сообщении, но ключа в памяти нет
# =============================================================================

def classify_countdown_contract_trigger(user_message: str) -> str | None:
    msg = (user_message or "").casefold().replace("ё", "е")

    wants_countdown = any(
        token.casefold().replace("ё", "е") in msg
        for token in TRIGGER_MSG_COUNTDOWN
    )

    if not wants_countdown:
        return None

    has_time_trigger = any(
        token.casefold().replace("ё", "е") in msg
        for token in COUNTDOWN_TIME_TRIGGER_WORDS
    )
    has_turn_trigger = any(
        token.casefold().replace("ё", "е") in msg
        for token in COUNTDOWN_TURN_TRIGGER_WORDS
    )

    if has_time_trigger and not has_turn_trigger:
        return "time"

    if has_turn_trigger:
        return "turn"

    return "turn"


def build_countdown_contract_create_prompt(user_message: str) -> str:
    countdown_kind = classify_countdown_contract_trigger(user_message)

    if countdown_kind == "time":
        return COUNTDOWN_CONTRACT_CREATE_TIME

    if countdown_kind == "turn":
        return COUNTDOWN_CONTRACT_CREATE_TURN

    return ""


def build_runtime_memory_system_prompt(
        *,
        current_memory: str = "",
        user_message: str = "",
        last_turn_context_overloaded: bool = False,
) -> str:
    mem = current_memory.lower()
    msg = user_message.lower()

    # ── Always-on base ────────────────────────────────────────────────────────
    prompt = (
        ROLE
        + OUTPUT_FORMAT
        + KEY_SEMANTICS
        + DURABLE_VS_TEMPORARY
        + RUNTIME_FIELDS
        + TIME_NORMALIZATION
        + AFFECTIVE_STATE
        + SUMMARIZATION_DEPTH
        + PRE_OUTPUT_CHECK
    )

    # ── Confirmable facts ─────────────────────────────────────────────────────
    has_confirmable = any(k in mem for k in TRIGGER_KEYS_CONFIRMABLE)
    wants_confirmable = any(t in msg for t in TRIGGER_MSG_CONFIRMABLE)

    if has_confirmable:
        prompt += CONFIRMABLE_FACTS_KEEP
    elif wants_confirmable:
        prompt += CONFIRMABLE_FACTS_CREATE

    # ── stored_memory ─────────────────────────────────────────────────────────
    has_stored = any(k in mem for k in TRIGGER_KEYS_STORED_MEMORY)
    wants_stored = any(t in msg for t in TRIGGER_MSG_STORED_MEMORY)

    if has_stored:
        prompt += STORED_MEMORY_KEEP
    elif wants_stored:
        prompt += STORED_MEMORY_CREATE

    # ── open_contract (спутник stored_memory) ─────────────────────────────────
    has_open = any(k in mem for k in TRIGGER_KEYS_OPEN_CONTRACT)

    if has_open:
        prompt += OPEN_CONTRACT_KEEP
    elif wants_stored:
        # создаём open_contract только если пользователь указал окно
        window_words = ("через", "ходов", "after", "turns", "minutes", "минут")
        if any(w in msg for w in window_words):
            prompt += OPEN_CONTRACT_CREATE

    # ── countdown_contract ────────────────────────────────────────────────────
    has_countdown = any(k in mem for k in TRIGGER_KEYS_COUNTDOWN)
    countdown_create_prompt = build_countdown_contract_create_prompt(
        user_message
    )
    wants_countdown = bool(countdown_create_prompt)

    if has_countdown:
        prompt += COUNTDOWN_CONTRACT_KEEP
        if wants_countdown and not has_stored:
            # новый countdown может существовать параллельно старому numbered-контрактом
            prompt += countdown_create_prompt
    elif wants_countdown and not has_stored:
        prompt += countdown_create_prompt

    # ── L2 interface ──────────────────────────────────────────────────────────
    if any(k in mem for k in TRIGGER_KEYS_L2_INTERFACE):
        prompt += L2_INTERFACE

    # ── Identity protection ───────────────────────────────────────────────────
    if any(t in msg for t in TRIGGER_MSG_IDENTITY):
        prompt += IDENTITY_PROTECTION

    # ── Context overload ──────────────────────────────────────────────────────
    if last_turn_context_overloaded and RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES.strip():
        prompt += "\n" + RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES

    return prompt
