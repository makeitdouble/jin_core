"""Bound recall by the measured Brain context; keep whole sources/messages."""
from __future__ import annotations

from copy import deepcopy
from xml.sax.saxutils import escape

from utils.context.runtime_action_result_text import format_runtime_action_result
from utils.token_usage import get_runtime_token_estimate_scale
from utils.tokens import estimate_stream_input_tokens
from utils.tool_results import get_runtime_tool_results, TOOL_RESULT_KIND_FACT_CONTEXT


def recall_fact_context_budget(context) -> int:
    window = getattr(context, "runtime_current_context_window", {}) or {}
    capacity = int(window.get("context_window") or 0)
    used = int(window.get("used_tokens") or 0)
    # Keep half of the measured free space for generation/follow-up scaffolding.
    if capacity:
        return max(0, capacity - used) // 2

    # The restore bootstrap is a one-shot priming turn. Its first provider
    # response can expose the real context capacity only after runtime actions
    # have already fired, so an unknown preflight window must not block recall.
    if getattr(context, "runtime_session_restore_priming", False):
        return 1 << 60

    # Outside bootstrap, unknown capacity is not permission to inject archives.
    return 0


def result_tokens(context, result: dict) -> int:
    text = escape(format_runtime_action_result(result, runtime_action="RECALL_FACT_CONTEXT"))
    return estimate_stream_input_tokens(
        None, prompt_text='<TOOL_RESULT name="RECALL_FACT_CONTEXT">\n' + text + '\n</TOOL_RESULT>',
        scale=get_runtime_token_estimate_scale(context, "brain"),
    )


def fit_recall_fact_context(context, recalled: dict, budget: int) -> tuple[dict, int]:
    turn = str(getattr(context, "runtime_current_turn_id", "") or "")
    progress = getattr(context, "runtime_recall_fact_context_progress", {})
    if progress.get("turn_id") != turn:
        progress = {"turn_id": turn, "delivered": []}
        context.runtime_recall_fact_context_progress = progress
    delivered = set(progress.get("delivered", []))
    loaded, messages = {}, {}
    for entry in get_runtime_tool_results(context):
        if entry.get("kind") != TOOL_RESULT_KIND_FACT_CONTEXT:
            continue
        for source in (entry.get("result") or {}).get("sources", []):
            if "frame" in source or source.get("messages"):
                loaded[source["source_id"]] = entry.get("id", "")
            for message in source.get("messages", []):
                if "text" in message:
                    messages[message["message_id"]] = entry.get("id", "")

    result = {key: value for key, value in recalled.items() if key != "sources"}
    result.update(sources=[], deferred_sources=[], previously_delivered_sources=[])
    # Reserve the explicit deferred-ID list before accepting any evidence.
    result["deferred_sources"] = [s["source_id"] for s in recalled.get("sources", [])]
    for original in recalled.get("sources", []):
        source = deepcopy(original)
        identity = source["source_id"]
        if identity in loaded:
            source = {"source_id": identity, "tool_result_ref": loaded[identity]}
        elif identity in delivered:
            result["previously_delivered_sources"].append(identity)
            result["deferred_sources"].remove(identity)
            continue
        else:
            for message in source.get("messages", []):
                if message["message_id"] in messages:
                    message.pop("text", None)
                    message["tool_result_ref"] = messages[message["message_id"]]
        trial = deepcopy(result)
        trial["sources"].append(source)
        trial["deferred_sources"].remove(identity)
        if result_tokens(context, trial) > budget:
            continue
        result = trial
        if "frame" in source or source.get("messages"):
            delivered.add(identity)
            loaded[identity] = recalled["fact_id"]
            for message in source.get("messages", []):
                if "text" in message:
                    messages[message["message_id"]] = recalled["fact_id"]
    result["ok"] = any("frame" in s or s.get("messages") or "tool_result_ref" in s for s in result["sources"])
    if result["deferred_sources"]:
        result["partial"] = True
        result["reason"] = "context_budget_exceeded" if budget else "context_budget_unknown_or_full"
    if not result["ok"]:
        result["error"] = result.get("error") or result.get("reason") or "sources_already_delivered"
    # Full current value is atomic too. Explicitly report omission if even metadata cannot fit.
    if result_tokens(context, result) > budget and "value" in result:
        result.pop("value")
        result["value_status"] = "omitted_context_budget"
    progress["delivered"] = sorted(delivered)
    return result, result_tokens(context, result)
