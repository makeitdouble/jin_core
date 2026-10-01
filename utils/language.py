import re


CYRILLIC_PATTERN = re.compile(
    r"[а-яА-ЯёЁ]"
)

UKRAINIAN_PATTERN = re.compile(
    r"[іїєґІЇЄҐ]"
)


def contains_cyrillic(
    text: str,
) -> bool:

    return bool(
        CYRILLIC_PATTERN.search(text)
    )


def detect_language_name(
    text: str,
    *,
    default: str = "English",
) -> str:

    """Return a lightweight English language name for prompt rules.

    JIN currently needs a cheap local distinction for the languages used in
    chat, not a heavyweight language-classification dependency. Ukrainian
    markers are checked before generic Cyrillic; other Cyrillic text falls
    back to Russian, while non-Cyrillic text uses the supplied default.
    """

    value = str(
        text
        or ""
    )

    if UKRAINIAN_PATTERN.search(
        value
    ):
        return "Ukrainian"

    if contains_cyrillic(
        value
    ):
        return "Russian"

    return str(
        default
        or "English"
    )
