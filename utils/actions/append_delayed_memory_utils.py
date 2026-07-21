from .action_payload_utils import (
    _clean_internal_action_query,
    _is_placeholder_internal_query,
)
from .delayed_memory_utils import is_delayed_memory_report_id


def build_append_delayed_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = _clean_internal_action_query(
        query
    ).casefold()

    if (
        _is_placeholder_internal_query(
            payload,
            placeholder_payloads,
        )
        or not is_delayed_memory_report_id(
            payload
        )
    ):
        return None

    return payload
