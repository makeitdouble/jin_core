from contracts.rules_assembler import get_internal_actions_with_payload

from .regexp_utils import extract_private_marker_parts


def _normalize_internal_action_placeholder(
    value: str,
) -> str:

    value = (
        value
        or ""
    ).strip()

    parts = [
        part.strip()
        for part in value.split("|")
        if part.strip()
    ]

    if parts:
        value = " | ".join(
            parts
        )

    return value.casefold().strip(
        "`'\"<>"
    ).strip()


def _get_internal_action_marker_payload(
    marker: str,
) -> str:

    _, payload = extract_private_marker_parts(
        marker
    )

    return " | ".join(
        part.strip()
        for part in payload.split("|")
        if part.strip()
    )


def _get_internal_action_placeholder_payloads(
    markers=None,
) -> tuple[str, ...]:

    markers = (
        markers
        if markers is not None
        else get_internal_actions_with_payload()
    )

    payloads = []

    for marker in markers:
        payload = _get_internal_action_marker_payload(
            marker
        )

        if (
            payload
            and payload not in payloads
        ):
            payloads.append(
                payload
            )

    return tuple(
        payloads
    )

def _clean_internal_action_query(
    query: str,
) -> str:

    return (
        query
        or ""
    ).strip().strip(
        "*_`~"
    ).strip()

def _is_placeholder_internal_query(
    query: str,
    placeholder_payloads=(),
) -> bool:

    normalized_query = _normalize_internal_action_placeholder(
        query
    )

    if normalized_query in {
        "",
        "...",
    }:
        return True

    placeholder_payloads = {
        _normalize_internal_action_placeholder(
            payload
        )
        for payload in placeholder_payloads
    }

    return normalized_query in placeholder_payloads
