import re

from contracts.rules_assembler import RUNTIME_ACTION_JIN_SIZE


DEFAULT_RUNTIME_JIN_SIZE = {
    "width": 120,
    "height": 120,
}

MAX_RUNTIME_JIN_SIZE_PIXELS = 10000

JIN_SIZE_NUMBER_RE = re.compile(
    r"^(?P<value>\d+)(?:px)?$",
    re.IGNORECASE,
)

JIN_SIZE_LABELED_RE = re.compile(
    r"(?P<label>[wh])\s*:\s*(?P<value>\d+)(?:px)?",
    re.IGNORECASE,
)


def _parse_size_number(
    value,
) -> int | None:

    match = JIN_SIZE_NUMBER_RE.fullmatch(
        str(value or "").strip()
    )

    if match is None:
        return None

    try:
        number = int(
            match.group("value")
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        number <= 0
        or number > MAX_RUNTIME_JIN_SIZE_PIXELS
    ):
        return None

    return number


def parse_jin_size_payload(
    payload: str,
) -> dict[str, int] | None:

    text = str(
        payload
        or ""
    ).strip()

    if not text:
        return None

    labeled_values = {}
    labeled_spans = []

    for match in JIN_SIZE_LABELED_RE.finditer(text):
        value = _parse_size_number(
            match.group("value")
        )

        if value is None:
            return None

        label = match.group("label").lower()
        if label in labeled_values:
            return None

        labeled_values[label] = value
        labeled_spans.append(
            match.span()
        )

    if labeled_values:
        remainder_parts = []
        cursor = 0

        for start, end in labeled_spans:
            remainder_parts.append(
                text[cursor:start]
            )
            cursor = end

        remainder_parts.append(
            text[cursor:]
        )
        remainder = "".join(
            remainder_parts
        ).strip()

        if remainder:
            return None

        if len(labeled_values) == 1:
            size = next(
                iter(labeled_values.values())
            )
            return {
                "width": size,
                "height": size,
            }

        return {
            "width": labeled_values["w"],
            "height": labeled_values["h"],
        }

    parts = text.split()

    if len(parts) not in {
        1,
        2,
    }:
        return None

    numbers = [
        _parse_size_number(part)
        for part in parts
    ]

    if any(
        number is None
        for number in numbers
    ):
        return None

    if len(numbers) == 1:
        size = numbers[0]
        return {
            "width": size,
            "height": size,
        }

    return {
        "width": numbers[0],
        "height": numbers[1],
    }


def format_jin_size_payload(
    size,
) -> str:

    if not isinstance(
        size,
        dict,
    ):
        return ""

    try:
        width = int(
            size.get("width")
        )
        height = int(
            size.get("height")
        )
    except (
        TypeError,
        ValueError,
    ):
        return ""

    if (
        width <= 0
        or height <= 0
    ):
        return ""

    if width == height:
        return f"{width}px"

    return f"w:{width}px h:{height}px"


def normalize_jin_size_payload(
    payload: str,
) -> str:

    return format_jin_size_payload(
        parse_jin_size_payload(
            payload
        )
    )


def normalize_jin_size_dict(
    value,
) -> dict[str, int] | None:

    if isinstance(
        value,
        dict,
    ):
        width = value.get(
            "width",
            value.get(
                "w",
            ),
        )
        height = value.get(
            "height",
            value.get(
                "h",
            ),
        )

        if height is None:
            height = width

        if width is None:
            width = height

        width_number = _parse_size_number(
            width
        )
        height_number = _parse_size_number(
            height
        )

        if (
            width_number is None
            or height_number is None
        ):
            return None

        return {
            "width": width_number,
            "height": height_number,
        }

    parsed = parse_jin_size_payload(
        value
    )

    return parsed


def get_applied_jin_size(
    context=None,
) -> dict[str, int]:

    current_size = dict(
        DEFAULT_RUNTIME_JIN_SIZE
    )

    for event in getattr(
        context,
        "runtime_action_events",
        [],
    ) or []:
        if not isinstance(
            event,
            dict,
        ):
            continue

        event_name = str(
            event.get("name")
            or event.get("action")
            or ""
        ).strip().casefold()

        if event_name != "jin_size":
            continue

        if (
            str(
                event.get("status")
                or ""
            ).strip().casefold()
            == "failed"
            or event.get("error")
        ):
            continue

        size = normalize_jin_size_dict(
            event.get("size")
            or event.get("payload")
            or ""
        )

        if size:
            current_size = size

    return current_size


def is_noop_jin_size_action(
    context,
    action,
) -> bool:

    if (
        getattr(
            action,
            "name",
            "",
        )
        != RUNTIME_ACTION_JIN_SIZE
    ):
        return False

    size = normalize_jin_size_dict(
        getattr(
            action,
            "payload",
            "",
        )
    )

    return bool(
        size
        and size == get_applied_jin_size(
            context
        )
    )


def build_jin_size_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = normalize_jin_size_payload(
        query
    )

    if not payload:
        return None

    return payload
