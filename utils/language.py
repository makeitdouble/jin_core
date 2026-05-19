import re


CYRILLIC_PATTERN = re.compile(
    r"[а-яА-ЯёЁ]"
)


def contains_cyrillic(
    text: str,
) -> bool:

    return bool(
        CYRILLIC_PATTERN.search(text)
    )
