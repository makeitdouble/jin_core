from __future__ import annotations

import re

from .action_payload_utils import _build_internal_action_payload


FACT_ID_RE = re.compile(r"^F([1-9]\d*)$", re.IGNORECASE)


def normalize_recall_fact_context_id(value) -> str:
    match = FACT_ID_RE.fullmatch(str(value or "").strip())
    if not match:
        return ""
    return f"F{int(match.group(1))}"


def build_recall_fact_context_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    payload = _build_internal_action_payload(
        query,
        placeholder_payloads,
        reject_placeholders=False,
    )
    fact_id = normalize_recall_fact_context_id(payload)
    return fact_id or payload
