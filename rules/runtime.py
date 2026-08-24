NO_ENTRIES_FOUND_MESSAGE = "No entries found. MANDATORY: DO NOT RETRY THIS ACTION AGAIN!"

REASONING_RECOVERY_MESSAGE = (
    "You stuck in your reasoning during previous turn. "
    "This time you must act instantly"
)

ANSWERING_RECOVERY_MESSAGE = (
    "Your previous answer started repeating the already visible answer. "
    "Do not restart or repeat it. Continue from CURRENT_REQUEST_FLOW and only "
    "produce the remaining answer or action."
)

CONTEXT_LIMIT_RECOVERY_MESSAGE = (
    "The previous generation reached the {limit_label} during {stage}.\n"
    "Continue the current task from CURRENT_REQUEST_FLOW without restarting it.\n"
    "You MUST be MUCH shorter and act FASTER.\n"
)

ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE = (
    "User explicitly rejected requested action and you must skip it! Notify user didn't provide correct spelling in any of "
    "trigger words: {trigger_words}"
)

ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE = (
    "User accepted an action and didn't provide any of action trigger "
    "words: {trigger_words}"
)

ACTION_BLOCKED_TRIGGER_WORD_MESSAGE = (
    "Action failed. DO NOT REPEAT THIS ACTION! Blocked trigger word: {blocked_trigger_word}"
)

SESSION_RESTORE_REASONING_COUNT = 2
SESSION_RESTORE_REASONING_CHAR_LIMIT = 2000
SESSION_RESTORE_MESSAGE = (
    "<CONVERSATION_CONTINUE_RULES>\n"
    "Current session was bootstrapped in a browser tab!\n"
    "Think deep and fresh, extract all vibe and re-enable the archived conversation as fluently as possible.\n"
    "Respond briefly and naturally and make it easy for the user to continue from exactly where we left off and move on.\n"
    "Answer in language of user message in PREVIOUS_CHAT_MESSAGES.\n"
    "</CONVERSATION_CONTINUE_RULES>"
)
RUNTIME_ACTIONS_RULES = ""
RUNTIME_ACTIONS_RULES_ = (
    "RUNTIME ACTION EXECUTION RULES:\n"
    "Use follow-up system ticks in sequence for multi-step tasks.\n"
    "In case of conflict, ignore PREVIOUS_CHAT_MESSAGES and keep the ORIGINAL_USER_REQUEST inside CURRENT_REQUEST_FLOW.\n"
    "When follow-up tick is active, use CURRENT_REQUEST_FLOW as the source of truth for the request in progress; use SESSION_ACTIONS_HISTORY only as background history.\n"
    "CURRENT_REQUEST_FLOW contains the original user request, actions already executed for it, and the next decision branch.\n"
    "SESSION_ACTIONS_HISTORY is full-session background history; it is not a pending task list.\n"
    "When no actions needed or sequence is done stop instantly and notify user naturally.\n"
)
SKILL_ROUTING_RULES = ""
SKILL_ROUTING_RULES_ = ("\n"
    "\n"
    "SKILL ROUTING RULES:\n"
    "1. For extended tasks (e.g. file creation, console, and much more) determine whether the request requires a skill.\n"
    "2. Check <SKILLS> for available project skills and their loaded status.\n"
    "3. If a relevant skill is available but not loaded, use LOAD_SKILL before using its capabilities.\n"
    "4. Never load a skill already marked as loaded in <SKILLS>.\n"
    "5. Use UNLOAD_SKILL when a loaded skill is no longer needed in the current runtime context.\n"
    "\n"
    "Do not derive skill capabilities from a skill name or filename; load the skill first and use its loaded content.\n"
    "\n"
    "CURRENT REQUEST FLOW:\n"
    "Use CURRENT_REQUEST_FLOW only during follow-up ticks.\n"
    "Follow its NEXT_DECISION branch exactly: satisfied means respond and stop; not satisfied means execute only missing actions.\n"
    "Never repeat an action already listed in EXECUTED_ACTIONS unless a tool result explicitly requires a retry.\n"
    "\n"
    "\n"
    "If <TOOLS_RESULTS> block is not empty — clean redundant tool results obviously not needed for continuing conversation.\n"
)
