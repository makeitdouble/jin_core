# Renders runtime action results as readable text for <TOOL_RESULT> blocks.
import re


def _humanize_key(value: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    return text[:1].upper() + text[1:] if text else "Value"


def _format_scalar(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "none"
    return str(value)


def _compact_turn_id(value) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"turn_0*(\d+)", text)
    if match:
        return f"turn_{int(match.group(1))}"
    return text or "turn_unknown"


def _append_compact_messages(
    lines: list[str],
    value,
    *,
    indent: str,
) -> None:
    lines.append(f"{indent}Messages:")
    if not value:
        lines.append(f"{indent}  none")
        return

    for index, item in enumerate(value):
        if index:
            lines.append("")

        if not isinstance(item, dict):
            lines.append(f"{indent}  {_format_scalar(item)}")
            continue

        turn_id = _compact_turn_id(item.get("turn_id"))
        timestamp = str(item.get("timestamp") or "").strip()
        header = turn_id if not timestamp else f"{turn_id} | {timestamp}"
        lines.append(f"{indent}  {header}")

        role = str(item.get("role") or "message").strip() or "message"
        text = str(item.get("text") or "").strip()
        text_lines = text.splitlines() if text else []
        if not text_lines:
            lines.append(f"{indent}  {role}:")
            continue

        lines.append(f"{indent}  {role}: {text_lines[0]}")
        lines.extend(f"{indent}  {line}" for line in text_lines[1:])


def _append_value(
    lines: list[str],
    label: str,
    value,
    *,
    indent: str = "",
    compact_messages: bool = False,
) -> None:
    if compact_messages and label == "Messages" and isinstance(value, (list, tuple)):
        _append_compact_messages(lines, value, indent=indent)
        return
    if isinstance(value, dict):
        lines.append(f"{indent}{label}:")
        if not value:
            lines.append(f"{indent}  none")
            return

        for key, nested_value in value.items():
            _append_value(
                lines,
                _humanize_key(key),
                nested_value,
                indent=indent + "  ",
                compact_messages=compact_messages,
            )
        return

    if isinstance(value, (list, tuple)):
        lines.append(f"{indent}{label}:")
        if not value:
            lines.append(f"{indent}  none")
            return

        for item in value:
            if isinstance(item, dict):
                item_lines: list[str] = []
                for key, nested_value in item.items():
                    _append_value(
                        item_lines,
                        _humanize_key(key),
                        nested_value,
                        compact_messages=compact_messages,
                    )
                if item_lines:
                    lines.append(f"{indent}  - {item_lines[0]}")
                    lines.extend(
                        f"{indent}    {line}"
                        for line in item_lines[1:]
                    )
                continue

            lines.append(
                f"{indent}  - {_format_scalar(item)}"
            )
        return

    text = _format_scalar(value)
    if "\n" in text:
        lines.append(f"{indent}{label}:")
        lines.extend(
            f"{indent}  {line}"
            for line in text.splitlines()
        )
        return

    lines.append(f"{indent}{label}: {text}")


def _runtime_action_for_result(
    result: dict,
    runtime_action: str,
) -> str:
    candidate = str(
        runtime_action
        or result.get("runtime_action_name")
        or result.get("action")
        or ""
    ).strip()

    if not candidate:
        return ""

    try:
        from contracts.rules_assembler import get_runtime_action_name

        return (
            get_runtime_action_name(candidate)
            or candidate.upper()
        )
    except Exception:
        return candidate.upper()


def _failure_reason(result: dict) -> str:
    for key in (
        "detail",
        "failure",
        "failure_reason",
        "failure_followup_message",
    ):
        value = str(
            result.get(key, "")
            or ""
        ).strip()
        if value:
            return value

    error = str(
        result.get("error", "")
        or ""
    ).strip()
    if error:
        return error.replace("_", " ")

    return "action failed"


def _action_schema(runtime_action: str) -> tuple[str, ...]:
    if not runtime_action:
        return ()

    try:
        from contracts.rules_assembler import get_runtime_action_schema

        return get_runtime_action_schema(runtime_action)
    except Exception:
        return ()


def _append_applied_changes(
    lines: list[str],
    changes,
) -> None:
    if not isinstance(changes, (list, tuple)):
        return

    change_lines = []
    for change in changes:
        if not isinstance(change, dict):
            continue

        field = str(
            change.get("field", "")
            or ""
        ).strip()
        if not field:
            continue

        before = change.get("before")
        after = change.get("after")

        if before is not None and str(before) != "":
            change_lines.append(
                f"  - {field}: {before} -> {after}"
            )
        else:
            change_lines.append(
                f"  - {field}: {after}"
            )

    if not change_lines:
        return

    lines.append("")
    lines.append("Applied changes:")
    lines.extend(change_lines)


def format_runtime_action_result(
    result,
    *,
    runtime_action: str = "",
) -> str:
    """Format one action result without serializing the result object as JSON."""

    if not isinstance(result, dict):
        lines: list[str] = []
        _append_value(lines, "Result", result)
        return "\n".join(lines).strip()

    action_name = _runtime_action_for_result(
        result,
        runtime_action,
    )
    ok = result.get("ok") is not False
    lines: list[str] = []

    result_id = str(
        result.get("id")
        or result.get("requested_id")
        or ""
    ).strip()

    if result_id:
        if "ACTIVE_MEMORY" in action_name:
            lines.append(
                f"Active memory id: {result_id}"
            )
        else:
            lines.append(
                f"Result id: {result_id}"
            )

    lines.append(
        f"Status: {'success' if ok else 'failed'}"
    )

    if not ok:
        lines.append(
            f"Reason: {_failure_reason(result)}"
        )

        error_code = str(
            result.get("error", "")
            or ""
        ).strip()
        if error_code:
            lines.append(
                f"Error code: {error_code}"
            )

        provided_payload = result.get("payload")
        if provided_payload is None and "requested" in result:
            provided_payload = result.get("requested")

        if (
            provided_payload is not None
            and str(provided_payload).strip()
        ):
            lines.append("")
            lines.append("Provided payload:")
            lines.extend(
                f"  {line}"
                for line in str(provided_payload).splitlines()
            )

        schema = _action_schema(action_name)
        if schema:
            lines.append("")
            lines.append("Correct action schema:")
            lines.extend(
                f"  {line}"
                for line in schema
            )

        for key in (
            "available_fields",
            "available_ids",
        ):
            value = result.get(key)
            if value in (None, "", [], {}):
                continue

            lines.append("")
            _append_value(
                lines,
                _humanize_key(key),
                value,
            )

        return "\n".join(lines).strip()

    _append_applied_changes(
        lines,
        result.get("changes"),
    )

    consumed_keys = {
        "ok",
        "action",
        "runtime_action_name",
        "error",
        "detail",
        "failure",
        "failure_reason",
        "failure_followup_message",
        "payload",
        "id",
        "requested_id",
        "requested",
        "changes",
    }

    for key, value in result.items():
        if (
            key in consumed_keys
            or value in (None, "", [], {})
        ):
            continue

        lines.append("")
        _append_value(
            lines,
            _humanize_key(key),
            value,
            compact_messages=(action_name == "RECALL_FACT_CONTEXT"),
        )

    return "\n".join(lines).strip()
