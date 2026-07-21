from .action_payload_utils import (
    _clean_internal_action_query,
    _is_placeholder_internal_query,
)


def build_asset_action_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = _clean_internal_action_query(
        query
    )

    if _is_placeholder_internal_query(
        payload,
        placeholder_payloads,
    ):
        return None

    return payload
