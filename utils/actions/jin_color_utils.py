import re

from contracts.rules_assembler import RUNTIME_ACTION_JIN_COLOR


DEFAULT_RUNTIME_JIN_COLOR = "#70a9dc"

JIN_COLOR_RE = re.compile(
    r"^\s*#?(?P<hex>[0-9a-f]{3}|[0-9a-f]{6})\s*$",
    re.IGNORECASE,
)

def normalize_jin_color_payload(
    payload: str,
) -> str:

    match = JIN_COLOR_RE.fullmatch(
        str(payload or "")
    )

    if match is None:
        return ""

    color = match.group("hex").lower()

    if len(color) == 3:
        color = "".join(
            char * 2
            for char in color
        )

    return f"#{color}"


def get_applied_jin_color(
    context=None,
) -> str:

    current_color = DEFAULT_RUNTIME_JIN_COLOR

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

        if event_name != "jin_color":
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

        color = normalize_jin_color_payload(
            event.get("color")
            or event.get("payload")
            or ""
        )

        if color:
            current_color = color

    return current_color


def is_noop_jin_color_action(
    context,
    action,
) -> bool:

    if (
        getattr(
            action,
            "name",
            "",
        )
        != RUNTIME_ACTION_JIN_COLOR
    ):
        return False

    color = normalize_jin_color_payload(
        getattr(
            action,
            "payload",
            "",
        )
    )

    return bool(
        color
        and color == get_applied_jin_color(
            context
        )
    )


def build_jin_color_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = normalize_jin_color_payload(
        query
    )

    if not payload:
        return None

    return payload
