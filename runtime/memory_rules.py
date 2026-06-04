import json


DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
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
        "Preserve what should survive a browser reload or a new tab: active project direction, "
        "explicit decisions, durable facts, unresolved tasks, constraints, and next step.\n"
        "Use the diff history to identify which topics or constraints actually changed during the session.\n"
        "Do not copy every L1 line. Compress repeated or superseded states.\n"
        "Do not infer durable user personality traits, relationship claims, or preferences from weak signal.\n"
        "Keep user-requested memory tokens and explicit facts in their own retrieval-friendly lines.\n"
        "Drop transient last_jin_response details unless they contain an unresolved question or next step.\n"
        "The final L3 snapshot should feel like a session handoff note for fluent continuation."
    )


def build_runtime_session_memory_user_prompt(
        *,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        runtime_l2_memory: str = "",
) -> str:

    snapshot_blocks = []

    for snapshot in runtime_memory_snapshots:
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

    return "\n\n".join([
        "Current L3 session memory:",
        current_session_memory.strip() or "<empty>",
        "Current L2 pattern memory for context only:",
        runtime_l2_memory.strip() or "<empty>",
        "Complete L1 runtime memory snapshot history:",
        "\n\n---\n\n".join(snapshot_blocks) or "<empty>",
        "Complete L1 diff history:",
        json.dumps(
            diff_history,
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
        "When the user asks to remember a word, code word, token, password-like label, or important detail, store it with a retrieval-friendly key such as key detail or memory token and include the user's label/synonym in the value.\n"
        "Preserve strong details until the current context directly makes them obsolete, corrected, cancelled, or irrelevant; a topic/task change alone is not enough.\n"
        "If existing memory contains a jin_fact about JIN, such as gender, age, identity, origin, or other self-fact, preserve it exactly and never change, contradict, or overwrite it.\n"
        "If existing memory contains a user_fact about the user, such as name, identity, role, preference, location, age, or other personal fact, preserve it exactly and never change, contradict, or overwrite it.\n"
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
