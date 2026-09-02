from __future__ import annotations

from typing import Any

from contracts.rules_assembler import (
    get_action_contract,
    get_action_contract_name_for_runtime_action,
    get_action_contracts,
    get_behavior_contract as load_behavior_contract,
)


def get_behavior_contract() -> dict[str, Any]:
    return load_behavior_contract()


def get_action_guards() -> dict[str, Any]:
    return get_action_contracts()


def get_action_guard(
    name: str,
) -> dict[str, Any]:
    return get_action_contract(name)


def _get_action_guard_strings(
    name: str,
    key: str,
) -> tuple[str, ...]:
    values = get_action_guard(
        name
    ).get(
        key,
        (),
    )

    if not isinstance(
        values,
        list,
    ):
        return ()

    return tuple(
        value
        for value in values
        if isinstance(
            value,
            str,
        )
    )


def get_action_guard_triggers(
    name: str,
) -> tuple[str, ...]:
    return _get_action_guard_strings(
        name,
        "triggers",
    )


def get_action_guard_blockers(
    name: str,
) -> tuple[str, ...]:
    return _get_action_guard_strings(
        name,
        "blockers",
    )


def get_action_guard_name_for_runtime_action(
    runtime_action: str,
) -> str:
    return get_action_contract_name_for_runtime_action(
        runtime_action
    )


def _normalize_guard_text(
    text: str,
) -> str:
    return (
        text
        or ""
    ).casefold().replace(
        "ё",
        "е",
    )


def _has_guard_trigger(
    normalized_text: str,
    normalized_trigger: str,
) -> bool:

    if not normalized_trigger:
        return False

    start = 0

    while True:
        index = normalized_text.find(
            normalized_trigger,
            start,
        )

        if index < 0:
            return False

        before_index = index - 1
        after_index = index + len(
            normalized_trigger
        )

        before_ok = (
            before_index < 0
            or not normalized_text[before_index].isalnum()
        )
        after_ok = (
            after_index >= len(normalized_text)
            or not normalized_text[after_index].isalnum()
        )

        if before_ok and after_ok:
            return True

        start = index + 1


def action_guard_has_blocker_match(
    name: str,
    user_text: str,
) -> bool:
    return bool(
        get_action_guard_blocker_match(
            name,
            user_text,
        )
    )


def get_action_guard_blocker_match(
    name: str,
    user_text: str,
) -> str:
    normalized_text = _normalize_guard_text(
        user_text
    )

    if not normalized_text:
        return ""

    for blocker in get_action_guard_blockers(
        name
    ):
        if _has_guard_trigger(
            normalized_text,
            _normalize_guard_text(
                blocker
            ),
        ):
            return blocker

    return ""


def action_guard_has_trigger_match(
    name: str,
    user_text: str,
) -> bool:
    normalized_text = _normalize_guard_text(
        user_text
    )

    if not normalized_text:
        return False

    return any(
        _has_guard_trigger(
            normalized_text,
            _normalize_guard_text(
                trigger
            ),
        )
        for trigger in get_action_guard_triggers(
            name
        )
    )


def action_guard_has_exact_trigger_match(
    name: str,
    user_text: str,
) -> bool:
    """Match only a bare configured trigger, ignoring outer whitespace.

    This is intentionally stricter than ``action_guard_has_trigger_match``:
    surrounding prose, punctuation, attachments, or any extra text must fall
    through to the normal model-driven path.
    """

    normalized_text = _normalize_guard_text(
        user_text
    ).strip()

    if not normalized_text:
        return False

    if action_guard_has_blocker_match(
        name,
        user_text,
    ):
        return False

    return any(
        normalized_text
        == _normalize_guard_text(
            trigger
        ).strip()
        for trigger in get_action_guard_triggers(
            name
        )
        if str(
            trigger
            or ""
        ).strip()
    )


def project_review_allows_report(name: str, context=None) -> bool:
    from utils.project_reader import project_review_active

    return name == "save_delayed_memory" and project_review_active(context)


def should_pause_action_guard_for_confirmation(
    name: str,
    user_text: str,
    *,
    context=None,
) -> bool:
    if project_review_allows_report(name, context):
        return False
    return (
        bool(get_action_guard_triggers(name))
        and not action_guard_has_blocker_match(
            name,
            user_text,
        )
        and not action_guard_has_trigger_match(
            name,
            user_text,
        )
    )


def should_execute_action_guard(
    name: str,
    user_text: str,
    *,
    context=None,
) -> bool:
    normalized_text = _normalize_guard_text(
        user_text
    )

    if action_guard_has_blocker_match(
        name,
        user_text,
    ):
        return False

    if project_review_allows_report(name, context):
        return True

    if not normalized_text:
        return False

    if not get_action_guard_triggers(
        name
    ):
        return True

    return action_guard_has_trigger_match(
        name,
        user_text,
    )


def should_prearm_action_guard(
    name: str,
    user_text: str,
) -> bool:
    return (
        bool(get_action_guard_triggers(name))
        and should_execute_action_guard(
            name,
            user_text,
        )
    )
