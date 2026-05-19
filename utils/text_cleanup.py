import re


JUNK_PATTERNS = [
    r"</start_of_turn>",
    r"<start_of_turn>",
    r"<think>.*?</think>",
]


def cleanup_text(text: str):

    removed = []

    cleaned = text

    for pattern in JUNK_PATTERNS:

        matches = re.findall(
            pattern,
            cleaned,
            flags=re.DOTALL,
        )

        if matches:
            removed.extend(matches)

        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.DOTALL,
        )

    cleaned = cleaned.strip()

    return cleaned, removed
