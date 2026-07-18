from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "behavior_contract.json"
)


@lru_cache(maxsize=1)
def get_behavior_contract() -> dict[str, Any]:
    with _CONTRACT_PATH.open(
        "r",
        encoding="utf-8",
    ) as contract_file:
        return json.load(
            contract_file
        )


def get_action_guards() -> dict[str, Any]:
    guards = get_behavior_contract().get(
        "action_guards",
        {},
    )

    if not isinstance(
        guards,
        dict,
    ):
        return {}

    return guards


def get_action_guard(
    name: str,
) -> dict[str, Any]:
    guard = get_action_guards().get(
        name,
        {},
    )

    if not isinstance(
        guard,
        dict,
    ):
        return {}

    return guard


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
    normalized_action = str(
        runtime_action
        or ""
    ).strip().casefold()

    if not normalized_action:
        return ""

    for name, guard in get_action_guards().items():
        if not isinstance(
            guard,
            dict,
        ):
            continue

        guard_action = str(
            guard.get(
                "runtime_action",
                "",
            )
            or ""
        ).strip().casefold()

        if guard_action == normalized_action:
            return str(
                name
            )

    return ""


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
    normalized_text = _normalize_guard_text(
        user_text
    )

    if not normalized_text:
        return False

    return any(
        _has_guard_trigger(
            normalized_text,
            _normalize_guard_text(
                blocker
            ),
        )
        for blocker in get_action_guard_blockers(
            name
        )
    )


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


def should_pause_action_guard_for_confirmation(
    name: str,
    user_text: str,
) -> bool:
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
) -> bool:
    normalized_text = _normalize_guard_text(
        user_text
    )

    if not normalized_text:
        return False

    if action_guard_has_blocker_match(
        name,
        user_text,
    ):
        return False

    return action_guard_has_trigger_match(
        name,
        user_text,
    )
