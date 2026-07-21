from contracts.rules_assembler import (
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_REMOVE_SKILL,
)

from .action_payload_utils import _clean_internal_action_query


def plural_skill_marker_action_name(
    action_name: str,
) -> str | None:

    normalized_name = (
        str(action_name)
        .strip()
        .upper()
    )

    if normalized_name == "APPEND_SKILLS":
        return RUNTIME_ACTION_APPEND_SKILL

    if normalized_name == "REMOVE_SKILLS":
        return RUNTIME_ACTION_REMOVE_SKILL

    return None


def split_internal_skill_marker_list(
    query: str,
) -> tuple[str, ...]:

    return tuple(
        skill_name
        for skill_name in (
            part.strip()
            for part in _clean_internal_action_query(
                query
            ).split(",")
        )
        if skill_name
    )


def build_append_skill_payload(
    query: str,
    placeholder_payloads=(),
) -> str:

    return _clean_internal_action_query(
        query
    )
