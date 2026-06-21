import json

from config_loader import (
    config,
)
from runtime.L2_memory_rules import (
    MAX_SESSION_L2_LINES,
)
from runtime.memory_common import (
    build_runtime_summarizer_user_prompt,
)
from utils.tokens import (
    estimate_runtime_tokens,
)
from runtime.L3_memory_rules import (
    L3_EMPTY_PROMPT_PLACEHOLDER,
    L3_INPUT_TOKEN_RESERVE,
    L3_INPUT_TOKEN_TARGET_MAX,
    L3_OMITTED_MEMORY_LINES_TEMPLATE,
    L3_PROMPT_BUDGET_EXCEEDED_MESSAGE,
    L3_SESSION_EVENT_DEFAULT_INITIATED_BY,
    L3_SESSION_EVENT_DEFAULT_SOURCE,
    L3_SESSION_EVENT_MEMORY_TYPE,
    L3_SESSION_META_KEYS,
    L3_SNAPSHOT_ROLE_LATEST,
    L3_SNAPSHOT_ROLE_SELECTED,
    L3_TEXT_TRUNCATED_SUFFIX,
    MAX_SESSION_EVENT_TEXT_CHARS,
    MAX_SESSION_LATEST_MEMORY_TEXT_CHARS,
    MAX_SESSION_LINE_CHARS,
    MAX_SESSION_MEMORY_TEXT_CHARS,
    MAX_SESSION_OLD_SNAPSHOT_TEXT_CHARS,
    MAX_SESSION_PROMPT_DIFFS,
    MAX_SESSION_PROMPT_EVENTS,
    MAX_SESSION_PROMPT_SNAPSHOTS,
    RUNTIME_L3_SESSION_MEMORY_SYSTEM_PROMPT,
    RUNTIME_L3_SNAPSHOT_INDEX_TEMPLATE,
    RUNTIME_L3_SNAPSHOT_MEMORY_LABEL,
    RUNTIME_L3_SNAPSHOT_PATCH_SUMMARY_LABEL,
    RUNTIME_L3_SNAPSHOT_ROLE_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_SNAPSHOT_SEPARATOR,
    RUNTIME_L3_SNAPSHOT_TOTAL_DIFF_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_COMPACT_DIGEST_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_CURRENT_MEMORY_LABEL,
    RUNTIME_L3_USER_PROMPT_L2_CONTEXT_LABEL,
    RUNTIME_L3_USER_PROMPT_OMITTED_DIFFS_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_OMITTED_EVENTS_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_OMITTED_SNAPSHOTS_TEMPLATE,
    RUNTIME_L3_USER_PROMPT_RECENT_DIFFS_LABEL,
    RUNTIME_L3_USER_PROMPT_REWRITE_INSTRUCTION,
    RUNTIME_L3_USER_PROMPT_SELECTED_SNAPSHOTS_LABEL,
    RUNTIME_L3_USER_PROMPT_SESSION_EVENTS_LABEL,
)



def build_l3_session_memory_max_tokens(
        *,
        system_prompt: str,
        user_prompt: str,
        context_window: int | None = None,
) -> int:

    prompt_tokens = estimate_runtime_tokens(
        system_prompt=system_prompt,
        user_input=user_prompt,
    )
    effective_context_window = (
        context_window
        or config.SERVICE_CONTEXT_WINDOW
    )
    response_budget = (
        effective_context_window
        - prompt_tokens
        - 128
    )

    return max(
        128,
        min(
            config.SERVICE_MAX_TOKENS,
            response_budget,
        ),
    )


class L3PromptBudgetExceeded(
    RuntimeError,
):

    def __init__(
            self,
            diagnostic: dict,
    ):

        super().__init__(
            L3_PROMPT_BUDGET_EXCEEDED_MESSAGE
        )
        self.diagnostic = diagnostic


def get_l3_input_token_budget(
        context_window: int | None,
) -> int:

    effective_context_window = (
        context_window
        or config.SERVICE_CONTEXT_WINDOW
    )

    return max(
        1,
        min(
            L3_INPUT_TOKEN_TARGET_MAX,
            effective_context_window
            - L3_INPUT_TOKEN_RESERVE,
        ),
    )


