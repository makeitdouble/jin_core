from .action_payload_utils import (
    _build_internal_action_payload,
)


def build_check_todo_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return _build_internal_action_payload(
        query,
        placeholder_payloads,
    )
