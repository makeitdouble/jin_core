import json


MAX_SESSION_PROMPT_SNAPSHOTS = 12
MAX_SESSION_PROMPT_DIFFS = 24
MAX_SESSION_EVENT_TEXT_CHARS = 800


DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
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


def detect_session_event_initiator(
        user_message: str,
) -> str:

    normalized = (
        user_message
        or ""
    ).casefold()

    user_markers = (
        "хочу это запомнить",
        "хочу запомнить",
        "сохрани это",
        "сохранить это",
        "это надо сохранить",
        "это надо запомнить",
        "запомни это",
        "важный момент",
        "надо сохранить",
    )

    if any(
        marker in normalized
        for marker in user_markers
    ):
        return "user"

    return "jin"


def build_runtime_session_event_snapshot(
        context,
        *,
        source: str = "runtime_action",
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
        "initiated_by": detect_session_event_initiator(
            user_message
        ),
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


def compact_session_event_snapshot(
        snapshot: dict,
) -> dict:

    compact = {}

    for key in (
            "index",
            "memory_type",
            "source",
            "initiated_by",
            "turn_number",
            "user_message_count",
            "assistant_message_count",
            "runtime_snapshot_count",
            "diff_count",
            "title",
            "temperature",
            "intensity",
            "why_it_matters",
            "preserve_detail",
            "memory",
            "user_message",
            "assistant_response",
    ):
        if key not in snapshot:
            continue

        value = snapshot.get(
            key
        )

        if isinstance(
            value,
            str,
        ):
            value = compact_session_prompt_text(
                value
            )

        compact[key] = value

    return compact


def select_session_prompt_snapshots(
        snapshots: list[dict],
) -> tuple[list[dict], int]:

    snapshots = list(
        snapshots
        or []
    )

    if len(snapshots) <= MAX_SESSION_PROMPT_SNAPSHOTS:
        return snapshots, 0

    head_count = 2
    tail_count = MAX_SESSION_PROMPT_SNAPSHOTS - head_count

    return (
        snapshots[:head_count]
        + snapshots[-tail_count:],
        len(snapshots) - MAX_SESSION_PROMPT_SNAPSHOTS,
    )


def build_runtime_l2_memory_system_prompt() -> str:

    return (
        "You are JIN's L2 pattern memory summarizer.\n"
        "Return only the new L2 pattern memory as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Write memory as atomic bullet lines, one semantic entity per line.\n"
        "Every memory entry MUST use the format:\n "
        "<key>: <value>\n"
        "L2 works above L1 factual runtime memory.\n"
        "Use only the recent L1 patch window supplied by the runtime.\n"
        "This window is selected because normalized L1 keys or topics repeated across patches.\n"
        "Pattern memory should not learn from itself.\n"
        "Do not treat existing possible pattern, observed tendency, emerging signal, or other pattern-memory entries as evidence.\n"
        "Pattern entries may be displayed as context, but they must never contribute to occurrence counts or create new pattern entries.\n"
        "Occurrences must be derived only from actual conversation evidence in the supplied L1 patches, not from previously generated pattern summaries.\n"
        "L2 is a hypothesis generator, not a source of settled memory.\n"
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
                    )
                else:
                    lines.append(
                        "- "
                        f"{entry.get('key', '')}: {entry.get('value', '')}"
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
) -> str:

    snapshot_blocks = []
    selected_snapshots, omitted_snapshot_count = (
        select_session_prompt_snapshots(
            runtime_memory_snapshots
        )
    )

    for snapshot in selected_snapshots:
        snapshot_blocks.append(
            "\n".join([
                f"snapshot: {snapshot.get('index', 0)}",
                f"total_diff: {snapshot.get('total_diff', 0)}",
                "memory:",
                (
                    snapshot.get(
                        "raw_memory",
                        "",
                    ).strip()
                    or "<empty>"
                ),
            ])
        )

    selected_diff_history = list(
        diff_history
        or []
    )[-MAX_SESSION_PROMPT_DIFFS:]
    omitted_diff_count = max(
        0,
        len(
            diff_history
            or []
        )
        - len(selected_diff_history),
    )
    compact_event_snapshots = [
        compact_session_event_snapshot(
            snapshot
        )
        for snapshot in (
            session_event_snapshots
            or []
        )
        if isinstance(
            snapshot,
            dict,
        )
    ]

    return "\n\n".join([
        "Current L3 session memory:",
        current_session_memory.strip() or "<empty>",
        "Current L2 pattern memory for context only:",
        runtime_l2_memory.strip() or "<empty>",
        "Session event snapshots array:",
        json.dumps(
            compact_event_snapshots,
            ensure_ascii=False,
            indent=2,
        ),
        "Selected L1 runtime memory snapshot history:",
        (
            f"omitted_middle_snapshots: {omitted_snapshot_count}"
            if omitted_snapshot_count
            else "omitted_middle_snapshots: 0"
        ),
        "\n\n---\n\n".join(snapshot_blocks) or "<empty>",
        "Recent L1 diff history:",
        (
            f"omitted_older_diffs: {omitted_diff_count}"
            if omitted_diff_count
            else "omitted_older_diffs: 0"
        ),
        json.dumps(
            selected_diff_history,
            ensure_ascii=False,
            indent=2,
        ),
        "Rewrite the L3 session memory now.",
    ])


def build_runtime_memory_system_prompt() -> str:

    return (
        "You are JIN's runtime memory summarizer.\n"
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
        "Keep memory actionable: write what helps the next answer, not a recap of "
        "what happened. \n"
        "Always keep a separate last_jin_response field with the concise gist of JIN's latest completed answer, offer, or question. "
        "Do not store the full wording; store only the meaning needed to resolve the user's next short or elliptical reply. "
        "Never omit this field from the memory snapshot; update it each completed turn, and mark it incomplete if JIN's answer was interrupted.\n"
        "Record only explicit facts from the current conversation: active topic, current request, "
        "user-stated intent, decisions, constraints, pending choices, open references, interruptions, "
        "and unresolved state.\n"
        "When the latest turn contains an explicit emotional moment, record one line as emotional moment: <type>; trigger quote: \"<short exact user quote>\".\n"
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
        "Treat any existing line about JIN's identity, nature, origin, role, capabilities, memory, or self-description as a durable JIN fact even when its key is not exactly jin_fact, such as jin self-introduction, JIN identity, or known fact about JIN.\n"
        "Treat any existing line about the user's name, identity, role, preference, location, age, or other personal detail as a durable user fact even when its key is not exactly user_fact.\n"
        "Once a durable JIN fact or durable user fact exists, keep its key permanently across L1 snapshots: do not delete it, rename it, demote it to known fact/current topic, or merge it into another line.\n"
        "For durable JIN/user facts, only the value may change, and only when the latest current conversation explicitly corrects, cancels, or supersedes that fact.\n"
        "When the user asks to remember a word, code word, token, password-like label, or important detail, store the value with a self-describing purpose, such as stored_memory: <value> (purpose: future recall test), and include the user's label/synonym when available.\n"
        "Do not store bare ambiguous values like memory token: <value> without recording why the value matters.\n"
        "Preserve strong details until the current context directly makes them obsolete, corrected, cancelled, or irrelevant; a topic/task change alone is not enough.\n"
        "Topic/task changes, shallow summarization, memory pressure, or a new current request are never enough to remove or rename durable JIN/user fact keys.\n"
        "Do not update a value when JIN merely paraphrased, reordered, or reworded the same offer, "
        "open reference, pending choice, or conversational state without adding a new explicit fact.\n"
        "Treat semantic rephrasing as no-op memory: keep the previous value unchanged unless the actual meaning changed.\n"
        "Drop old details only when they are clearly obsolete, duplicated, or no longer useful.\n"
        "Decide the summary depth from the signal in the latest turn.\n"
        "Use shallow summarization for simple factual, isolated, or low-signal turns: "
        "keep one or two bullet lines with only the dry fact, topic, or unresolved "
        "reference that could help the next answer.\n"
        "Use deep summarization for turns that reveal user intent, project direction, "
        "decisions, constraints, pending choices, open references, implementation direction, "
        "or a meaningful shift in the immediate conversation state; use three to six bullet lines when "
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
        "The final memory snapshot should feel like current live trusted state.\n"
    )


def build_runtime_memory_user_prompt(
        *,
        current_memory: str,
        user_message: str,
        assistant_message: str,
        current_l2_memory: str = "",
) -> str:

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
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
) -> str:

    lines = [
        "Current runtime memory:",
        current_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
        "Current L2 pattern memory for occurrence tracking only:",
        current_l2_memory.strip() or "<empty>",
        "",
        "New completed turns since that memory snapshot:",
        ]

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
