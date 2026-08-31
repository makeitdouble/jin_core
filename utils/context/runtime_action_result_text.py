# Renders runtime action results as readable text for <TOOL_RESULT> blocks.


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


def _append_value(
    lines: list[str],
    label: str,
    value,
    *,
    indent: str = "",
) -> None:
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
        )

    return "\n".join(lines).strip()
