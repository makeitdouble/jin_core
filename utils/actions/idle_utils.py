import re


IDLE_SECONDS_RE = re.compile(
    r"^\s*(?P<seconds>\d+)(?:\s*(?:m?s))?\s*$",
    re.IGNORECASE,
)



def parse_idle_seconds(
    payload: str,
) -> int | None:

    match = IDLE_SECONDS_RE.fullmatch(
        str(payload or "")
    )

    if match is None:
        return None

    try:
        return int(
            match.group("seconds")
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def build_idle_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    seconds = parse_idle_seconds(
        query
    )

    if seconds is None:
        return None

    return f"{seconds}s"