async def build_budgeted_l3_session_user_prompt(
        *,
        context,
        system_prompt: str,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        runtime_l2_memory: str,
        session_event_snapshots: list[dict],
        context_window: int | None,
) -> tuple[str, dict]:

    target_budget = get_l3_input_token_budget(
        context_window
    )

    for minimal in (
            False,
            True,
    ):
        raw_user_prompt = build_runtime_session_memory_user_prompt(
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=runtime_memory_snapshots,
            diff_history=diff_history,
            runtime_l2_memory=runtime_l2_memory,
            session_event_snapshots=session_event_snapshots,
            minimal=minimal,
        )
        user_prompt = build_runtime_summarizer_user_prompt(
            context=context,
            prompt=raw_user_prompt,
        )
        input_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=user_prompt,
        )
        diagnostic = {
            "minimal": minimal,
            "context_window": context_window,
            "input_tokens": input_tokens,
            "target_budget": target_budget,
            "prompt_chars": len(user_prompt),
            "system_prompt_chars": len(system_prompt),
        }

        if input_tokens <= target_budget:
            return user_prompt, diagnostic

    raise L3PromptBudgetExceeded(
        diagnostic
    )


def _parse_int(value, default=None):

    try:
        return int(str(value).strip())
    except (
            TypeError,
            ValueError,
    ):
        return default


def parse_l3_session_snapshot_metadata(
        memory: str,
) -> dict:

    metadata = {}

    for line in str(memory or "").splitlines():
        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1,
        )
        key = key.strip()

        if key not in L3_SESSION_META_KEYS:
            continue

        metadata[key] = _parse_int(
            value,
        )

    return metadata


def get_l3_session_previous_last_turn(
        memory: str,
) -> int | None:

    return parse_l3_session_snapshot_metadata(
        memory
    ).get(
        "session_snapshot_last_turn"
    )


def strip_l3_session_snapshot_metadata(
        memory: str,
) -> str:

    stripped_metadata_keys = set(
        L3_SESSION_META_KEYS
    )

    clean_memory_lines = [
        line
        for line in str(memory or "").splitlines()
        if line.split(
            ":",
            1,
        )[0].strip() not in stripped_metadata_keys
    ]

    return "\n".join(clean_memory_lines).strip()


def prepend_l3_session_snapshot_metadata(
        memory: str,
        *,
        previous_session_memory: str,
        runtime_memory_snapshots: list[dict],
) -> str:

    valid_snapshots = [
        snapshot
        for snapshot in (runtime_memory_snapshots or [])
        if isinstance(snapshot, dict)
    ]

    if not valid_snapshots:
        return str(memory or "").strip()

    previous_metadata = parse_l3_session_snapshot_metadata(
        previous_session_memory
    )
    previous_first_turn = previous_metadata.get(
        "session_snapshot_first_turn"
    )

    runtime_indexes = [
        _parse_int(
            snapshot.get(
                "index",
            ),
        )
        for snapshot in valid_snapshots
    ]
    runtime_indexes = [
        index
        for index in runtime_indexes
        if index is not None
    ]

    if not runtime_indexes:
        return str(memory or "").strip()

    runtime_first_turn = min(runtime_indexes)
    runtime_last_turn = max(runtime_indexes)
    session_first_turn = (
        previous_first_turn
        if previous_first_turn is not None
        else runtime_first_turn
    )

    lines = [
        f"session_snapshot_first_turn: {session_first_turn}",
        f"session_snapshot_last_turn: {runtime_last_turn}",
    ]

    clean_memory = strip_l3_session_snapshot_metadata(
        memory
    )

    if clean_memory:
        lines.append(clean_memory)

    return "\n".join(lines).strip()


def select_l3_unsaved_runtime_snapshots(
        runtime_memory_snapshots: list[dict],
        *,
        saved_runtime_snapshot_index: int | None,
) -> list[dict]:

    valid_snapshots = [
        snapshot
        for snapshot in (runtime_memory_snapshots or [])
        if isinstance(snapshot, dict)
    ]

    if saved_runtime_snapshot_index is None:
        return valid_snapshots

    return [
        snapshot
        for snapshot in valid_snapshots
        if (
            _parse_int(
                snapshot.get(
                    "index",
                ),
                -1,
            )
            > saved_runtime_snapshot_index
        )
    ]


def select_l3_unsaved_diff_history(
        diff_history: list[dict],
        *,
        saved_runtime_snapshot_index: int | None,
) -> list[dict]:

    valid_entries = [
        entry
        for entry in (diff_history or [])
        if isinstance(entry, dict)
    ]

    if saved_runtime_snapshot_index is None:
        return valid_entries

    return [
        entry
        for entry in valid_entries
        if (
            _parse_int(
                entry.get(
                    "snapshot_index",
                ),
                -1,
            )
            > saved_runtime_snapshot_index
        )
    ]


