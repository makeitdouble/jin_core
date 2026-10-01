import math
import re

from contracts.rules_assembler import RUNTIME_ACTION_JIN_SIZE


DEFAULT_RUNTIME_JIN_SIZE = {
    "width": 120,
    "height": 120,
}

MAX_RUNTIME_JIN_SIZE_VALUE = 10000

JIN_SIZE_NUMBER_RE = re.compile(
    r"^(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+))"
    r"\s*(?P<unit>px|vw|vh|%)?$",
    re.IGNORECASE,
)

JIN_SIZE_VALUE_RE = re.compile(
    r"(?<![a-zA-Z0-9_.])"
    r"(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
    r"\s*(?:px|vw|vh|%)?)"
    r"(?![a-zA-Z0-9_.%])",
    re.IGNORECASE,
)

JIN_SIZE_LABEL_PREFIX_RE = re.compile(
    r"(?<![a-zA-Z0-9_])(?:width|height|w|h)\s*[:=]",
    re.IGNORECASE,
)

JIN_SIZE_EXPLICIT_ALPHA_UNIT_RE = re.compile(
    r"(?<![a-zA-Z0-9_.])"
    r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?P<unit>[a-zA-Z]+)"
    r"(?![a-zA-Z0-9_])"
    r"(?!\s*[:=])",
    re.IGNORECASE,
)

JIN_SIZE_LABELED_VALUE_RE = re.compile(
    r"(?<![a-zA-Z0-9_])"
    r"(?P<label>width|height|w|h)\s*[:=]\s*"
    r"(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
    r"\s*(?:px|vw|vh|%)?)"
    r"(?![a-zA-Z0-9_.%])",
    re.IGNORECASE,
)


def _format_size_number(
    value: float,
) -> str:

    if value.is_integer():
        return str(int(value))

    return (
        f"{value:.6f}"
        .rstrip("0")
        .rstrip(".")
    )


def _parse_size_value(
    value,
) -> int | float | str | None:

    if isinstance(value, bool):
        return None

    match = JIN_SIZE_NUMBER_RE.fullmatch(
        str(value or "").strip()
    )

    if match is None:
        return None

    try:
        number = float(
            match.group("value")
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        not math.isfinite(number)
        or number <= 0
        or number > MAX_RUNTIME_JIN_SIZE_VALUE
    ):
        return None

    unit = str(
        match.group("unit")
        or "px"
    ).casefold()

    if unit == "px":
        return (
            int(number)
            if number.is_integer()
            else number
        )

    return f"{_format_size_number(number)}{unit}"


def format_jin_size_value(
    value,
) -> str:

    normalized = _parse_size_value(
        value
    )

    if normalized is None:
        return ""

    if isinstance(normalized, str):
        return normalized

    return (
        f"{_format_size_number(float(normalized))}px"
    )


def parse_jin_size_payload(
    payload: str,
) -> dict[str, int | float | str] | None:

    text = str(
        payload
        or ""
    ).strip()

    if not text:
        return None

    if any(
        str(match.group("unit") or "").casefold()
        not in {"px", "vw", "vh"}
        for match in JIN_SIZE_EXPLICIT_ALPHA_UNIT_RE.finditer(
            text
        )
    ):
        return None

    label_prefixes = list(
        JIN_SIZE_LABEL_PREFIX_RE.finditer(
            text
        )
    )

    if label_prefixes:
        labeled_matches = list(
            JIN_SIZE_LABELED_VALUE_RE.finditer(
                text
            )
        )

        if len(labeled_matches) != len(label_prefixes):
            return None

        dimensions = {}

        for match in labeled_matches:
            label = str(
                match.group("label")
                or ""
            ).casefold()
            dimension = (
                "width"
                if label in {"w", "width"}
                else "height"
            )

            if dimension in dimensions:
                return None

            normalized = _parse_size_value(
                match.group("value")
            )

            if normalized is None:
                return None

            dimensions[dimension] = normalized

        width = dimensions.get("width")
        height = dimensions.get("height")

        if width is None:
            width = height

        if height is None:
            height = width

        if width is None or height is None:
            return None

        return {
            "width": width,
            "height": height,
        }

    raw_values = [
        match.group("value")
        for match in JIN_SIZE_VALUE_RE.finditer(text)
    ]

    if not raw_values:
        return None

    values = []

    for raw_value in raw_values[:2]:
        normalized = _parse_size_value(
            raw_value
        )

        if normalized is None:
            return None

        values.append(
            normalized
        )

    if len(values) == 1:
        return {
            "width": values[0],
            "height": values[0],
        }

    return {
        "width": values[0],
        "height": values[1],
    }


def format_jin_size_payload(
    size,
) -> str:

    if not isinstance(
        size,
        dict,
    ):
        return ""

    normalized = normalize_jin_size_dict(
        size
    )

    if not normalized:
        return ""

    width = format_jin_size_value(
        normalized["width"]
    )
    height = format_jin_size_value(
        normalized["height"]
    )

    if width == height:
        return width

    return f"w:{width} h:{height}"


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
) -> dict[str, int | float | str] | None:

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

        width_value = _parse_size_value(
            width
        )
        height_value = _parse_size_value(
            height
        )

        if (
            width_value is None
            or height_value is None
        ):
            return None

        return {
            "width": width_value,
            "height": height_value,
        }

    parsed = parse_jin_size_payload(
        value
    )

    return parsed


def get_applied_jin_size(
    context=None,
) -> dict[str, int | float | str]:

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
