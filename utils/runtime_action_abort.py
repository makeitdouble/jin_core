from contracts.rules_assembler import (
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)


RUNTIME_ACTION_ABORTED_STATUS = "aborted"
RUNTIME_ACTION_ABORTED_LABEL = "ABORTED"


def normalize_runtime_action_key(
        action: str,
) -> str:

    return str(
        action
        or ""
    ).strip().lower()


def build_runtime_action_aborted_text(
        action: str,
        display_name: str = "",
) -> str:

    resolved_name = str(
        display_name
        or get_runtime_action_display_name(
            action
        )
        or action
        or "runtime_action"
    ).strip()

    return f"{resolved_name}: {RUNTIME_ACTION_ABORTED_LABEL}"


def ensure_runtime_active_actions(
        context,
) -> list[dict]:

    active_actions = getattr(
        context,
        "runtime_active_action_markers",
        None,
    )

    if not isinstance(
        active_actions,
        list,
    ):
        active_actions = []
        context.runtime_active_action_markers = active_actions

    return active_actions


def _runtime_action_matches(
        record: dict,
        *,
        action: str,
        action_id: str = "",
) -> bool:

    if not isinstance(
        record,
        dict,
    ):
        return False

    if normalize_runtime_action_key(
        record.get("action")
    ) != normalize_runtime_action_key(
        action
    ):
        return False

    normalized_id = str(
        action_id
        or ""
    ).strip()

    if not normalized_id:
        return True

    return str(
        record.get("id")
        or ""
    ).strip() == normalized_id


def _runtime_action_record_key(
        record: dict,
) -> tuple[str, str]:

    return (
        normalize_runtime_action_key(
            record.get("action")
        ),
        str(
            record.get("id")
            or ""
        ).strip(),
    )


def mark_runtime_action_started(
        context,
        *,
        action: str,
        action_id: str = "",
        display_name: str = "",
        text: str = "",
        payload: str = "",
        detail: str = "",
        close_tag: bool | None = None,
        context_snapshot: dict | None = None,
) -> dict | None:

    if context is None:
        return None

    normalized_action = normalize_runtime_action_key(
        action
    )

    if not normalized_action:
        return None

    resolved_display_name = str(
        display_name
        or get_runtime_action_display_name(
            normalized_action
        )
    ).strip()

    resolved_close_tag = (
        runtime_action_has_close_tag(
            normalized_action
        )
        if close_tag is None
        else bool(close_tag)
    )

    resolved_text = str(
        text
        or build_runtime_action_display_text(
            normalized_action,
            payload,
        )
        or resolved_display_name
    ).strip()

    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    record = {
        "action": normalized_action,
        "display_name": resolved_display_name,
        "text": resolved_text,
        "close_tag": resolved_close_tag,
    }

    normalized_id = str(
        action_id
        or ""
    ).strip()
    if normalized_id:
        record["id"] = normalized_id

    normalized_payload = str(
        payload
        or ""
    ).strip()
    if normalized_payload:
        record["payload"] = normalized_payload

    normalized_detail = str(
        detail
        or ""
    ).strip()
    if normalized_detail:
        record["detail"] = normalized_detail

    if runtime_turn_id:
        record["runtime_turn_id"] = runtime_turn_id

    if isinstance(
        context_snapshot,
        dict,
    ):
        record["context"] = dict(
            context_snapshot
        )

    active_actions = ensure_runtime_active_actions(
        context
    )
    record_key = _runtime_action_record_key(
        record
    )

    for index, existing in enumerate(
        active_actions
    ):
        if _runtime_action_record_key(
            existing
        ) == record_key:
            active_actions[index] = {
                **existing,
                **record,
            }
            return active_actions[index]

    active_actions.append(
        record
    )

    return record


def mark_runtime_action_completed(
        context,
        *,
        action: str,
        action_id: str = "",
) -> None:

    if context is None:
        return

    active_actions = ensure_runtime_active_actions(
        context
    )

    active_actions[:] = [
        record
        for record in active_actions
        if not _runtime_action_matches(
            record,
            action=action,
            action_id=action_id,
        )
    ]


def mark_runtime_actions_completed(
        context,
        actions,
        *,
        keep_actions: set[str] | None = None,
) -> None:

    keep = {
        normalize_runtime_action_key(
            action
        )
        for action in (
            keep_actions
            or set()
        )
    }

    for action in actions or ():
        action_name = normalize_runtime_action_key(
            getattr(
                action,
                "name",
                action,
            )
        )

        if (
            not action_name
            or action_name in keep
        ):
            continue

        mark_runtime_action_completed(
            context,
            action=action_name,
        )


