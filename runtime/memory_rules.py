MAX_SESSION_PROMPT_SNAPSHOTS = 6
MAX_SESSION_PROMPT_DIFFS = 8
MAX_SESSION_PROMPT_EVENTS = 3
MAX_SESSION_EVENT_TEXT_CHARS = 300
MAX_SESSION_MEMORY_TEXT_CHARS = 1800
MAX_SESSION_LATEST_MEMORY_TEXT_CHARS = 2200
MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS = 500
MAX_SESSION_LINE_CHARS = 220
MAX_SESSION_L2_LINES = 3

SESSION_MEMORY_PRIORITY_KEYWORDS = (
    "decision",
    "constraint",
    "unresolved",
    "pending",
    "next step",
    "current",
    "topic",
    "direction",
    "milestone",
    "blocked",
    "todo",
    "task",
    "fact",
    "user",
    "jin",
    "stored_memory",
    "open_contract",
    "countdown_contract",
    "count_from",
    "count_to",
    "current",
    "remaining",
    "created_at",
    "created_user_message_count",
    "due_user_message_count",
    "last_jin_response",
    "решение",
    "огранич",
    "важно",
    "следующ",
    "текущ",
    "задач",
    "факт",
)

SESSION_EVENT_IMPORTANCE_MARKERS = (
    "запомни",
    "важно",
    "надо сохранить",
    "ключевой момент",
    "это надо зафиксировать",
    "сохрани",
    "зафиксируй",
)

SESSION_EVENT_MILESTONE_MARKERS = (
    "decision",
    "decided",
    "milestone",
    "shipped",
    "completed",
    "resolved",
    "fixed",
    "session-level",
    "решение",
    "решили",
    "веха",
    "готово",
    "закрыли",
    "починили",
)


DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
)

RUNTIME_USER_IDLE_KEY = "user_idle"


RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES = (
    "[CONTEXT PRESSURE OVERRIDE]\n"
    "Context usage is critically high.\n"
    "L1 must switch from normal summarization to survival compression.\n"

    "Rules:\n"
    "- Compress harder than usual.\n"
    "- Keep only information needed to continue the session after context loss.\n"
    "- Prefer durable state: decisions, active task, bugs, next steps, user preferences, project changes, unresolved risks, and active recall contracts.\n"
    "- Drop examples, jokes, emotional texture, repeated explanations, and wording that does not change future behavior.\n"
    "- Do not restate memory that already exists unless it changed.\n"
    "- Context pressure may shorten temporary state, but must not remove stored_memory, open_contract, countdown_contract, durable facts, pending contracts, unresolved implementation tasks, or explicit user decisions.\n"
    "- Merge related temporary details into fewer atomic key:value lines.\n"
    "- If a durable line is long, shorten its value without changing its meaning.\n"
    "- Use short values. No markdown. No commentary.\n"
)

