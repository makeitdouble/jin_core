from .action_payload_utils import (
    _build_internal_action_payload,
)
from .delayed_memory_utils import is_delayed_memory_report_id


def build_append_delayed_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = _build_internal_action_payload(
        query,
        placeholder_payloads,
    )

    if (
        payload is None
        or not is_delayed_memory_report_id(
            payload
        )
    ):
        return None

    return payload.casefold()