def append_runtime_aborted_action_memory(
        context,
        record: dict,
) -> dict:

    aborted_actions = getattr(
        context,
        "runtime_turn_aborted_actions",
        None,
    )

    if not isinstance(
        aborted_actions,
        list,
    ):
        aborted_actions = []
        context.runtime_turn_aborted_actions = aborted_actions

    memory_record = {
        "name": str(
            record.get("display_name")
            or get_runtime_action_display_name(
                record.get("action", "")
            )
            or record.get("action")
            or "runtime_action"
        ).strip(),
        "action": normalize_runtime_action_key(
            record.get("action")
        ),
        "status": RUNTIME_ACTION_ABORTED_STATUS,
    }

    action_id = str(
        record.get("id")
        or ""
    ).strip()
    if action_id:
        memory_record["id"] = action_id

    runtime_turn_id = str(
        record.get("runtime_turn_id")
        or getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()
    if runtime_turn_id:
        memory_record["runtime_turn_id"] = runtime_turn_id

    aborted_actions.append(
        memory_record
    )

    return memory_record


async def abort_active_runtime_actions(
        context,
        *,
        logger=None,
        emit_to_client: bool = True,
        remember_for_l1: bool = True,
) -> list[dict]:

    if context is None:
        return []

    active_actions = ensure_runtime_active_actions(
        context
    )

    if not active_actions:
        _reject_pending_runtime_action_guards(
            context
        )
        return []

    records = list(
        active_actions
    )
    active_actions.clear()

    runtime_events = getattr(
        context,
        "runtime_action_events",
        None,
    )
    if not isinstance(
        runtime_events,
        list,
    ):
        runtime_events = []
        context.runtime_action_events = runtime_events

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    aborted_records = []

    for record in records:
        action = normalize_runtime_action_key(
            record.get("action")
        )
        if not action:
            continue

        display_name = str(
            record.get("display_name")
            or get_runtime_action_display_name(
                action
            )
        ).strip()
        aborted_text = build_runtime_action_aborted_text(
            action,
            display_name,
        )
        action_id = str(
            record.get("id")
            or ""
        ).strip()
        runtime_turn_id = str(
            record.get("runtime_turn_id")
            or getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()

        event = {
            "name": action,
            "status": RUNTIME_ACTION_ABORTED_STATUS,
            "aborted": True,
            "display_name": display_name,
        }
        if action_id:
            event["id"] = action_id
        if runtime_turn_id:
            event["runtime_turn_id"] = runtime_turn_id

        runtime_events.append(
            event
        )

        if remember_for_l1:
            append_runtime_aborted_action_memory(
                context,
                {
                    **record,
                    "display_name": display_name,
                    "runtime_turn_id": runtime_turn_id,
                },
            )

        if log_runtime is not None:
            await log_runtime(
                f"[RUNTIME ACTION] {aborted_text}"
            )

        if (
            emit_to_client
            and emit is not None
        ):
            payload = {
                "type": "runtime_action",
                "action": action,
                "status": RUNTIME_ACTION_ABORTED_STATUS,
                "text": aborted_text,
                "display_name": display_name,
                "close_tag": bool(
                    record.get("close_tag")
                ),
                "aborted": True,
            }
            if action_id:
                payload["id"] = action_id
            if record.get("detail"):
                payload["detail"] = record.get("detail")
            if record.get("payload"):
                payload["payload"] = record.get("payload")
            if isinstance(
                record.get("context"),
                dict,
            ):
                payload["context"] = dict(
                    record["context"]
                )

            await emit(
                payload
            )

        aborted_records.append(
            event
        )

    _clear_pending_runtime_action_ids(
        context,
        records,
    )
    _reject_pending_runtime_action_guards(
        context
    )

    return aborted_records


def _clear_pending_runtime_action_ids(
        context,
        records: list[dict],
) -> None:

    pending_id_attributes = (
        "runtime_pending_asset_action_ids",
        "runtime_pending_delayed_memory_action_ids",
    )
    aborted_ids = {
        str(
            record.get("id")
            or ""
        ).strip()
        for record in records
        if str(
            record.get("id")
            or ""
        ).strip()
    }

    if not aborted_ids:
        return

    for attribute in pending_id_attributes:
        pending_ids = getattr(
            context,
            attribute,
            None,
        )
        if not isinstance(
            pending_ids,
            list,
        ):
            continue

        pending_ids[:] = [
            pending_id
            for pending_id in pending_ids
            if str(
                pending_id
                or ""
            ).strip() not in aborted_ids
        ]


def _reject_pending_runtime_action_guards(
        context,
) -> None:

    pending = getattr(
        context,
        "runtime_action_guard_confirmations",
        None,
    )

    if not isinstance(
        pending,
        dict,
    ):
        return

    for future in list(
        pending.values()
    ):
        done = getattr(
            future,
            "done",
            None,
        )
        set_result = getattr(
            future,
            "set_result",
            None,
        )

        if (
            done is None
            or set_result is None
            or done()
        ):
            continue

        set_result(
            "reject"
        )

    pending.clear()
