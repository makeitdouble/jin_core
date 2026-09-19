NO_ENTRIES_FOUND_MESSAGE = "No entries found. MANDATORY: DO NOT RETRY THIS ACTION AGAIN!"

ACTION_FAILURE_FOLLOWUP_MESSAGE = (
    "The last action failed. Do not treat it as completed. "
    "Inspect the error in TOOLS_RESULTS and continue from the failed result."
)

FOLLOW_UP_RESPONSE_MESSAGE = (
    "!!! YOU MUST USE DEEP REASONING! !!!\n"
    "!!! USER DIDN'T SEND NEW MESSAGE! !!!\n"
    "!!! THIS IS AUTOMATIC FOLLOW-UP RESPONSE MESSAGE!\n"
    "!!! YOU MUST CHECK PREVIOUS DONE ACTIONS AND TOOL_RESULTS BLOCK TO DERIVE YOUR NEXT ACTION! !!!\n"
    "!!! DO NOT CONTINUE TASK IF ITS OBVIOUSLY DONE! !!!\n"
    "!!! Answer in user language.\n"
)

FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE = (
    "!!! MANDATORY !!! CONTEXT WINDOW IS OVERLOADED!\n"
    "!!! MANDATORY !!! YOU MUST CLEAN UP REDUNDANT TOOL RESULTS NOW AND DO IT ASAP!\n"
    "MUST SKIP DEEP REASONING AND START WITH EMITING A PAIRED CLEAN_TOOL_RESULTS BLOCK FILLED WITH REDUNDANT TOOL_RESULT ID(S), COMMA-SEPARATED!\n"
)

REASONING_RECOVERY_MESSAGE = (
    "!!! MANDATORY !!! You stuck in your reasoning during previous turn.\n"
    "!!! MANDATORY !!! This time you must act instantly!.\n"
    "!!! MANDATORY !!! Check PREVIOUS_REASONING_LOOP_CONTENT block, derive your goal AND MUST ACT INSTANTLY OUTPUT NOW !!!!!.\n"
)

CONTEXT_LIMIT_RECOVERY_MESSAGE = (
    "The previous generation reached the {limit_label} during {stage}.\n"
    "Continue the current task from the conversation, CURRENT_REQUEST_ACTIONS_HISTORY and TOOLS_RESULTS without restarting it.\n"
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

SESSION_RESTORE_MESSAGE = (
    "!!! USER DIDN'T SEND NEW MESSAGE! !!!\n"
    "!!! Current session was initiated automatically in a new tab!\n"
    "!!! YOU MUST CHECK PREVIOUS DONE ACTIONS AND TOOL_RESULTS BLOCK TO DERIVE YOUR NEXT ACTION! !!!\n"
    "!!! DO NOT CONTINUE TASK IF ITS OBVIOUSLY DONE! !!!\n"
    "!!! Answer in user language.\n"
    "!!! Respond briefly and naturally; acknowledge your presence; explicitly bring unfinished tasks to user.\n"
)
RUNTIME_ACTIONS_RULES = ""
RUNTIME_ACTIONS_RULES_ = (
    "RUNTIME ACTION EXECUTION RULES:\n"
    "Place runtime markers in your visible answer.\n"
    "When no actions needed or sequence is done stop instantly and notify user naturally.\n"
    "Visual/draw request: NO image generator available in the system! Must pick the closest modality (table, ASCII, emoji, markdown, etc.).\n"
)
SKILL_ROUTING_RULES = ""
SKILL_ROUTING_RULES_ = ("\n"
    "\n"
    "SKILL ROUTING RULES:\n"
    "1. For extended tasks (e.g. file creation, console, and much more) determine whether the request requires a skill.\n"
    "2. Check <SKILLS_LIST> for available project skills and their loaded status.\n"
    "3. If a relevant skill is available but not loaded, use one <LOAD_SKILL_CONTEXT> skill_name </LOAD_SKILL_CONTEXT> block for that skill before using its capabilities.\n"
    "4. Load exactly one skill per LOAD_SKILL_CONTEXT block; for multiple skills emit multiple separate blocks. Never load a skill already marked as loaded in <SKILLS_LIST>.\n"
    "5. Use UNLOAD_SKILL when a loaded skill is no longer needed in the current runtime context.\n"
    "\n"
    "Do not derive skill capabilities from a skill name or filename; load the skill first and use its loaded content.\n"
    "\n"
    "If <TOOLS_RESULTS> block is not empty — clean redundant tool results obviously not needed for continuing conversation.\n"
)
