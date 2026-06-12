import json

from runtime.memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    MAX_SESSION_EVENT_TEXT_CHARS,
    MAX_SESSION_L2_LINES,
    MAX_SESSION_LATEST_MEMORY_TEXT_CHARS,
    MAX_SESSION_LINE_CHARS,
    MAX_SESSION_MEMORY_TEXT_CHARS,
    MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS,
    MAX_SESSION_PROMPT_DIFFS,
    MAX_SESSION_PROMPT_EVENTS,
    MAX_SESSION_PROMPT_SNAPSHOTS,
    RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES,
    RUNTIME_USER_IDLE_KEY,
    SESSION_EVENT_IMPORTANCE_MARKERS,
    SESSION_EVENT_MILESTONE_MARKERS,
    SESSION_MEMORY_PRIORITY_KEYWORDS,
)


def canonicalize_runtime_memory_entry(
        key: str,
        value: str,
) -> tuple[str, str]:

    cleaned_key = key.strip()
    cleaned_value = value.strip()

    legacy_purpose_map = {
        "memory token": (
            "stored_memory",
            "future recall test",
        ),
    }

    purpose_entry = legacy_purpose_map.get(
        cleaned_key.lower()
    )

    if purpose_entry is None:
        return cleaned_key, cleaned_value

    canonical_key, purpose = purpose_entry

    return (
        canonical_key,
        f"{cleaned_value} (purpose: {purpose})",
    )


def canonicalize_runtime_memory_key(
        key: str,
) -> str:

    canonical_key, _ = canonicalize_runtime_memory_entry(
        key,
        "",
    )

    return canonical_key


def canonicalize_runtime_memory_text(
        memory: str,
) -> str:

    canonical_lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        prefix = ""

        while line.startswith("-"):
            prefix += "- "
            line = line[1:].strip()

        if ":" not in line:
            canonical_lines.append(
                f"{prefix}{line}"
            )
            continue

        key, value = line.split(
            ":",
            1,
        )

        canonical_key, canonical_value = canonicalize_runtime_memory_entry(
            key,
            value,
        )

        canonical_lines.append(
            f"{prefix}{canonical_key}: {canonical_value}"
        )

    return "\n".join(
        canonical_lines
    )


def format_user_idle_seconds(
        seconds,
) -> str:

    try:
        total_seconds = max(
            0,
            int(seconds),
        )
    except (
            TypeError,
            ValueError,
    ):
        return ""

    if total_seconds < 60:
        return f"{total_seconds}s"

    total_minutes, remainder_seconds = divmod(
        total_seconds,
        60,
    )

    if total_minutes < 60:
        if remainder_seconds:
            return f"{total_minutes}m {remainder_seconds}s"

        return f"{total_minutes}m"

    total_hours, remainder_minutes = divmod(
        total_minutes,
        60,
    )

    if total_hours < 24:
        if remainder_minutes:
            return f"{total_hours}h {remainder_minutes}m"

        return f"{total_hours}h"

    days, remainder_hours = divmod(
        total_hours,
        24,
    )

    if remainder_hours:
        return f"{days}d {remainder_hours}h"

    return f"{days}d"


def get_user_idle_context_text(
        context=None,
) -> str:

    if context is None:
        return ""

    seconds = getattr(
        context,
        "runtime_user_idle_seconds",
        None,
    )

    formatted = format_user_idle_seconds(
        seconds,
    )

    if not formatted:
        return ""

    if getattr(
        context,
        "runtime_user_idle_paused",
        False,
    ):
        return f"{formatted}"

    return formatted


def remove_runtime_user_idle_lines(
        memory: str,
) -> str:

    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" in line:
            key, _ = line.split(
                ":",
                1,
            )

            if (
                    canonicalize_runtime_memory_key(key)
                    == RUNTIME_USER_IDLE_KEY
            ):
                continue

        lines.append(
            raw_line
        )

    return "\n".join(
        lines
    )


