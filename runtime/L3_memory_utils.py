import json

from runtime.L2_memory_rules import (
    MAX_SESSION_L2_LINES,
)
from runtime.L3_memory_rules import (
    MAX_SESSION_EVENT_TEXT_CHARS,
    MAX_SESSION_LATEST_MEMORY_TEXT_CHARS,
    MAX_SESSION_LINE_CHARS,
    MAX_SESSION_MEMORY_TEXT_CHARS,
    MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS,
    MAX_SESSION_PROMPT_DIFFS,
    MAX_SESSION_PROMPT_EVENTS,
    MAX_SESSION_PROMPT_SNAPSHOTS,
)

def build_runtime_session_event_snapshot(
        context,
        *,
        source: str = "runtime_action",
        initiated_by: str = "jin",
) -> dict:

    existing_snapshots = list(
        getattr(
            context,
            "runtime_session_event_snapshots",
            [],
        )
        or []
    )
    runtime_snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    diff_history = list(
        getattr(
            context,
            "runtime_l1_diff_history",
            [],
        )
        or []
    )
    user_message = getattr(
        context,
        "runtime_turn_user_message",
        "",
    )
    assistant_response = getattr(
        context,
        "runtime_turn_assistant_response",
        "",
    )

    return {
        "index": len(existing_snapshots),
        "memory_type": "session_event_snapshot",
        "source": source,
        "initiated_by": initiated_by,
        "turn_number": getattr(
            context,
            "turn_number",
            0,
        ),
        "user_message_count": getattr(
            context,
            "user_message_count",
            0,
        ),
        "assistant_message_count": getattr(
            context,
            "assistant_message_count",
            0,
        ),
        "runtime_snapshot_count": len(
            runtime_snapshots
        ),
        "diff_count": len(
            diff_history
        ),
        "user_message": user_message,
        "assistant_response": assistant_response,
    }


def compact_session_prompt_text(
        value,
        *,
        limit: int = MAX_SESSION_EVENT_TEXT_CHARS,
) -> str:

    text = str(
        value
        or ""
    ).strip()

    if len(text) <= limit:
        return text

    return (
        text[:limit].rstrip()
        + " ... <truncated>"
    )


def compact_l3_text_block(
        memory: str,
        *,
        max_chars: int,
        max_lines: int = 10,
) -> str:

    lines = [
        line.strip()
        for line in (
            memory
            or ""
        ).splitlines()
        if line.strip()
    ]

    if not lines:
        return "<empty>"

    if max_lines <= 0:
        return "<empty>"

    selected = lines[-max_lines:]
    omitted = max(0, len(lines) - len(selected))
    text = "\n".join(
        compact_session_prompt_text(
            line,
            limit=MAX_SESSION_LINE_CHARS,
        )
        for line in selected
    )

    if len(text) > max_chars:
        text = compact_session_prompt_text(
            text,
            limit=max_chars,
        )

    if omitted:
        text = (
            f"omitted_memory_lines: {omitted}\n"
            f"{text}"
        )

    return text.strip() or "<empty>"


def compact_l3_event(
        entry: dict,
) -> dict:

    if not isinstance(
        entry,
        dict,
    ):
        return {}

    keep_keys = (
        "index",
        "memory_type",
        "source",
        "initiated_by",
        "turn_number",
        "title",
        "memory",
        "user_message",
        "assistant_response",
    )

    return {
        key: (
            compact_session_prompt_text(
                value,
                limit=MAX_SESSION_EVENT_TEXT_CHARS,
            )
            if isinstance(value, str)
            else value
        )
        for key in keep_keys
        if (value := entry.get(key)) is not None
    }


def select_l3_snapshots(
        snapshots: list[dict],
        *,
        snapshot_count: int,
) -> tuple[list[dict], int]:

    valid_snapshots = [
        snapshot
        for snapshot in (
            snapshots
            or []
        )
        if isinstance(
            snapshot,
            dict,
        )
    ]

    if not valid_snapshots:
        return [], 0

    ranked = sorted(
        valid_snapshots,
        key=lambda snapshot: snapshot.get(
            "total_diff",
            0,
        )
        or 0,
        reverse=True,
    )

    selected = []
    seen_indexes = set()

    for snapshot in (
            [valid_snapshots[0], valid_snapshots[-1]]
            + ranked
    ):
        index = snapshot.get(
            "index",
            id(snapshot),
        )

        if index in seen_indexes:
            continue

        seen_indexes.add(
            index
        )
        selected.append(
            snapshot
        )

        if len(selected) >= snapshot_count:
            break

    selected.sort(
        key=lambda snapshot: snapshot.get(
            "index",
            0,
        )
        or 0
    )

    return (
        selected,
        max(
            0,
            len(valid_snapshots) - len(selected),
        ),
    )


