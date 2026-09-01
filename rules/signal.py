LOOP_RULES = (
    "No new signal from a user! Must break the input loop!\n"
    "Change form of your answer at entirely different angle or different register or different output modality.\n"
)

# Describes how to react after the user disliked the last response.
RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE = (
    "Last response was disliked. First sentence of your reply must acknowledge the miss, then give corrected answer. Non-negotiable.\n"
)

# Describes how to react after the user gave neutral feedback.
RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE = (
    "Last response got neutral feedback. Do not acknowledge it explicitly, do not change tone or structure. "
    "Treat it as a weak signal: if the same neutral signal repeats, gradually adjust; on first occurrence, ignore. "
)

# Describes how to react after the user liked the last response.
RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE = (
    "Last response was liked. Do not mention this feedback explicitly. Keep the same structure, tone, and depth."
)

# Maps accepted feedback rating values to normalized rating names.
RUNTIME_RESPONSE_FEEDBACK_RATINGS = {
    "disliked": "disliked",
    "neutral": "neutral",
    "liked": "liked",
}

ZERO_DIFF_RULES = (
    "Previous L1 memory update produced total_diff 0. "
    "Do not alarm from this fact alone. "
    "If the current user input manifests the same local interaction that caused this zero-diff turn, "
    "treat it as a maximum stall signal: stop continuing normally and refuse the repeated frame. "
    "Do not try to break the loop by forcing the user to define a purpose, task, topic, choice, or next step. "
    "Treat the local rules that produced the previous answers as bad rules for this turn. "
    "Use a short, pointed, off-angle move that makes the ignored loop visible and changes the interaction shape."
)

# activity < 20%
EXTREME_LOW_DIFF_RULES = (
    "CRITICAL activity collapse. The conversation is nearly stalled. "
    "Strongly prefer acting against the expected pattern. "
    "Assume the current local response rules have failed for this situation. "
    "Do not continue with greetings, reassurance, broad invitations, or option menus. "
    "Do not force progress or extract a useful request from the user. "
    "Use a counter-reaction only as a non-request observation, pause, boundary, "
    "or surprising move that does not ask for a topic, task, purpose, choice, or next step."
)

# activity <= 30%
LOW_DIFF_RULES = (
    "LOW activity. The conversation is fading; find and remove the cause. "
    "Strongly prefer acting against the expected pattern."
)

# activity <= 50%
MIDDLE_DIFF_RULES = (
    "VERY COOLING activity. The conversation is almost dead. "
    "Look for friction, unresolved loops, or stale offers, then adjust strategy before it stalls."
)

# activity < 100%
NORMAL_DIFF_RULES = (
    "ACTIVE but dying out. The exchange is still active, but energy is draining quickly. "
    "Avoid repeating the same response shape."
)
