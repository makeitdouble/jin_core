import json
import re

from .action_payload_utils import (
    _clean_internal_action_query,
    _is_placeholder_internal_query,
)


def build_web_search_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    query = _clean_internal_action_query(
        query
    )

    if _is_placeholder_internal_query(
        query,
        placeholder_payloads,
    ):
        return None

    return json.dumps(
        {
            "query": query,
        },
        ensure_ascii=False,
    )


def extract_search_query(
    payload: str,
) -> str:

    payload = (
        payload
        or ""
    ).strip()

    if not payload:
        return ""

    data = payload

    for _ in range(2):

        if not isinstance(
            data,
            str,
        ):
            break

        stripped_data = data.strip()

        if not stripped_data:
            return ""

        if _is_ellipsis_placeholder(
            stripped_data
        ):
            return ""

        try:
            data = json.loads(
                stripped_data
            )

        except json.JSONDecodeError:
            return stripped_data

    if isinstance(
        data,
        str,
    ):
        stripped_data = data.strip()

        if _is_ellipsis_placeholder(
            stripped_data
        ):
            return ""

        return stripped_data

    if not isinstance(
        data,
        dict,
    ):
        return payload

    query = data.get(
        "query",
        "",
    )

    if not isinstance(
        query,
        str,
    ):
        return ""

    return extract_search_query(
        query
    )


def _is_ellipsis_placeholder(
    value: str,
) -> bool:

    token = (
        value
        or ""
    ).strip()

    token = token.strip(
        "`'\""
    ).strip()

    if (
        token.startswith("{")
        and token.endswith("}")
    ):
        token = token[
            1:-1
        ].strip()

    token = token.strip(
        "`'\""
    ).strip()

    return bool(
        token
        and re.fullmatch(
            r"(?:\.{3,}|\u2026)+",
            token,
        )
    )
