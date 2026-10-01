import re

from contracts.rules_assembler import RUNTIME_ACTION_JIN_POSITION


MAX_RUNTIME_JIN_POSITION_PIXELS = 100000

JIN_POSITION_VALUE_RE = re.compile(
    r"[+-]?\d+(?:px)?",
    re.IGNORECASE,
)


def _parse_position_number(value) -> int | None:
    text = str(value if value is not None else "").strip().lower()

    if text.endswith("px"):
        text = text[:-2].strip()

    if not re.fullmatch(r"[+-]?\d+", text):
        return None

    try:
        number = int(text)
    except (TypeError, ValueError):
        return None

    if abs(number) > MAX_RUNTIME_JIN_POSITION_PIXELS:
        return None

    return number


def parse_jin_position_payload(payload: str) -> dict[str, int] | None:
    text = str(payload or "").strip()

    if not text:
        return None

    labeled_x = re.search(
        r"\bx\s*:\s*([+-]?\d+(?:px)?)\b",
        text,
        re.IGNORECASE,
    )
    labeled_y = re.search(
        r"\by\s*:\s*([+-]?\d+(?:px)?)\b",
        text,
        re.IGNORECASE,
    )

    if labeled_x or labeled_y:
        if not labeled_x or not labeled_y:
            return None
        raw_values = [
            labeled_x.group(1),
            labeled_y.group(1),
        ]
    else:
        raw_values = [
            match.group(0)
            for match in JIN_POSITION_VALUE_RE.finditer(text)
        ][:2]

        if len(raw_values) != 2:
            return None

    x = _parse_position_number(raw_values[0])
    y = _parse_position_number(raw_values[1])

    if x is None or y is None:
        return None

    return {
        "x": x,
        "y": y,
    }


def normalize_jin_position_dict(value) -> dict[str, int] | None:
    if isinstance(value, dict):
        x = _parse_position_number(value.get("x"))
        y = _parse_position_number(value.get("y"))

        if x is None or y is None:
            return None

        return {
            "x": x,
            "y": y,
        }

    return parse_jin_position_payload(value)


def format_jin_position_payload(position) -> str:
    normalized = normalize_jin_position_dict(position)

    if not normalized:
        return ""

    return f"x:{normalized['x']}px y:{normalized['y']}px"


def normalize_jin_position_payload(payload: str) -> str:
    return format_jin_position_payload(
        parse_jin_position_payload(payload)
    )


def build_jin_position_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    payload = normalize_jin_position_payload(query)

    if not payload:
        return None

    return payload


def get_applied_jin_position(context=None) -> dict[str, int] | None:
    current_position = None

    for event in getattr(
        context,
        "runtime_action_events",
        [],
    ) or []:
        if not isinstance(event, dict):
            continue

        event_name = str(
            event.get("name")
            or event.get("action")
            or ""
        ).strip().casefold()

        if event_name != "jin_position":
            continue

        if (
            str(event.get("status") or "").strip().casefold()
            == "failed"
            or event.get("error")
        ):
            continue

        position = normalize_jin_position_dict(
            {
                "x": event.get("x"),
                "y": event.get("y"),
            }
        ) or normalize_jin_position_dict(
            event.get("position")
            or event.get("payload")
            or ""
        )

        if position:
            current_position = position

    return current_position


def is_noop_jin_position_action(context, action) -> bool:
    if getattr(action, "name", "") != RUNTIME_ACTION_JIN_POSITION:
        return False

    position = normalize_jin_position_dict(
        getattr(action, "payload", "")
    )
    current = get_applied_jin_position(context)

    return bool(
        position
        and current
        and position == current
    )