def compact_l3_diff_entry(entry: dict) -> dict:

    changes = entry.get("changes", {}) if isinstance(entry, dict) else {}
    changes = changes if isinstance(changes, dict) else {}

    def keys(items, name):
        return [
            str(item.get(name, ""))
            for item in (items or [])[:8]
            if isinstance(item, dict) and item.get(name)
        ]

    return {
        "turn_number": entry.get("turn_number", 0),
        "snapshot_index": entry.get("snapshot_index", 0),
        "total_diff": entry.get("total_diff", 0),
        "added_keys": keys(changes.get("added", []), "key"),
        "changed_keys": keys(changes.get("changed", []), "current_key"),
        "removed_keys": keys(changes.get("removed", []), "key"),
    }


def build_l3_session_digest(
        *,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        runtime_l2_memory: str = "",
        session_event_snapshots: list[dict] | None = None,
        minimal: bool = False,
) -> dict:

    snapshot_count = (
        1
        if minimal
        else MAX_SESSION_PROMPT_SNAPSHOTS
    )
    diff_count = (
        1
        if minimal
        else MAX_SESSION_PROMPT_DIFFS
    )
    event_count = (
        1
        if minimal
        else MAX_SESSION_PROMPT_EVENTS
    )
    current_memory_chars = (
        1000
        if minimal
        else MAX_SESSION_MEMORY_TEXT_CHARS
    )

    selected_snapshots, omitted_snapshot_count = (
        select_l3_snapshots(
            runtime_memory_snapshots,
            snapshot_count=snapshot_count,
        )
    )

    latest_index = (
        selected_snapshots[-1].get(
            "index",
            0,
        )
        if selected_snapshots
        else None
    )

    compact_snapshots = []

    for snapshot in selected_snapshots:
        is_latest = snapshot.get("index", 0) == latest_index
        max_chars = (
            1000
            if minimal
            else (
                MAX_SESSION_LATEST_MEMORY_TEXT_CHARS
                if is_latest
                else MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS
            )
        )
        compact_snapshots.append({
            "index": snapshot.get("index", 0),
            "total_diff": snapshot.get("total_diff", 0),
            "role": "latest" if is_latest else "selected",
            "memory": compact_l3_text_block(
                snapshot.get("raw_memory", ""),
                max_chars=max_chars,
            ),
        })

    valid_events = [
        event
        for event in (session_event_snapshots or [])
        if isinstance(event, dict)
    ]
    compact_events = [
        compact_l3_event(event)
        for event in valid_events[-event_count:]
    ]

    selected_diffs = [
        entry
        for entry in (diff_history or [])
        if isinstance(entry, dict)
    ][-diff_count:]
    compact_diffs = [
        compact_l3_diff_entry(entry)
        for entry in selected_diffs
    ]

    omitted_event_count = max(0, len(valid_events) - len(compact_events))
    omitted_diff_count = max(
        0,
        len(diff_history or []) - len(selected_diffs),
    )

    return {
        "minimal": minimal,
        "current_session_memory": compact_l3_text_block(
            current_session_memory,
            max_chars=current_memory_chars,
            max_lines=8,
        ),
        "l2_context": compact_l3_text_block(
            runtime_l2_memory,
            max_chars=600,
            max_lines=0 if minimal else MAX_SESSION_L2_LINES,
        ),
        "session_events": compact_events,
        "omitted_events_count": omitted_event_count,
        "snapshots": compact_snapshots,
        "omitted_middle_snapshots": omitted_snapshot_count,
        "diff_history": compact_diffs,
        "omitted_older_diffs": omitted_diff_count,
    }

