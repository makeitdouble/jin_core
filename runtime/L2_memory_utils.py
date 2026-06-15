import re


def extract_runtime_l2_pattern_evidence_lines(
        runtime_l2_memory: str,
) -> list[str]:

    evidence_lines = []

    for raw_line in (runtime_l2_memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if (
                parsed_line is None
                or not is_l2_pattern_evidence_key(
                    parsed_line[0]
                )
        ):
            continue

        evidence_lines.append(
            line
        )

    return evidence_lines


def remove_runtime_l2_pattern_evidence_lines(
        runtime_l2_memory: str,
) -> str:

    output_lines = []

    for raw_line in (runtime_l2_memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if (
                parsed_line is not None
                and is_l2_pattern_evidence_key(
            parsed_line[0]
        )
        ):
            continue

        output_lines.append(
            raw_line
        )

    return "\n".join(
        output_lines
    )


L2_OCCURRENCE_PATTERN_KEYS = {
    "possible pattern",
    "emerging signal",
    "observed tendency",
    "may indicate",
}


def remove_runtime_l2_occurrence_pattern_lines(
        runtime_l2_memory: str,
) -> str:

    output_lines = []

    for raw_line in (runtime_l2_memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if parsed_line is None:
            output_lines.append(
                raw_line
            )
            continue

        key, value = parsed_line

        if (
                key.strip().casefold() in L2_OCCURRENCE_PATTERN_KEYS
                and "occurrences:" in value.casefold()
        ):
            continue

        output_lines.append(
            raw_line
        )

    return "\n".join(
        output_lines
    )

L2_PATTERN_EVIDENCE_KEY_RE = re.compile(
    r"^L2_pattern_evidence_(?P<index>\d+)$",
    re.IGNORECASE,
)
L2_EVIDENCE_QUOTE_RE = re.compile(
    r'"(?P<quote>[^"]+)"',
)
L2_EVIDENCE_FIRST_SEEN_RE = re.compile(
    r"\[\s*first_seen_turn_snapshot\s*:\s*(?P<value>\d+)\s*\]",
    re.IGNORECASE,
)
L2_EVIDENCE_LAST_SEEN_RE = re.compile(
    r"\[\s*last_seen_turn_snapshot\s*:\s*(?P<value>\d+)\s*\]",
    re.IGNORECASE,
)
L2_EVIDENCE_OCCURRENCES_RE = re.compile(
    r"\[\s*occurrences\s*:\s*(?P<value>\d+)\s*\]",
    re.IGNORECASE,
)
L2_EVIDENCE_QUOTE_META_RE = re.compile(
    r"\[\s*quote\s*:\s*\"(?P<quote>[^\"]*)\"\s*\]",
    re.IGNORECASE,
)
RUNTIME_REPEATED_SUFFIX_RE = re.compile(
    r"\s*\[\s*repeated\s*:\s*\d+\s*\]\s*$",
    re.IGNORECASE,
)
USER_MESSAGE_QUOTED_VALUE_RE = re.compile(
    r'^\s*\"(?P<quote>.*)\"\s*(?:\[\s*repeated\s*:\s*\d+\s*\])?\s*$',
    re.IGNORECASE | re.DOTALL,
)


def strip_runtime_repeated_suffix(
        value: str,
) -> str:

    text = str(
        value
        or ""
    ).strip()
    match = USER_MESSAGE_QUOTED_VALUE_RE.match(
        text
    )

    if match:
        text = match.group(
            "quote"
        )

    return RUNTIME_REPEATED_SUFFIX_RE.sub(
        "",
        text,
    ).strip()


def normalize_l2_pattern_evidence_example(
        value: str,
        *,
        limit: int = 100,
) -> str:

    text = strip_runtime_repeated_suffix(
        value
    ).casefold()
    text = re.sub(
        r"[\s,.]+",
        "",
        text,
    )

    return text[:limit]


def compact_l2_pattern_evidence_example(
        value: str,
        *,
        limit: int = 100,
) -> str:

    text = strip_runtime_repeated_suffix(
        value
    )
    text = re.sub(
        r"[\s,.]+",
        " ",
        text.casefold(),
    ).strip()

    return text[:limit].rstrip()


def is_l2_pattern_evidence_key(
        key: str,
) -> bool:

    return bool(
        L2_PATTERN_EVIDENCE_KEY_RE.match(
            str(
                key
                or ""
            ).strip()
        )
    )


def split_l2_memory_line(
        line: str,
) -> tuple[str, str] | None:

    if ":" not in line:
        return None

    key, value = line.split(
        ":",
        1,
    )

    return key.strip(), value.strip()


def parse_l2_pattern_evidence_value(
        value: str,
) -> dict:

    quote_meta_match = L2_EVIDENCE_QUOTE_META_RE.search(
        value
    )
    quote_match = L2_EVIDENCE_QUOTE_RE.search(
        value
    )
    quote = (
        quote_meta_match.group(
            "quote"
        )
        if quote_meta_match
        else (
            quote_match.group(
                "quote"
            )
            if quote_match
            else value
        )
    )
    first_seen_match = L2_EVIDENCE_FIRST_SEEN_RE.search(
        value
    )
    last_seen_match = L2_EVIDENCE_LAST_SEEN_RE.search(
        value
    )
    occurrences_match = L2_EVIDENCE_OCCURRENCES_RE.search(
        value
    )

    return {
        "value": value,
        "quote": quote,
        "normalized_quote": normalize_l2_pattern_evidence_example(
            quote,
        ),
        "first_seen": (
            int(first_seen_match.group("value"))
            if first_seen_match
            else None
        ),
        "last_seen": (
            int(last_seen_match.group("value"))
            if last_seen_match
            else None
        ),
        "occurrences": (
            int(occurrences_match.group("value"))
            if occurrences_match
            else None
        ),
    }


def format_l2_pattern_evidence_value(
        value: str,
        *,
        first_seen: int | None = None,
        last_seen: int | None = None,
        occurrences: int | None = None,
) -> str:

    cleaned = re.sub(
        r"\s*\[\s*(?:first_seen_turn_snapshot|last_seen_turn_snapshot|occurrences)\s*:\s*\d+\s*\]",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    metadata = []

    if first_seen is not None:
        metadata.append(
            f"[ first_seen_turn_snapshot: {first_seen} ]"
        )

    if last_seen is not None:
        metadata.append(
            f"[ last_seen_turn_snapshot: {last_seen} ]"
        )

    # Occurrence counters now live on the current user_message suffix
    # (`[ repeated: N ]`). L2 evidence keeps only the historical span
    # so old pattern lines do not pretend to be an always-current count.

    return " ".join(
        [cleaned]
        + metadata
    ).strip()



def escape_l2_pattern_evidence_quote(
        value: str,
) -> str:

    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def extract_l2_patch_user_messages(
        patch: dict,
) -> list[str]:

    if not isinstance(
        patch,
        dict,
    ):
        return []

    messages = []

    def add_message(
            value,
    ) -> None:

        text = compact_l2_pattern_evidence_example(
            value,
            limit=100,
        )

        if text:
            messages.append(
                text
            )

    add_message(
        patch.get(
            "user_message",
            "",
        )
    )

    for value in patch.get(
            "user_messages",
            [],
    ) or []:
        add_message(
            value
        )

    changes = patch.get(
        "changes",
        {},
    )

    if not isinstance(
        changes,
        dict,
    ):
        return list(
            dict.fromkeys(
                messages
            )
        )

    for entry in changes.get(
            "added",
            [],
    ) or []:
        if (
                str(entry.get("key", "")).strip().casefold()
                == "user_message"
        ):
            add_message(
                entry.get(
                    "value",
                    "",
                )
            )

    for entry in changes.get(
            "changed",
            [],
    ) or []:
        if (
                str(entry.get("current_key", "")).strip().casefold()
                == "user_message"
        ):
            add_message(
                entry.get(
                    "current_value",
                    "",
                )
            )

    return list(
        dict.fromkeys(
            messages
        )
    )


def extract_l2_previous_evidence_by_quote(
        previous_memory: str,
) -> dict[str, dict]:

    evidence_by_quote = {}

    for raw_line in (previous_memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if (
                parsed_line is None
                or not is_l2_pattern_evidence_key(
                    parsed_line[0]
                )
        ):
            continue

        parsed = parse_l2_pattern_evidence_value(
            parsed_line[1]
        )
        normalized_quote = parsed.get(
            "normalized_quote",
            "",
        )

        if normalized_quote:
            evidence_by_quote[normalized_quote] = parsed

    return evidence_by_quote


def build_runtime_l2_repeated_user_message_evidence_memory(
        *,
        previous_memory: str,
        patches: list[dict],
) -> str:

    observations_by_quote: dict[str, dict] = {}

    for patch in patches or []:
        try:
            snapshot_index = int(
                patch.get(
                    "snapshot_index",
                    0,
                )
                or 0
            )
        except (
                TypeError,
                ValueError,
        ):
            snapshot_index = 0

        if snapshot_index <= 0:
            continue

        for message in extract_l2_patch_user_messages(
                patch
        ):
            normalized_quote = normalize_l2_pattern_evidence_example(
                message,
            )

            if not normalized_quote:
                continue

            bucket = observations_by_quote.setdefault(
                normalized_quote,
                {
                    "quote": message,
                    "snapshots": set(),
                },
            )
            bucket["snapshots"].add(
                snapshot_index
            )

    previous_by_quote = extract_l2_previous_evidence_by_quote(
        previous_memory
    )

    output_lines = []

    for normalized_quote, observation in observations_by_quote.items():
        snapshots = sorted(
            observation.get(
                "snapshots",
                set(),
            )
        )

        if len(snapshots) < 2 and normalized_quote not in previous_by_quote:
            continue

        previous = previous_by_quote.get(
            normalized_quote,
            {},
        )
        previous_first_seen = previous.get(
            "first_seen",
        )
        previous_last_seen = previous.get(
            "last_seen",
        )
        previous_occurrences = previous.get(
            "occurrences",
            0,
        ) or 0

        new_snapshots = [
            snapshot
            for snapshot in snapshots
            if (
                    previous_last_seen is None
                    or snapshot > previous_last_seen
            )
        ]

        if previous and not new_snapshots:
            continue

        first_seen = min(
            value
            for value in (
                previous_first_seen,
                snapshots[0] if snapshots else None,
            )
            if value is not None
        )
        last_seen = max(
            value
            for value in (
                previous_last_seen,
                snapshots[-1] if snapshots else None,
            )
            if value is not None
        )
        occurrences = (
            previous_occurrences + len(new_snapshots)
            if previous
            else len(snapshots)
        )

        if occurrences < 2:
            continue

        output_lines.append(
            "L2_pattern_evidence_1: "
            "user repeatedly sending one message in a row "
            f"[ quote: \"{escape_l2_pattern_evidence_quote(observation.get('quote', ''))}\" ] "
            f"[ first_seen_turn_snapshot: {first_seen} ] "
            f"[ last_seen_turn_snapshot: {last_seen} ]"
        )

    return "\n".join(
        output_lines
    )


def merge_runtime_l2_pattern_evidence_memory(
        *,
        previous_memory: str,
        candidate_memory: str,
) -> str:

    output_lines = []
    evidence_by_example: dict[str, dict] = {}

    def ingest_evidence_line(
            line: str,
            *,
            prefer_candidate_text: bool,
    ) -> None:

        parsed_line = split_l2_memory_line(
            line
        )

        if parsed_line is None:
            return

        _key, value = parsed_line
        parsed = parse_l2_pattern_evidence_value(
            value
        )
        example_key = parsed.get(
            "normalized_quote",
            "",
        )

        if not example_key:
            return

        existing = evidence_by_example.get(
            example_key
        )

        if existing is None:
            evidence_by_example[example_key] = {
                **parsed,
                "value": value,
            }
            return

        old_first = existing.get(
            "first_seen",
        )
        new_first = parsed.get(
            "first_seen",
        )
        old_last = existing.get(
            "last_seen",
        )
        new_last = parsed.get(
            "last_seen",
        )
        old_occurrences = existing.get(
            "occurrences",
        )
        new_occurrences = parsed.get(
            "occurrences",
        )

        existing.update({
            "value": (
                value
                if prefer_candidate_text
                else existing.get(
                    "value",
                    value,
                )
            ),
            "first_seen": min(
                value
                for value in (old_first, new_first)
                if value is not None
            ) if any(
                value is not None
                for value in (old_first, new_first)
            ) else None,
            "last_seen": max(
                value
                for value in (old_last, new_last)
                if value is not None
            ) if any(
                value is not None
                for value in (old_last, new_last)
            ) else None,
            "occurrences": max(
                value
                for value in (old_occurrences, new_occurrences)
                if value is not None
            ) if any(
                value is not None
                for value in (old_occurrences, new_occurrences)
            ) else None,
        })

    for raw_line in (
            previous_memory
            or ""
    ).splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if (
                parsed_line is not None
                and is_l2_pattern_evidence_key(
            parsed_line[0]
        )
        ):
            ingest_evidence_line(
                line,
                prefer_candidate_text=False,
            )

    for raw_line in (
            candidate_memory
            or ""
    ).splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parsed_line = split_l2_memory_line(
            line
        )

        if (
                parsed_line is not None
                and is_l2_pattern_evidence_key(
            parsed_line[0]
        )
        ):
            ingest_evidence_line(
                line,
                prefer_candidate_text=True,
            )
            continue

        output_lines.append(
            raw_line
        )

    for index, evidence in enumerate(
            evidence_by_example.values(),
            start=1,
    ):
        output_lines.append(
            "L2_pattern_evidence_"
            f"{index}: "
            + format_l2_pattern_evidence_value(
                evidence.get(
                    "value",
                    "",
                ),
                first_seen=evidence.get(
                    "first_seen",
                ),
                last_seen=evidence.get(
                    "last_seen",
                ),
                occurrences=evidence.get(
                    "occurrences",
                ),
            )
        )

    return "\n".join(
        line
        for line in output_lines
        if str(line).strip()
    )

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
        "Count occurrences by unique patch snapshot values, not by how many rows mention the same behavior inside one patch.\n"
        "If the same user_message appears in both user_messages and changes for one snapshot, it still counts as one occurrence.\n"
        "L2 is a hypothesis generator, not a source of settled memory.\n"
        "If L2 writes one of these confirmable keys, it MUST include a marker: "
        "user_fact, jin_fact, pending_fact, jin_recommendation, user_recommendation. "
        "Use (confirmed: none) unless the supplied patch already contains explicit user, jin, or web confirmation.\n"
        "Allowed outputs: possible pattern, emerging signal, observed tendency, may indicate, contradiction, corrected assumption.\n"
        "Prefer 'possible pattern' over 'pattern'.\n"
        "Every possible pattern, emerging signal, or observed tendency SHOULD include span metadata in the value: "
        "first_seen_snapshot: S1; last_seen_snapshot: S2; evidence summary: <short evidence>; confidence: low|medium|high.\n"
        "Do not put Occurrences counters into L2 pattern memory. Current exact-repeat counts are supplied by runtime on user_message as [ repeated: N ].\n"
        "When L2 names or updates a concrete repeated pattern, also write a companion evidence line named L2_pattern_evidence_N. "
        "Use this exact shape: L2_pattern_evidence_N: <short pattern description> [ quote: \"<literal user_message value>\" ] [ first_seen_turn_snapshot: S1 ] [ last_seen_turn_snapshot: S2 ]\n"
        "For L2_pattern_evidence_N lines, the final token on the line MUST be the closing bracket of [ last_seen_turn_snapshot: S2 ]. "
        "Never append status, notes, explanations, conclusions, punctuation, occurrence counters, or any other text after the final [ last_seen_turn_snapshot: S2 ] bracket.\n"
        "For repeated-message patterns, the quoted literal MUST be copied from the supplied user_message field exactly in the user's original language. "
        "Do not translate it, do not paraphrase it, and do not replace it with an English command or description.\n"
        "The quoted literal may only be stripped of leading/trailing whitespace and cleaned of repeated spaces; keep it at maximum 100 characters. "
        "If no matching user_message is available, omit the L2_pattern_evidence_N line instead of inventing a quote.\n"
        "L2_pattern_evidence_N is runtime accounting evidence, not a personality trait and not a durable user fact.\n"
        "If an existing L2_pattern_evidence_N line matches the same normalized literal example or the same pattern, preserve first_seen_turn_snapshot, then update only last_seen_turn_snapshot when new matching L1 evidence appears.\n"
        "Do not duplicate an existing pattern under a new L2_pattern_evidence_N key; update the existing evidence line instead.\n"
        "For a brand-new pattern with no prior L2 entry, set first_seen_turn_snapshot and last_seen_turn_snapshot from the matching unique patch snapshots in the supplied L1 patch window.\n"
        "Do not create a brand-new pattern when all matching evidence is confined to one unique patch snapshot, even if that snapshot contains multiple rows for the same message.\n"
        "For an existing pattern, preserve its first_seen_snapshot; do not recompute it from the supplied patch window alone.\n"
        "Only update last_seen_snapshot when patch snapshot > old last_seen_snapshot and the L1 evidence actually matches this pattern.\n"
        "If last_seen_snapshot is missing for an existing pattern, initialize it from the newest matching visible evidence.\n"
        "Never add or preserve Occurrences counters on L2_pattern_evidence_N lines.\n"
        "When the user explicitly cancels the pattern, stops doing it, or clearly changes topic, the pattern may be dropped instead of zero-counted.\n"
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

        user_messages = [
            str(message or "").replace("\n", " ").strip()
            for message in (patch.get("user_messages", []) or [])
            if str(message or "").strip()
        ]

        if user_messages:
            lines.append(
                "user_messages:"
            )

            for message in user_messages:
                lines.append(
                    f'- "{message}"'
                )

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