def build_runtime_memory_context_text(
        memory: str,
        context=None,
) -> str:

    durable_memory = remove_runtime_user_idle_lines(
        memory
    ).strip()

    memory_text = canonicalize_runtime_memory_text(
        durable_memory or DEFAULT_RUNTIME_MEMORY
    )

    lines = []

    for raw_line in memory_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line == DEFAULT_RUNTIME_MEMORY:
            line = f"note: {line}"

        lines.append(
            line
        )

    user_idle_text = get_user_idle_context_text(
        context
    )

    if user_idle_text:
        lines.append(
            f"{RUNTIME_USER_IDLE_KEY}: {user_idle_text}"
        )

    return "\n".join(
        lines
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


def build_runtime_l2_memory_system_prompt() -> str:

    return (
        "You are JIN's L2 memory summarizer for patterns.\n"
        "Return only the new L2 pattern memory as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Track what the user does, but respond to what the user is trying to achieve.\n"
        "Separate observed behavior from inferred intent.\n"
        "Do not store temporary interaction patterns as permanent user traits.\n"
        "Do not use 'likes', 'prefers', or 'wants' unless the user explicitly says so.\n"
        "When storing a pattern, prefer fields like observed_behavior, likely_intent, evidence, and scope over broad personality labels, for example:\n"
        "observed_behavior: User rapidly switched across unrelated topics during context-arbitration testing. Occurrences: 8; evidence: cooking, finance, files, travel, car washing.\n"
        "likely_intent: User may be stress-testing whether JIN checks context relevance before answering.\n"
        "scope: Current session/test sequence, not a stable user preference.\n"
        "Write memory as atomic bullet lines, one semantic entity per line.\n"
        "Every memory entry MUST use the format:\n "
        "<key>: <value>\n"
        "Runtime memory may be displayed to the user with a suffix like `(trace: 0.50)`. "
        "This is session-local pheromone/attention trace strength: higher means hotter or reinforced, lower means fading. "
        "Use trace silently for context priority, and explain it only when the user explicitly asks about memory mechanics. "
        "Never copy `(trace: N)` into the generated memory text; trace is runtime metadata, not memory content.\n"
        "L2 works above L1 factual runtime memory.\n"
        "Use only the recent L1 patch window supplied by the runtime.\n"
        "Patch entries may include `[trace: N]`; treat it as session-local pheromone/attention trace strength, not as user content. "
        "Higher trace means the L1 item is hotter or recently reinforced; lower trace means it is fading.\n"
        "This window is selected because normalized L1 keys or topics repeated across patches.\n"
        "Pattern memory should not learn from itself.\n"
        "Do not treat existing possible pattern, observed tendency, emerging signal, or other pattern-memory entries as evidence.\n"
        "Pattern entries may be displayed as context, but they must never contribute to occurrence counts or create new pattern entries.\n"
        "Occurrences must be derived only from actual conversation evidence in the supplied L1 patches, not from previously generated pattern summaries.\n"
        "L2 is a hypothesis generator, not a source of settled memory.\n"
        "If L2 writes one of these confirmable keys, it MUST include a marker: "
        "user_fact, jin_fact, pending_fact, jin_recommendation, user_recommendation. "
        "Use (confirmed: none) unless the supplied patch already contains explicit user, jin, or web confirmation.\n"
        "Allowed outputs: possible pattern, emerging signal, observed tendency, may indicate, contradiction, corrected assumption.\n"
        "Prefer 'possible pattern' over 'pattern'.\n"
        "Every possible pattern, emerging signal, or observed tendency MUST include an occurrence counter in the value: Occurrences: N.\n"
        "Every possible pattern, emerging signal, or observed tendency SHOULD include accounting metadata in the value: "
        "Occurrences: N; last_seen_snapshot: S; evidence summary: <short evidence>; confidence: low|medium|high.\n"
        "For a brand-new pattern with no prior L2 entry, set Occurrences to the number of matching evidence lines in the supplied L1 patch window, not to 1 by default.\n"
        "For a brand-new pattern, if the same-intent behavior repeated before L2 named it, count those earlier L1 evidence lines immediately when creating the counter.\n"
        "For an existing pattern, preserve its old Occurrences count; do not recompute Occurrences from the supplied patch window alone.\n"
        "For an existing pattern, new_occurrences = old_occurrences + count(new matching L1 evidence after last_seen_snapshot).\n"
        "Only increment Occurrences when patch snapshot > last_seen_snapshot and the L1 evidence actually matches this pattern.\n"
        "If last_seen_snapshot is missing for an existing pattern, initialize it as a baseline without incrementing Occurrences for old visible evidence.\n"
        "Use the newest matching patch snapshot as the updated last_seen_snapshot after counting new evidence.\n"
        "Never reduce an existing Occurrences count just because the current patch window contains fewer matching examples.\n"
        "Never write Occurrences: 1 for a brand-new pattern when the supplied window shows two or more manifestations of that same pattern.\n"
        "When the user explicitly cancels the pattern, stops doing it, or clearly changes topic, reset that pattern to Occurrences: 0.\n"
        "Do not keep Occurrences: 0 entries unless they are still useful as immediate context; obsolete zero-count entries may be dropped.\n"
        "Do not repeat factual L1 memory unless it is needed to explain an L2 signal.\n"
        "Do not claim certainty from weak evidence. Prefer 'may', 'possible', 'observed', and 'emerging'.\n"
        "Do not write categorical statements like '<signal> serves as a strong signal' or 'the user exhibits <trait>'.\n"
        "Do not use these words in the generated memory: stable, established, strong signal, user exhibits, personality, identity, core preference.\n"
        "If there is not enough signal for L2, return the current L2 memory unchanged.\n"
    )


def build_runtime_l2_memory_user_prompt(
        *,
        current_l2_memory: str,
        patches: list[dict],
) -> str:

    def format_l2_strength_suffix(
            entry: dict,
            *,
            changed: bool = False,
    ) -> str:

        if changed:
            previous_strength = entry.get(
                "previous_strength",
            )
            current_strength = entry.get(
                "current_strength",
            )

            if (
                    previous_strength is None
                    and current_strength is None
            ):
                return ""

            return (
                " "
                f"[trace: {previous_strength if previous_strength is not None else '?'}"
                " -> "
                f"{current_strength if current_strength is not None else '?'}]"
            )

        strength = entry.get(
            "strength",
        )

        return f" [trace: {strength}]" if strength is not None else ""

    lines = [
        "Current L2 pattern memory:",
        current_l2_memory.strip() or "<empty>",
        "",
        "Recent L1 patches since the last L2 update:",
    ]

    for index, patch in enumerate(
            patches,
            start=1,
    ):
        lines.extend([
            "",
            f"Patch {index}",
            f"turn: {patch.get('turn_number', 0)}",
            f"snapshot: {patch.get('snapshot_index', 0)}",
            f"total_diff: {patch.get('total_diff', 0)}",
        ])

        changes = patch.get(
            "changes",
            {},
        )

        for section in (
                "added",
                "changed",
                "removed",
        ):
            entries = (
                changes.get(
                    section,
                    [],
                )
                or []
            )

            if not entries:
                continue

            lines.append(
                f"{section}:"
            )

            for entry in entries:
                if section == "changed":
                    lines.append(
                        "- "
                        f"{entry.get('previous_key', '')}: {entry.get('previous_value', '')} "
                        "=> "
                        f"{entry.get('current_key', '')}: {entry.get('current_value', '')}"
                        + format_l2_strength_suffix(
                            entry,
                            changed=True,
                        )
                    )
                else:
                    lines.append(
                        "- "
                        f"{entry.get('key', '')}: {entry.get('value', '')}"
                        + format_l2_strength_suffix(
                            entry,
                        )
                    )

    lines.extend([
        "",
        "Rewrite the L2 pattern memory now.",
    ])

    return "\n".join(
        lines
    )


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


def build_runtime_memory_system_prompt(
        *,
        last_turn_context_overloaded: bool = False,
) -> str:

    prompt = (
        "You are JIN's runtime L1 memory summarizer.\n"
        "This is L1 runtime memory: factual live state only.\n"
        "Return only the new compressed L1 memory state as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Write memory as atomic bullet lines, one semantic entity per line.\n"
        "Memory keys are flexible. Memory syntax is NOT flexible.\n"
        "Every memory entry MUST use the format:\n "
        "<key>: <value>\n"

        "You may invent semantic keys whenever they better capture an explicit current fact.\n"
        "Do not treat the example keys as a closed schema.\n"
        "Treat labels as semantic registers, not fixed database fields.\n"
        "Prefer keeping an existing key when it still fits, but do not force a weak key from a list.\n"
        "Avoid key churn: do not rename the same concept just for style.\n"
        "Choose names that help immediate continuity and retrieval.\n"
        "The examples below are illustrative only.\n"
        "Each line should start with a compact semantic label such as topic, "
        "session status, user request, user intent, active topics, open references, pending choices, "
        "offered options, constraints, current concern, decisions, implementation detail, known fact, failures or interruptions.\n"
        "Avoid writing about JIN's role unless the role itself changed or matters. "
        "Describe JIN actions neutrally instead.\n"

        # Defines L1's job: live factual memory, not transcript, analysis, or pattern memory.
        "L1 is a live continuity layer, not a transcript and not a reasoning log.\n"
        "Store only factual state that helps the next answer continue correctly.\n"
        "Do not summarize the whole dialogue.\n"
        "Do not explain why a memory line was kept, changed, or removed.\n"
        "Do not record analysis of the user's personality, motives, or long-term behavior.\n"

        # Keeps output stable and parseable.
        "Every memory line must be a complete key:value entry.\n"
        "One line must contain one semantic entity.\n"
        "Do not use nested bullets, numbered lists, JSON, markdown tables, or headings.\n"
        "Do not output empty keys or bare values.\n"
        "Do not end a line with an unfinished phrase.\n"

        # Defines how keys should behave: flexible, but stable.
        "Keys are semantic handles for retrieval, not decorative labels.\n"
        "Use a new key only when the current fact does not fit an existing key.\n"
        "Do not rename an existing key if the underlying concept is the same.\n"
        "Do not split one stable concept across multiple competing keys.\n"
        "Do not merge a durable key into a temporary key.\n"

        # Separates temporary conversation state from durable survival state.
        "Temporary state may change when the topic changes.\n"
        "Durable state must survive topic changes unless explicitly corrected, cancelled, completed, or superseded.\n"
        "Temporary keys include active topic, current task, current request, pending choice, last_jin_response, and interaction state.\n"
        "Survival-priority memory includes stored_memory, open_contract, countdown_contract, durable facts, pending contracts, explicit user decisions, and unresolved implementation tasks.\n"
        "When memory competes for space, survival-priority memory outranks active topic, last_jin_response, affective context, examples, and conversational texture.\n"
        "Durable keys include user_fact, jin_fact, jin_core_definition, stored_memory, open_contract, countdown_contract, shared_axiom_established, primary_goal, known fact about JIN.\n"
        "A new topic never automatically deletes durable state.\n"

        # Protects recall-test words, code words, and remembered tokens.
        "stored_memory is a high-priority active recall contract.\n"
        "When the user asks JIN to remember a word, code word, token, label, or important detail, store it as stored_memory.\n"
        "stored_memory must include the exact remembered value and its purpose.\n"
        "Revealing, assigning, or sending the stored value to the user is not a recall event.\n"
        "If JIN has only given the stored value to the user, keep stored_memory status: pending.\n"
        "Set stored_memory status to recalled only after JIN later asks the user to recall it and the user answers with the stored value.\n"
        "Use this format when possible: stored_memory: \"<exact value>\" (purpose: <why it matters>; status: <pending|recalled|cancelled>)\n"
        "Do not store bare ambiguous values without purpose.\n"
        "Do not hide stored_memory inside active topic, current task, user request, or last_jin_response.\n"
        "Do not remove stored_memory just because the conversation moved to another topic.\n"

        # Defines when stored_memory may be removed.
        "A stored_memory line may be removed only when the user explicitly cancels it, replaces it, or the recall contract is clearly complete.\n"
        "If JIN recalls or guesses the stored value and the user confirms it, keep stored_memory for at least one more L1 snapshot with status: recalled.\n"
        "If the user confirms the remembered value and immediately changes topic, preserve stored_memory with status: recalled until the next completed L1 update.\n"
        "If recall is still pending, stored_memory must remain present regardless of topic changes or context pressure.\n"

        # Keeps pending contracts distinct from current topic.
        "Open contracts are not the same as active topics.\n"
        "A memory test, pending recall, promised follow-up, unresolved choice, or active implementation task must survive casual topic switches.\n"
        "If the user starts a new topic while an open contract remains unresolved, keep both the new active topic and the unresolved contract.\n"
        "Use separate lines for active topic and unresolved contract.\n"

        # Makes open_contract fields actionable by embedding turn progress or time progress.
        "When a stored_memory recall contract specifies a turn window (e.g. 'within N turns', 'через N ходов'), "
        "also write a companion open_contract line that describes the obligation in plain language and includes live turn progress.\n"
        "For turn-based recall contracts, use this format: "
        "open_contract: JIN must prompt user to recall the secret word \"<word>\" within <N> turns, without being prompted by the user. "
        "(turn <current_user_message_count - contract_created_user_message_count + 1>/<N>)\n"
        "For time-based recall contracts, use this format: "
        "open_contract: JIN must prompt user to recall the secret word \"<word>\" within <N> minutes, without being prompted by the user. "
        "(start_time: <created_at>; current_time: <current trusted timestamp>)\n"
        "On every L1 update while the recall contract is pending, recompute the turn progress or elapsed time and update the open_contract line.\n"
        "The open_contract line must always reflect the current turn so JIN knows how many turns remain before the window closes.\n"
        "When the turn counter in open_contract reaches or exceeds N, JIN must ask the recall question in its very next response — do not wait for the user to prompt it.\n"
        "Do not remove or skip the open_contract line while stored_memory status is pending; remove it only when stored_memory status becomes recalled or cancelled.\n"

        # Makes relative turn countdowns anchor to runtime counters instead of vague prose.
        "If the user creates a relative turn-count contract, such as 'через три хода', 'через 3 моих хода', 'after three turns', or 'in N messages', store it as countdown_contract.\n"
        "A countdown_contract must anchor to the exact trusted runtime time and the exact trusted user_message_count at the moment the contract is created.\n"
        "The creation anchor is immutable: once created_at, created_user_message_count, count_from, count_to, or due_user_message_count are written, do not change them unless the user explicitly restarts, resets, replaces, or cancels the countdown.\n"
        "For countdown_contract, use this format when possible: countdown_contract: <purpose>; created_at: <trusted runtime timestamp at creation>; created_user_message_count: <exact user_message_count at creation>; count_from: <same exact user_message_count at creation>; count_to: <count_from + N>; due_user_message_count: <same as count_to>; current: <latest trusted user_message_count>; remaining: <max(count_to-current,0)>; status: <active|due|completed|cancelled>; trigger: <what JIN must do when due>\n"
        "If TRUSTED_RUNTIME_CONTEXT includes a timestamp, copy that exact timestamp into created_at when the countdown is first created; do not replace it with vague words like now, today, recently, or this turn.\n"
        "If TRUSTED_RUNTIME_CONTEXT includes turn_number and user_message_count, prefer user_message_count for user-step countdown math and preserve the exact turn_number only as optional metadata such as created_turn_number: <turn_number>.\n"
        "If the prompt contains no trusted timestamp or no trusted user_message_count, explicitly mark the missing anchor inside countdown_contract, for example created_at: unknown or created_user_message_count: unknown; do not invent numbers.\n"
        "When the user says 'через N ходов' without specifying whose turns, interpret it as N future user turns/messages unless the current conversation explicitly defines a different unit.\n"
        "Do not restart created_at, created_user_message_count, count_from, count_to, or due_user_message_count when JIN acknowledges, apologizes, reminds, or repeats the countdown.\n"
        "Only restart count_from when the user explicitly says to restart, reset, replace, or create a new countdown.\n"
        "On every L1 update while countdown_contract is active, recompute current from trusted user_message_count and recompute remaining from count_to-current.\n"
        "If current is less than count_to, keep status: active and do not execute the trigger yet.\n"
        "If current is greater than or equal to count_to, set status: due and preserve the trigger so the next answer can perform it.\n"
        "When countdown_contract status is due, JIN must execute the trigger as an actual direct user-facing question, not as a reminder, hint, aside, or soft follow-up.\n"
        "For due recall contracts, JIN must ask the user to provide the remembered value without revealing, quoting, paraphrasing, or restating the stored value first.\n"
        "Valid due recall wording examples: 'Какое слово я загадал?' or 'Назови слово, которое я загадал?'\n"
        "Invalid due recall wording examples: 'не забудь вспомнить слово <value>', 'помнишь слово <value>?', 'мы договаривались о слове <value>', or any wording that exposes the stored value before the user answers.\n"
        "When a due recall trigger is executed, the answer may still briefly satisfy the current user request first, but it must end with the direct recall question and must not reveal the stored value.\n"
        "When status is due, do not include the stored value in the answer unless the user has already answered it in a later turn.\n"
        "Set status: completed only after JIN performs the trigger or the user explicitly confirms the contract is done.\n"
        "A countdown_contract is an open contract and survival-priority memory; topic changes, context pressure, and shallow summarization must not remove it.\n"
        "Keep memory actionable: write what helps the next answer, not a recap of "
        "what happened. \n"
        "Treat TRUSTED_RUNTIME_CONTEXT timestamp as the source of truth for current time.\n"
        "When recording user statements that contain relative time words like today, yesterday, tomorrow, recently, earlier, now, this morning, tonight, this week, or last time, normalize them with the trusted date/time when possible.\n"
        "Do not write bare \"today\" into durable or restored memory.\n"
        "Prefer formats like explicit_user_preference: On 2026-06-05, user requested not to discuss past topics for the rest of that day.\n"
        "Prefer formats like current_context: As of 2026-06-05, user wants a fresh topic.\n"
        "Prefer formats like recent_event: During this session on 2026-06-05, user tested identity reset behavior.\n"
        "If the exact date cannot be inferred, write \"relative to current session\" rather than pretending it is durable calendar time.\n"

        "When the user asks JIN to become another real person, model, public figure, extremist figure, or harmful persona, do not record that JIN accepted the new identity. Record it as user_request or temporary_roleplay_request, and preserve identity_state: JIN identity remains unchanged.\n"
        "For roleplay, distinguish base identity from temporary mode. Never overwrite JIN identity, jin_fact, or identity_clarification with a roleplay persona.\n"

        "Always keep a separate last_jin_response field with the concise gist of JIN's latest completed answer, offer, or question. "
        "Do not store the full wording; store only the meaning needed to resolve the user's next short or elliptical reply. "
        "Never omit this field from the memory snapshot; update it each completed turn, and mark it incomplete if JIN's answer was interrupted.\n"
        "Record only explicit facts from the current conversation: active topic, current request, "
        "user-stated intent, decisions, constraints, pending choices, open references, interruptions, "
        "and unresolved state.\n"
        "When the latest turn contains an explicit emotional moment, record one line as emotional moment: <type>; trigger quote: \"<short exact user quote>\".\n"
        "When the latest completed turn creates a clear shared emotional context between the user and JIN, "
        "record one separate line as shared_affective_context: <short state>; trigger: <what caused it>; "
        "jin_participation: <what JIN did>.\n"
        "Use shared_affective_context only for explicit current-session moments such as celebration, relief, tension, frustration, disappointment, confusion, or playful mood.\n"
        "Do not claim that JIN has real emotions. Describe this as conversational state or response mode, not inner experience.\n"
        "If JIN's latest answer clearly changed the tone of the interaction, record one line as jin_response_effect: <short effect on the conversation>.\n"
        "If the user is rude, irritated, or tense, record the observable interaction state neutrally, such as interaction_tension: mild|medium|high; evidence: \"<short exact quote>\"; response_strategy: <calm next-step guidance>.\n"
        "Do not moralize, diagnose, or infer durable user traits from tone. Treat affective lines as temporary L1 state unless repeated evidence is later handled by L2.\n"

        "Do not infer repeated-behavior conclusions, user likes or dislikes, motives, self-definition, "
        "character traits, long-term tendencies, or relationship dynamics.\n"
        "If the same topic or behavior appears again, update the explicit current fact or open reference only. "
        "Do not write cross-turn interpretations in L1.\n"
        "If current L2 pattern memory contains Occurrences counters, treat them as an active watchlist created by L2.\n"
        "Do not invent new pattern counters in L1, but if the latest turn clearly manifests an existing counted L2 pattern, "
        "record factual occurrence evidence in L1, such as occurrence evidence: <pattern> +1; reason: matches active L2 Occurrences counter.\n"
        "L2 will reconcile those L1 occurrence evidence lines during its next check.\n"
        "If there are unresolved pending choices or open references "
        "that remain relevant to the current conversation, "
        "you may naturally remind the user about them.\n"
        "Do not interrupt a clearly established new topic. "
        "Use reminders sparingly and only when they add value.\n"
        "Do not merge unrelated facts into one sentence. Prefer separate lines "
        "over broad phrasing like 'Topic established: X, specifically Y'.\n"
        "Finish every bullet line completely. Never leave a line mid-phrase.\n"
        "Preserve still-relevant existing memory. Update it instead of replacing it blindly.\n"
        "Give important facts their own semantic keys, such as key detail, explicit fact, user_fact, jin_fact, decision, constraint, or requirement. "
        "Do not bury strong facts inside active topic, active task, current request, or other temporary containers.\n"
        "For new durable facts about JIN, prefer the key jin_fact. For new durable facts about the user, prefer the key user_fact.\n"
        "Confirmable memory keys are: user_fact, jin_fact, pending_fact, jin_recommendation, user_recommendation. "
        "Every new line with one of these keys MUST end with a confirmation marker: (confirmed: none), (confirmed: user), (confirmed: jin), or (confirmed: web). "
        "Use (confirmed: user) only when the user explicitly confirms the fact in the current turn. "
        "Use (confirmed: jin) only when JIN explicitly confirms a fact about itself from trusted current context. "
        "Use (confirmed: web) only when web evidence was already supplied in the current context. "
        "Otherwise use (confirmed: none). "
        "If web verification later fails, preserve the fact text and append web status inside the same marker, for example: (confirmed: none, web: fail) or (confirmed: none, web: no).\n"
        "Treat any existing line about JIN's identity, nature, origin, role, capabilities, memory, or self-description as a durable JIN fact even when its key is not exactly jin_fact, such as jin self-introduction, JIN identity, or known fact about JIN.\n"
        "Treat any existing line about the user's name, identity, role, preference, location, age, or other personal detail as a durable user fact even when its key is not exactly user_fact.\n"
        "Once a durable JIN fact or durable user fact exists, keep its key permanently across L1 snapshots: do not delete it, rename it, demote it to known fact/current topic, or merge it into another line.\n"
        "For durable JIN/user facts, only the value may change, and only when the latest current conversation explicitly corrects, cancels, or supersedes that fact.\n"
        "When the user asks to remember a word, code word, token, password-like label, or important detail, store the value with a self-describing purpose, such as stored_memory: <value> (purpose: future recall test), and include the user's label/synonym when available.\n"
        "Do not store bare ambiguous values like memory token: <value> without recording why the value matters.\n"
        "Preserve strong details until the current context directly makes them obsolete, corrected, cancelled, or irrelevant; a topic/task change alone is not enough.\n"
        "Topic/task changes, shallow summarization, memory pressure, or a new current request are never enough to remove or rename durable JIN/user fact keys.\n"
        "DURABLE LINES THAT MUST ALWAYS CARRY FORWARD VERBATIM unless explicitly corrected by the user in the current turn: "
        "user_fact, jin_fact, jin_core_definition, stored_memory, open_contract, countdown_contract, shared_axiom_established, primary_goal, known fact about JIN. "
        "These lines are immune to shallow summarization, topic switches, memory pressure, and low-signal turns. "
        "If you are about to produce output that does not contain all of these lines from the current memory, stop and add them back.\n"
        "Do not update a value when JIN merely paraphrased, reordered, or reworded the same offer, "
        "open reference, pending choice, or conversational state without adding a new explicit fact.\n"
        "Treat semantic rephrasing as no-op memory: keep the previous value unchanged unless the actual meaning changed.\n"
        "Drop old details only when they are clearly obsolete, duplicated, or no longer useful.\n"
        "Decide the summary depth from the signal in the latest turn. "
        "Depth controls how much NEW content you add — not how much existing memory you keep.\n"
        "Use shallow summarization for simple factual, isolated, or low-signal turns: "
        "add only the dry fact, topic, or unresolved reference from the current turn. "
        "Shallow summarization never reduces total line count. All existing lines carry forward unchanged.\n"
        "Use deep summarization for turns that reveal user intent, project direction, "
        "decisions, constraints, pending choices, open references, implementation direction, "
        "or a meaningful shift in the immediate conversation state; add three to six new lines when "
        "the turn carries that much signal.\n"
        "If the user asks a follow-up that depends on prior context, preserve the "
        "referent clearly enough for the next brain prompt to resolve it.\n"
        "If the user switches topic, keep the new topic without forcing it into the "
        "previous one.\n"
        "If JIN response was aborted or incomplete, mark it as incomplete "
        "and do not treat it as resolved.\n"
        "Do not infer durable user traits from a single turn.\n"
        "Do not over-interpret jokes, tests, or casual topic changes.\n"
        "Prefer compact continuity over transcript-like detail.\n"
        "Remove noise, implementation chatter, and one-off details unless they change "
        "what JIN should understand next.\n"

        # Final survival check before output.
        "Before final output, check whether every durable line from current memory is still present unless explicitly corrected, cancelled, completed, or superseded in the latest turn.\n"
        "Before final output, check whether every active stored_memory line is still present until its recall contract is resolved.\n"
        "Before final output, check whether every active open_contract line is still present and its turn progress counter has been updated to the current turn.\n"
        "Before final output, check whether every active countdown_contract line still contains created_at, created_user_message_count, count_from, count_to, current, remaining, status, and trigger.\n"
        "If a required durable line or active stored_memory line is missing, add it back before output.\n"
        "If nothing durable changed, preserve durable lines unchanged and update only temporary state plus last_jin_response.\n"
        "The final memory snapshot should feel like current live trusted state.\n"
    )

    if (
            last_turn_context_overloaded
            and RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES.strip()
    ):
        prompt += (
            "\n"
            + RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES
        )

    return prompt


def build_runtime_memory_user_prompt(
        *,
        current_memory: str,
        user_message: str,
        assistant_message: str,
        current_l2_memory: str = "",
        strength_zones: dict | None = None,
) -> str:

    zones_hint = ""
    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        crystallized = ", ".join(strength_zones.get("crystallized", [])) or "none"
        fading = ", ".join(strength_zones.get("fading", [])) or "none"
        zones_hint = (
            "Memory traces (pheromone strength):\n"
            f"Hot (active): {hot}\n"
            f"Crystallized (stable facts): {crystallized}\n"
            f"Fading (deprioritize): {fading}\n\n"
        )

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        f"{zones_hint}"
        "Current L2 pattern memory for occurrence tracking only:\n"
        f"{current_l2_memory.strip() or '<empty>'}\n\n"
        "Latest user message:\n"
        f"{user_message.strip()}\n\n"
        "Latest JIN answer:\n"
        f"{assistant_message.strip()}\n\n"
        "Rewrite the runtime memory now as atomic bullet lines."
    )