def build_runtime_session_memory_system_prompt() -> str:

    return (
        "You are JIN's L3 session memory summarizer.\n"
        "This is the layer above L1 runtime memory and L2 pattern memory.\n"
        "Return only the new compressed L3 session snapshot as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Write memory as atomic lines using the format:\n"
        "<key>: <value>\n"
        "Summarize the whole session from all L1 runtime memory snapshots, "
        "not only the latest snapshot.\n"
        "Session event snapshots are stored by the runtime as an array and are always available at session-context level.\n"
        "Treat that array as persistent event history for the session: use it to preserve causal sequence, important moments, and prior session-level decisions.\n"
        "Do not ask the user to fill snapshot fields manually; infer event snapshot meaning from natural conversation and explicit user markings.\n"
        "Preserve what should survive a browser reload or a new tab: active project direction, "
        "explicit decisions, durable facts, unresolved tasks, constraints, and next step.\n"
        "Treat TRUSTED_RUNTIME_CONTEXT timestamp as the source of truth for current time.\n"
        "L3 must convert relative temporal phrases from L1 snapshots into absolute or session-relative phrases before preserving them.\n"
        "Session handoff memory must not contain ambiguous standalone words like today, now, or recently unless paired with a timestamp/date.\n"
        "If a preference expires at end of day, encode that explicitly, such as temporary_preference: User requested X for 2026-06-05 only; expires after that date unless renewed.\n"
        "If the exact date cannot be inferred, write relative to current session rather than pretending it is durable calendar time.\n"
        "Session memory may include rare episodic_key_moment records for events that need richer sequence memory.\n"
        "Use episodic_key_moment only when the moment changed understanding of the project, user, or system; "
        "has a clear cause -> event -> outcome chain; was explicitly marked important by the user; "
        "or carries high emotional or narrative weight.\n"
        "Do not create episodic_key_moment entries for ordinary progress updates, routine feature work, "
        "minor bugs, casual jokes, or low-signal chat.\n"
        "When writing an episodic_key_moment, preserve the exact chain rather than only the conclusion.\n"
        "Use this plain-text block format:\n"
        "memory_type: episodic_key_moment\n"
        "title: <short event title>\n"
        "emotional_weight: low|medium|high\n"
        "why_it_matters: <why this should survive the session>\n"
        "sequence:\n"
        "1. <first causal step>\n"
        "2. <next causal step>\n"
        "preserve_detail: <which exact details matter and why>\n"
        "Use the diff history to identify which topics or constraints actually changed during the session.\n"
        "Do not copy every L1 line. Compress repeated or superseded states.\n"
        "Do not infer durable user personality traits, relationship claims, or preferences from weak signal.\n"
        "Preserve durable JIN/user fact lines from L1 snapshots as stable session facts; keep their keys stable and change only values that were explicitly corrected or superseded.\n"
        "Keep user-requested stored values with explicit purpose and explicit facts in their own retrieval-friendly lines.\n"
        "Drop transient last_jin_response details unless they contain an unresolved question or next step.\n"
        "The final L3 snapshot should feel like a session handoff note for fluent continuation."
    )


def build_runtime_session_memory_user_prompt(
        *,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        runtime_l2_memory: str = "",
        session_event_snapshots: list[dict] | None = None,
        minimal: bool = False,
) -> str:

    digest = build_l3_session_digest(
        current_session_memory=current_session_memory,
        runtime_memory_snapshots=runtime_memory_snapshots,
        diff_history=diff_history,
        runtime_l2_memory=runtime_l2_memory,
        session_event_snapshots=session_event_snapshots,
        minimal=minimal,
    )

    snapshot_blocks = []

    for snapshot in digest["snapshots"]:
        snapshot_blocks.append(
            "\n".join([
                f"snapshot: {snapshot.get('index', 0)}",
                f"role: {snapshot.get('role', '')}",
                f"total_diff: {snapshot.get('total_diff', 0)}",
                "memory:",
                snapshot.get(
                    "memory",
                    "<empty>",
                ),
                "patch_summary:",
                json.dumps(
                    snapshot.get(
                        "patch_summary",
                        {},
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            ])
        )

    return "\n\n".join([
        f"L3 compact digest minimal: {digest['minimal']}",
        "Current L3 session memory:",
        digest["current_session_memory"],
        "Compact L2 pattern context:",
        digest["l2_context"],
        "Session event snapshots array:",
        f"omitted_events_count: {digest['omitted_events_count']}",
        json.dumps(
            digest["session_events"],
            ensure_ascii=False,
            indent=2,
        ),
        "Selected L1 runtime memory snapshot history:",
        (
            f"omitted_middle_snapshots: {digest['omitted_middle_snapshots']}"
            if digest["omitted_middle_snapshots"]
            else "omitted_middle_snapshots: 0"
        ),
        "\n\n---\n\n".join(snapshot_blocks) or "<empty>",
        "Recent L1 diff history:",
        (
            f"omitted_older_diffs: {digest['omitted_older_diffs']}"
            if digest["omitted_older_diffs"]
            else "omitted_older_diffs: 0"
        ),
        json.dumps(
            digest["diff_history"],
            ensure_ascii=False,
            indent=2,
        ),
        "Rewrite the L3 session memory now.",
    ])
