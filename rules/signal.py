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