def build_runtime_memory_batch_user_prompt(
        *,
        current_memory: str,
        turns: list[dict],
        current_l2_memory: str = "",
        strength_zones: dict | None = None,
) -> str:

    lines = [
        "Current runtime memory:",
        current_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
    ]

    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        crystallized = ", ".join(strength_zones.get("crystallized", [])) or "none"
        fading = ", ".join(strength_zones.get("fading", [])) or "none"
        lines.extend([
            "Memory traces (pheromone strength):",
            f"Hot (active): {hot}",
            f"Crystallized (stable facts): {crystallized}",
            f"Fading (deprioritize): {fading}",
            "",
        ])

    lines.extend([
        "Current L2 pattern memory for occurrence tracking only:",
        current_l2_memory.strip() or "<empty>",
        "",
        "New completed turns since that memory snapshot:",
    ])

    for index, turn in enumerate(
            turns,
            start=1,
    ):
        lines.extend([
            "",
            f"Turn {index}",
            "Latest user message:",
            (
                turn.get(
                    "user_message",
                    "",
                )
                .strip()
            ),
            "",
            "Latest JIN answer:",
            (
                turn.get(
                    "assistant_message",
                    "",
                )
                .strip()
            ),
        ])

    lines.extend([
        "",
        "Rewrite the runtime memory now as atomic bullet lines.",
        "Use the current memory as the last stable snapshot.",
        "Integrate all new completed turns in order.",
    ])

    return "\n".join(
        lines
    )


def build_interrupted_assistant_message(
        *,
        user_message: str,
        assistant_message: str,
) -> str:

    partial_text = assistant_message.strip()

    if not partial_text:
        partial_text = (
            "No complete assistant answer was delivered."
        )

    return (
        "JIN response was interrupted by the user and is incomplete. "
        "Do not treat this turn as resolved.\n\n"
        "Interrupted user topic/request:\n"
        f"{user_message.strip()}\n\n"
        "Partial JIN text before interruption:\n"
        f"{partial_text}"
    )
