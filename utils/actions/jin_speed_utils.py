import re

from contracts.rules_assembler import RUNTIME_ACTION_JIN_SPEED


DEFAULT_RUNTIME_JIN_SPEED = 900
MIN_RUNTIME_JIN_SPEED = 1
MAX_RUNTIME_JIN_SPEED = 100000

JIN_SPEED_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?:px\s*/\s*s|pxps|px\s*/\s*sec|px\s*/\s*second)?\s*$",
    re.IGNORECASE,
)


def normalize_jin_speed_value(value) -> int | None:
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = JIN_SPEED_RE.fullmatch(
            str(value or "")
        )

        if match is None:
            return None

        try:
            number = float(match.group("value"))
        except (TypeError, ValueError):
            return None

    if (
        not number
        or number < MIN_RUNTIME_JIN_SPEED
        or number > MAX_RUNTIME_JIN_SPEED
    ):
        return None

    return int(round(number))


def format_jin_speed_payload(speed) -> str:
    normalized = normalize_jin_speed_value(speed)

    if normalized is None:
        return ""

    return f"{normalized}px/s"


def normalize_jin_speed_payload(payload: str) -> str:
    return format_jin_speed_payload(payload)


def build_jin_speed_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    payload = normalize_jin_speed_payload(query)

    if not payload:
        return None

    return payload


def get_applied_jin_speed(context=None) -> int:
    current_speed = DEFAULT_RUNTIME_JIN_SPEED

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

        if event_name != "jin_speed":
            continue

        if (
            str(event.get("status") or "").strip().casefold()
            == "failed"
            or event.get("error")
        ):
            continue

        speed = normalize_jin_speed_value(
            event.get("speed")
            or event.get("payload")
            or ""
        )

        if speed is not None:
            current_speed = speed

    return current_speed


def is_noop_jin_speed_action(context, action) -> bool:
    if getattr(action, "name", "") != RUNTIME_ACTION_JIN_SPEED:
        return False

    speed = normalize_jin_speed_value(
        getattr(action, "payload", "")
    )

    return bool(
        speed is not None
        and speed == get_applied_jin_speed(context)
    )