def select_l3_unsaved_session_events(
        session_event_snapshots: list[dict],
        *,
        saved_runtime_snapshot_index: int | None,
) -> list[dict]:

    valid_events = [
        event
        for event in (session_event_snapshots or [])
        if isinstance(event, dict)
    ]

    if saved_runtime_snapshot_index is None:
        return valid_events

    return [
        event
        for event in valid_events
        if (
            _parse_int(
                event.get(
                    "runtime_snapshot_count",
                ),
                -1,
            )
            - 1
            > saved_runtime_snapshot_index
        )
    ]

def build_runtime_session_event_snapshot(
        context,
        *,
        source: str = L3_SESSION_EVENT_DEFAULT_SOURCE,
        initiated_by: str = L3_SESSION_EVENT_DEFAULT_INITIATED_BY,
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
        "memory_type": L3_SESSION_EVENT_MEMORY_TYPE,
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
        + L3_TEXT_TRUNCATED_SUFFIX
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
        return L3_EMPTY_PROMPT_PLACEHOLDER

    if max_lines <= 0:
        return L3_EMPTY_PROMPT_PLACEHOLDER

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
            L3_OMITTED_MEMORY_LINES_TEMPLATE.format(
                count=omitted,
                text=text,
            )
        )

    return text.strip() or L3_EMPTY_PROMPT_PLACEHOLDER


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
            "role": (
                L3_SNAPSHOT_ROLE_LATEST
                if is_latest
                else L3_SNAPSHOT_ROLE_SELECTED
            ),
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

    return RUNTIME_L3_SESSION_MEMORY_SYSTEM_PROMPT

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
                RUNTIME_L3_SNAPSHOT_INDEX_TEMPLATE.format(
                    index=snapshot.get(
                        "index",
                        0,
                    ),
                ),
                RUNTIME_L3_SNAPSHOT_ROLE_TEMPLATE.format(
                    role=snapshot.get(
                        "role",
                        "",
                    ),
                ),
                RUNTIME_L3_SNAPSHOT_TOTAL_DIFF_TEMPLATE.format(
                    total_diff=snapshot.get(
                        "total_diff",
                        0,
                    ),
                ),
                RUNTIME_L3_SNAPSHOT_MEMORY_LABEL,
                snapshot.get(
                    "memory",
                    L3_EMPTY_PROMPT_PLACEHOLDER,
                ),
                RUNTIME_L3_SNAPSHOT_PATCH_SUMMARY_LABEL,
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
        RUNTIME_L3_USER_PROMPT_COMPACT_DIGEST_TEMPLATE.format(
            minimal=digest["minimal"],
        ),
        RUNTIME_L3_USER_PROMPT_CURRENT_MEMORY_LABEL,
        digest["current_session_memory"],
        RUNTIME_L3_USER_PROMPT_L2_CONTEXT_LABEL,
        digest["l2_context"],
        RUNTIME_L3_USER_PROMPT_SESSION_EVENTS_LABEL,
        RUNTIME_L3_USER_PROMPT_OMITTED_EVENTS_TEMPLATE.format(
            count=digest["omitted_events_count"],
        ),
        json.dumps(
            digest["session_events"],
            ensure_ascii=False,
            indent=2,
        ),
        RUNTIME_L3_USER_PROMPT_SELECTED_SNAPSHOTS_LABEL,
        RUNTIME_L3_USER_PROMPT_OMITTED_SNAPSHOTS_TEMPLATE.format(
            count=digest["omitted_middle_snapshots"],
        ),
        RUNTIME_L3_USER_PROMPT_SNAPSHOT_SEPARATOR.join(snapshot_blocks) or L3_EMPTY_PROMPT_PLACEHOLDER,
        RUNTIME_L3_USER_PROMPT_RECENT_DIFFS_LABEL,
        RUNTIME_L3_USER_PROMPT_OMITTED_DIFFS_TEMPLATE.format(
            count=digest["omitted_older_diffs"],
        ),
        json.dumps(
            digest["diff_history"],
            ensure_ascii=False,
            indent=2,
        ),
        RUNTIME_L3_USER_PROMPT_REWRITE_INSTRUCTION,
    ])
