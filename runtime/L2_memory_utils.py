import re

from runtime.L2_memory_rules import (
    DEFAULT_RUNTIME_L2_MEMORY,
    L2_EVIDENCE_FIRST_SEEN_PATTERN,
    L2_EVIDENCE_LAST_SEEN_PATTERN,
    L2_EVIDENCE_OCCURRENCES_PATTERN,
    L2_EVIDENCE_QUOTE_META_PATTERN,
    L2_EVIDENCE_QUOTE_PATTERN,
    L2_MAX_EVIDENCE_PATCHES,
    L2_OCCURRENCE_PATTERN_KEYS,
    L2_PATTERN_EVIDENCE_EXAMPLE_LIMIT,
    L2_PATTERN_EVIDENCE_KEY_PATTERN,
    L2_TRIGGER_IGNORED_KEYS,
    L2_USER_MESSAGE_EVIDENCE_LIMIT,
    L2_USER_MESSAGE_QUOTED_VALUE_PATTERN,
    RUNTIME_L2_MEMORY_SYSTEM_PROMPT,
    RUNTIME_L2_REPEATED_SUFFIX_PATTERN,
)


def normalize_memory_key(key: str) -> str:
    return str(key or "").strip().lower()


EMBEDDED_L2_PATTERN_EVIDENCE_RE = re.compile(
    r"(?P<line>"
    r"L2_pattern_evidence_\d+\s*:\s*"
    r".*?"
    r"\[\s*quote\s*:\s*\"[^\"]*\"\s*\]\s*"
    r"\[\s*first_seen_turn_snapshot\s*:\s*\d+\s*\]\s*"
    r"\[\s*last_seen_turn_snapshot\s*:\s*\d+\s*\]"
    r")",
    re.IGNORECASE,
)


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
            evidence_lines.extend(
                match.group(
                    "line"
                ).strip()
                for match in EMBEDDED_L2_PATTERN_EVIDENCE_RE.finditer(
                    line
                )
            )
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
    L2_PATTERN_EVIDENCE_KEY_PATTERN,
    re.IGNORECASE,
)
L2_EVIDENCE_QUOTE_RE = re.compile(
    L2_EVIDENCE_QUOTE_PATTERN,
)
L2_EVIDENCE_FIRST_SEEN_RE = re.compile(
    L2_EVIDENCE_FIRST_SEEN_PATTERN,
    re.IGNORECASE,
)
L2_EVIDENCE_LAST_SEEN_RE = re.compile(
    L2_EVIDENCE_LAST_SEEN_PATTERN,
    re.IGNORECASE,
)
L2_EVIDENCE_OCCURRENCES_RE = re.compile(
    L2_EVIDENCE_OCCURRENCES_PATTERN,
    re.IGNORECASE,
)
L2_EVIDENCE_QUOTE_META_RE = re.compile(
    L2_EVIDENCE_QUOTE_META_PATTERN,
    re.IGNORECASE,
)
RUNTIME_REPEATED_SUFFIX_RE = re.compile(
    RUNTIME_L2_REPEATED_SUFFIX_PATTERN,
    re.IGNORECASE,
)
USER_MESSAGE_QUOTED_VALUE_RE = re.compile(
    L2_USER_MESSAGE_QUOTED_VALUE_PATTERN,
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
        limit: int = L2_PATTERN_EVIDENCE_EXAMPLE_LIMIT,
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
        limit: int = L2_PATTERN_EVIDENCE_EXAMPLE_LIMIT,
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

        if snapshot_index < 0:
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
            "user repeatedly sending the same message "
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

def get_runtime_l2_user_turn_count(
        context,
) -> int:

    return int(
        getattr(
            context,
            "user_message_count",
            getattr(
                context,
                "turn_number",
                0,
            ),
        )
        or 0
    )


def ensure_runtime_l2_state(
        context,
) -> None:

    if not hasattr(
        context,
        "runtime_l2_memory",
    ):
        context.runtime_l2_memory = DEFAULT_RUNTIME_L2_MEMORY

    if not hasattr(
        context,
        "runtime_l2_last_turn",
    ):
        context.runtime_l2_last_turn = 0


def is_runtime_l2_context_line_key(
        key: str,
) -> bool:

    return (
        str(
            key
            or ""
        )
        .strip()
        .casefold()
        .startswith(
            "l2_pattern_evidence_"
        )
    )


def filter_runtime_l2_context_lines_from_patch(
        patch: dict,
) -> dict:

    if not isinstance(
        patch,
        dict,
    ):
        return {}

    filtered_patch = {
        "added": [],
        "changed": [],
        "removed": [],
    }

    for entry in patch.get(
            "added",
            [],
    ) or []:
        if is_runtime_l2_context_line_key(
                entry.get(
                    "key",
                    "",
                )
        ):
            continue

        filtered_patch["added"].append(
            entry
        )

    for entry in patch.get(
            "changed",
            [],
    ) or []:
        if (
                is_runtime_l2_context_line_key(
                    entry.get(
                        "previous_key",
                        "",
                    )
                )
                or is_runtime_l2_context_line_key(
                    entry.get(
                        "current_key",
                        "",
                    )
                )
        ):
            continue

        filtered_patch["changed"].append(
            entry
        )

    for entry in patch.get(
            "removed",
            [],
    ) or []:
        if is_runtime_l2_context_line_key(
                entry.get(
                    "key",
                    "",
                )
        ):
            continue

        filtered_patch["removed"].append(
            entry
        )

    return filtered_patch


def compact_runtime_l2_user_message_evidence(
        value,
        *,
        limit: int = L2_USER_MESSAGE_EVIDENCE_LIMIT,
) -> str:

    text = str(
        value
        or ""
    ).strip()

    text = " ".join(
        text.split()
    )

    if len(text) <= limit:
        return text

    return text[:limit].rstrip()


def runtime_l1_patch_total_diff(
        patch: dict,
) -> float:

    total_diff = 0

    total_diff += 30 * len(
        patch.get(
            "added",
            [],
        )
        or []
    )
    total_diff += 20 * len(
        patch.get(
            "removed",
            [],
        )
        or []
    )

    for entry in patch.get(
            "changed",
            [],
    ) or []:
        total_diff += round(
            (
                entry.get(
                    "key_change_ratio",
                    0,
                )
                + entry.get(
                    "value_change_ratio",
                    0,
                )
            )
            * 50,
            2,
        )

    return total_diff


def average_diff(
        diffs: list[float],
) -> float:

    if not diffs:
        return 0

    return round(
        sum(diffs) / len(diffs),
        2,
    )


def format_diff_value(
        value: float,
) -> str:

    return (
        f"{value:.2f}"
        .rstrip(
            "0"
        )
        .rstrip(
            "."
        )
    )


def diff_value_range(
        diffs: list[float],
) -> float:

    if not diffs:
        return 0

    return round(
        max(diffs) - min(diffs),
        2,
    )


def normalize_l2_signal_key(
        key: str,
) -> str:

    return re.sub(
        r"[\s-]+",
        "_",
        normalize_memory_key(
            key
        ),
    ).strip("_")


def is_runtime_l2_trigger_key(
        key: str,
) -> bool:

    normalized = normalize_l2_signal_key(
        key
    )

    return bool(
        normalized
        and normalized not in L2_TRIGGER_IGNORED_KEYS
        and not normalized.startswith(
            "l2_pattern_evidence_"
        )
    )


def extract_l2_patch_signal_keys(
        patch: dict,
) -> set[str]:

    changes = patch.get(
        "changes",
        {},
    ) or {}
    keys = set()

    for entry in changes.get(
            "added",
            [],
    ) or []:
        key = normalize_l2_signal_key(
            entry.get(
                "key",
                "",
            )
        )

        if is_runtime_l2_trigger_key(
                key
        ):
            keys.add(
                key
            )

    for entry in changes.get(
            "changed",
            [],
    ) or []:
        key = normalize_l2_signal_key(
            entry.get(
                "current_key",
                "",
            )
            or entry.get(
                "previous_key",
                "",
            )
        )

        if is_runtime_l2_trigger_key(
                key
        ):
            keys.add(
                key
            )

    return keys


def build_l2_occurrence_episodes(
        positions: list[int],
        history: list[dict],
) -> list[dict]:

    episodes = []

    for position in sorted(
            set(
                positions
            )
    ):
        patch = history[position]
        turn_number = int(
            patch.get(
                "turn_number",
                0,
            )
            or 0
        )

        if (
                episodes
                and position == episodes[-1]["end_position"] + 1
        ):
            episodes[-1]["end_position"] = position
            episodes[-1]["end_turn"] = turn_number
            episodes[-1]["count"] += 1
            continue

        episodes.append({
            "start_position": position,
            "end_position": position,
            "start_turn": turn_number,
            "end_turn": turn_number,
            "count": 1,
        })

    return episodes


def compact_runtime_l2_signal_value(
        value,
        *,
        limit: int = 260,
) -> str:

    text = " ".join(
        str(
            value
            or ""
        ).split()
    )

    if len(text) <= limit:
        return text

    return text[:limit].rstrip() + "…"


def clean_runtime_l2_evidence_patch(
        patch: dict,
        *,
        candidate_keys: set[str],
        candidate_messages: set[str],
) -> dict:

    changes = patch.get(
        "changes",
        {},
    ) or {}
    cleaned_changes = {
        "added": [],
        "changed": [],
    }

    for entry in changes.get(
            "added",
            [],
    ) or []:
        key = normalize_l2_signal_key(
            entry.get(
                "key",
                "",
            )
        )

        if key not in candidate_keys:
            continue

        cleaned_changes["added"].append({
            "key": key,
            "value": compact_runtime_l2_signal_value(
                entry.get(
                    "value",
                    "",
                )
            ),
        })

    for entry in changes.get(
            "changed",
            [],
    ) or []:
        key = normalize_l2_signal_key(
            entry.get(
                "current_key",
                "",
            )
            or entry.get(
                "previous_key",
                "",
            )
        )

        if key not in candidate_keys:
            continue

        cleaned_changes["changed"].append({
            "key": key,
            "value": compact_runtime_l2_signal_value(
                entry.get(
                    "current_value",
                    "",
                )
            ),
        })

    user_messages = []
    has_signal_changes = bool(
        cleaned_changes["added"]
        or cleaned_changes["changed"]
    )

    for message in extract_l2_patch_user_messages(
            patch
    ):
        compact = compact_runtime_l2_user_message_evidence(
            message
        )
        normalized = normalize_l2_pattern_evidence_example(
            compact
        )

        if (
                normalized in candidate_messages
                or has_signal_changes
        ):
            user_messages.append(
                compact
            )

    user_messages = list(
        dict.fromkeys(
            user_messages
        )
    )[-3:]

    return {
        "turn_number": int(
            patch.get(
                "turn_number",
                0,
            )
            or 0
        ),
        "snapshot_index": int(
            patch.get(
                "snapshot_index",
                0,
            )
            or 0
        ),
        "user_messages": user_messages,
        "changes": cleaned_changes,
    }


def build_runtime_l2_recurrence_evidence(
        context,
) -> dict:

    ensure_runtime_l2_state(
        context
    )

    history = list(
        getattr(
            context,
            "runtime_l1_diff_history",
            [],
        )
        or []
    )

    if not history:
        return {
            "keys": [],
            "messages": [],
            "patches": [],
        }

    last_l2_turn = int(
        getattr(
            context,
            "runtime_l2_last_turn",
            0,
        )
        or 0
    )
    key_positions: dict[str, list[int]] = {}
    message_positions: dict[str, list[int]] = {}
    message_examples: dict[str, str] = {}

    for position, patch in enumerate(
            history
    ):
        for key in extract_l2_patch_signal_keys(
                patch
        ):
            key_positions.setdefault(
                key,
                [],
            ).append(
                position
            )

        for message in extract_l2_patch_user_messages(
                patch
        ):
            compact = compact_runtime_l2_user_message_evidence(
                message
            )
            normalized = normalize_l2_pattern_evidence_example(
                compact
            )

            if not normalized:
                continue

            message_positions.setdefault(
                normalized,
                [],
            ).append(
                position
            )
            message_examples[normalized] = compact

    candidate_keys = set()
    relevant_positions = set()

    for key, positions in key_positions.items():
        episodes = build_l2_occurrence_episodes(
            positions,
            history,
        )

        if len(episodes) < 2:
            continue

        latest_episode = episodes[-1]

        if latest_episode["start_turn"] <= last_l2_turn:
            continue

        candidate_keys.add(
            key
        )
        relevant_positions.update(
            positions
        )

    candidate_messages = set()

    for normalized, positions in message_positions.items():
        episodes = build_l2_occurrence_episodes(
            positions,
            history,
        )
        if len(episodes) < 2:
            continue

        latest_episode = episodes[-1]

        if latest_episode["start_turn"] <= last_l2_turn:
            continue

        candidate_messages.add(
            normalized
        )
        relevant_positions.update(
            positions
        )

    if not candidate_keys and not candidate_messages:
        return {
            "keys": [],
            "messages": [],
            "patches": [],
        }

    ordered_positions = sorted(
        relevant_positions
    )

    if len(ordered_positions) > L2_MAX_EVIDENCE_PATCHES:
        ordered_positions = [
            ordered_positions[0],
            *ordered_positions[-(
                L2_MAX_EVIDENCE_PATCHES - 1
            ):],
        ]
        ordered_positions = list(
            dict.fromkeys(
                ordered_positions
            )
        )

    patches = [
        clean_runtime_l2_evidence_patch(
            history[position],
            candidate_keys=candidate_keys,
            candidate_messages=candidate_messages,
        )
        for position in ordered_positions
    ]
    patches = [
        patch
        for patch in patches
        if (
            patch.get("user_messages")
            or patch.get("changes", {}).get("added")
            or patch.get("changes", {}).get("changed")
        )
    ]

    return {
        "keys": sorted(
            candidate_keys
        ),
        "messages": [
            message_examples[normalized]
            for normalized in sorted(
                candidate_messages
            )
            if normalized in message_examples
        ],
        "patches": patches,
    }


def build_runtime_l2_memory_system_prompt() -> str:

    return RUNTIME_L2_MEMORY_SYSTEM_PROMPT


def build_runtime_l2_memory_user_prompt(
        *,
        current_l2_memory: str,
        patches: list[dict],
        recurring_keys: list[str] | None = None,
        recurring_messages: list[str] | None = None,
) -> str:

    recurring_keys = list(
        recurring_keys
        or []
    )
    recurring_messages = list(
        recurring_messages
        or []
    )

    lines = [
        "Current L2 pattern memory:",
        current_l2_memory.strip() or "<empty>",
        "",
        "Recurrence gate:",
        "signals: " + (
            ", ".join(
                recurring_keys
            )
            if recurring_keys
            else "<none>"
        ),
        "repeated user messages: " + (
            " | ".join(
                f'"{message}"'
                for message in recurring_messages
            )
            if recurring_messages
            else "<none>"
        ),
        "",
        "Selected L1 recurrence evidence:",
    ]

    for index, patch in enumerate(
            patches,
            start=1,
    ):
        lines.extend([
            "",
            f"Evidence {index}",
            f"turn: {patch.get('turn_number', 0)}",
            f"snapshot: {patch.get('snapshot_index', 0)}",
        ])

        for message in patch.get(
                "user_messages",
                [],
        ) or []:
            lines.append(
                f'user_message: "{message}"'
            )

        changes = patch.get(
            "changes",
            {},
        ) or {}

        for entry in changes.get(
                "added",
                [],
        ) or []:
            lines.append(
                "signal added: "
                f"{entry.get('key', '')}: {entry.get('value', '')}"
            )

        for entry in changes.get(
                "changed",
                [],
        ) or []:
            lines.append(
                "signal changed: "
                f"{entry.get('key', '')}: {entry.get('value', '')}"
            )

    lines.extend([
        "",
        "Use only this evidence. Ignore ordinary live-state churn. ",
        "Update L2 only if the recurrence is genuinely useful for future adaptation.",
    ])

    return "\n".join(
        lines
    )
