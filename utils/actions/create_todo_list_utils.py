from .action_payload_utils import _clean_internal_action_query


def build_create_todo_list_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = _clean_internal_action_query(
        query
    )

    if not payload:
        return None

    return payload
