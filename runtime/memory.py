import asyncio
import contextlib
import json
import traceback
from difflib import SequenceMatcher

from clients.service_client import (
    ask_service_model,
)
from runtime.state import (
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
)
from config_loader import (
    config,
)
from clients.response_extractor import (
    ResponseExtractor,
)
from runtime.state_sync import (
    refresh_runtime_state,
)
from utils.tokens import (
    estimate_runtime_tokens,
)


DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
)

DEFAULT_RUNTIME_L2_MEMORY = ""
MIN_L2_TURNS = 3
L2_PATCH_WINDOW = 5
L2_REPEATED_KEY_THRESHOLD = 3

def change_ratio(
        previous: str,
        current: str,
) -> float:

    previous = (
            previous
            or ""
    ).strip()

    current = (
            current
            or ""
    ).strip()

    if not previous and not current:
        return 0.0

    if not previous or not current:
        return 1.0

    similarity = SequenceMatcher(
        None,
        previous.lower(),
        current.lower(),
    ).ratio()

    return round(
        1.0 - similarity,
        3,
        )

async def safe_call(
        call,
        *args,
        **kwargs,
):

    if call is None:
        return

    with contextlib.suppress(Exception):
        await call(
            *args,
            **kwargs,
        )


async def emit_runtime_memory_update(
        context,
) -> dict:

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    memory = getattr(context, "runtime_memory", "")

    if not hasattr(
        context,
        "runtime_memory_snapshots",
    ):
        context.runtime_memory_snapshots = []

    snapshot = build_runtime_memory_snapshot(context, memory)

    context.runtime_memory_snapshots.append(snapshot)
    context.runtime_memory_snapshot_index = snapshot["index"]

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": memory,
            "updates": getattr(context, "runtime_memory_updates", 0),
            "snapshot": snapshot,
            "snapshots_count": len(context.runtime_memory_snapshots),
            "snapshot_index": context.runtime_memory_snapshot_index,
        },
    )

    return snapshot


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


def extract_runtime_memory_text(
        response: dict,
) -> str:

    text = (
            ResponseExtractor.extract_content_text(
                response
            )
            or ResponseExtractor.extract_reasoning_text(
        response
    )
    )

    return text.strip()


def is_runtime_memory_response_truncated(
        response: dict,
) -> bool:

    finish_reason = (
        ResponseExtractor
        .extract_finish_reason(
            response
        )
        .lower()
    )

    return finish_reason in (
        "length",
        "max_tokens",
    )


def looks_like_incomplete_runtime_memory(
        text: str,
) -> bool:

    stripped = (
            text
            or ""
    ).strip()

    if not stripped:
        return True

    if stripped[-1] in (
            ",",
            ":",
            "(",
            "[",
            "{",
    ):
        return True

    pairs = (
        (
            "(",
            ")",
        ),
        (
            "[",
            "]",
        ),
        (
            "{",
            "}",
        ),
    )

    return any(
        stripped.count(open_char)
        > stripped.count(close_char)
        for open_char, close_char
        in pairs
    )


async def refresh_runtime_memory_summarizer_usage(
        context,
        *,
        system_prompt: str,
        user_prompt: str,
        response: dict | None = None,
) -> None:

    if context is None:
        return

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    if getattr(
        emitter,
        "emit",
        None,
    ) is None:
        return

    usage = (
        ResponseExtractor.extract_usage(
            response
        )
        if isinstance(
            response,
            dict,
        )
        else None
    )

    if (
            response is not None
            and not usage
    ):
        return

    context_tokens = (
        usage.get(
            "prompt_tokens",
            0,
        )
        if usage
        else estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=user_prompt,
        )
    )

    total_tokens = (
        usage.get(
            "total_tokens",
            0,
        )
        if usage
        else context_tokens
    )

    if not context_tokens:
        return

    await refresh_runtime_state(
        context,
        runtime_id=(
            RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
        ),
        used_tokens=(
            total_tokens
            or context_tokens
        ),
        context_tokens=context_tokens,
        total_tokens=(
            total_tokens
            or context_tokens
        ),
        max_tokens=config.SERVICE_CONTEXT_WINDOW,
        last_error=None,
        status="online",
    )


def build_runtime_summarizer_payload(
        *,
        service_client,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
) -> dict:

    return {
        "model": getattr(
            service_client,
            "model_uid",
            "<service>",
        ),
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }


async def log_runtime_summarizer_payload(
        context,
        *,
        label: str,
        payload: dict,
) -> None:

    await safe_call(
        getattr(
            getattr(
                context,
                "logger",
                None,
            ),
            "log_summarizer",
            None,
        ),
        f"[MEMORY] {label} summarizer request",
        details=json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
    )


async def log_runtime_summarizer_result(
        context,
        *,
        label: str,
        result: str,
) -> None:

    await safe_call(
        getattr(
            getattr(
                context,
                "logger",
                None,
            ),
            "log_summarizer",
            None,
        ),
        f"[MEMORY] {label} summarizer result",
        details=(
            result.strip()
            or "<empty>"
        ),
    )


async def ask_runtime_memory_model(
        *,
        context=None,
        service_client,
        current_memory: str,
        user_message: str,
        assistant_message: str,
) -> dict:

    system_prompt = (
        build_runtime_memory_system_prompt()
    )
    user_prompt = (
        build_runtime_memory_user_prompt(
            current_memory=current_memory,
            user_message=user_message,
            assistant_message=assistant_message,
            current_l2_memory=getattr(
                context,
                "runtime_l2_memory",
                "",
            ),
        )
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = (
        config.SERVICE_MAX_TOKENS
    )

    await log_runtime_summarizer_payload(
        context,
        label="L1",
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
    )

    return response


async def ask_runtime_memory_batch_model(
        *,
        context=None,
        service_client,
        current_memory: str,
        turns: list[dict],
) -> dict:

    system_prompt = (
        build_runtime_memory_system_prompt()
    )
    user_prompt = (
        build_runtime_memory_batch_user_prompt(
            current_memory=current_memory,
            turns=turns,
            current_l2_memory=getattr(
                context,
                "runtime_l2_memory",
                "",
            ),
        )
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = (
        config.SERVICE_MAX_TOKENS
    )

    await log_runtime_summarizer_payload(
        context,
        label="L1 batch",
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
    )

    return response


async def ask_runtime_l2_memory_model(
        *,
        context=None,
        service_client,
        current_l2_memory: str,
        patches: list[dict],
) -> dict:

    system_prompt = (
        build_runtime_l2_memory_system_prompt()
    )
    user_prompt = (
        build_runtime_l2_memory_user_prompt(
            current_l2_memory=current_l2_memory,
            patches=patches,
        )
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = (
        config.SERVICE_MAX_TOKENS
    )

    await log_runtime_summarizer_payload(
        context,
        label="L2",
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
    )

    return response


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
        "runtime_l2_pending_patches",
    ):
        context.runtime_l2_pending_patches = []

    if not hasattr(
        context,
        "runtime_l2_last_turn",
    ):
        context.runtime_l2_last_turn = 0


async def record_runtime_l1_diff(
        context,
        snapshot: dict,
        turns: list[dict] | None = None,
) -> None:

    ensure_runtime_l2_state(
        context
    )

    total_diff = snapshot.get(
        "total_diff",
        0,
    )
    context.runtime_conversation_activity_diff = total_diff

    observed_turns = list(
        turns
        or []
    )

    user_turn_count = get_runtime_l2_user_turn_count(
        context
    )

    context.runtime_l2_pending_patches.append({
        "turn_number": user_turn_count,
        "snapshot_index": snapshot.get(
            "index",
            0,
        ),
        "total_diff": total_diff,
        "changes": snapshot.get(
            "patch",
            {},
        ),
    })

    turns_since_l2 = (
        user_turn_count
        - getattr(
            context,
            "runtime_l2_last_turn",
            0,
        )
    )

    recent_diffs = get_recent_l2_diff_values(
        context
    )
    diff_average = average_diff(
        recent_diffs
    )
    diff_range = diff_value_range(
        recent_diffs
    )
    repeated_keys = get_repeated_l2_patch_keys(
        context
    )
    l2_last_turn = getattr(
        context,
        "runtime_l2_last_turn",
        0,
    )
    l2_turn_label = (
        f"turns since L2 {turns_since_l2}"
        if l2_last_turn
        else f"L2 not run yet; observed turns {user_turn_count}"
    )

    if total_diff == 0:
        latest_turn = (
            observed_turns[-1]
            if observed_turns
            else {}
        )
        context.runtime_zero_diff_alert = {
            "turn_number": user_turn_count,
            "user_message": latest_turn.get(
                "user_message",
                "",
            ),
            "assistant_message": latest_turn.get(
                "assistant_message",
                "",
            ),
            "reason": (
                "Previous L1 memory update produced total_diff 0."
            ),
        }

    await safe_call(
        getattr(
            getattr(
                context,
                "logger",
                None,
            ),
            "log_service",
            None,
        ),
        (
            "[MEMORY] L1 diff "
            f"+{format_diff_value(total_diff)}; "
            f"recent diffs {format_diff_values(recent_diffs)}; "
            f"avg {format_diff_value(diff_average)}; "
            f"range {format_diff_value(diff_range)}; "
            f"patch window {len(recent_diffs)}/{L2_PATCH_WINDOW}; "
            f"repeated keys {repeated_keys}; "
            f"{l2_turn_label}"
        ),
    )


def get_recent_l2_patches(
        context,
) -> list[dict]:

    return list(
        getattr(
            context,
            "runtime_l2_pending_patches",
            [],
        )
        or []
    )[-L2_PATCH_WINDOW:]


def get_recent_l2_diff_values(
        context,
) -> list[float]:

    return [
        patch.get(
            "total_diff",
            0,
        )
        for patch in get_recent_l2_patches(
            context
        )
    ]


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


def format_diff_values(
        values: list[float],
) -> str:

    return (
        "["
        + ", ".join(
            format_diff_value(
                value
            )
            for value in values
        )
        + "]"
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


def extract_l2_patch_keys(
        patch: dict,
) -> set[str]:

    changes = patch.get(
        "changes",
        {},
    )

    keys = set()

    for entry in (
            changes.get(
                "added",
                [],
            )
            or []
    ):
        key = normalize_memory_key(
            entry.get(
                "key",
                "",
            )
        )

        if key:
            keys.add(
                key
            )

    for entry in (
            changes.get(
                "changed",
                [],
            )
            or []
    ):
        for key_name in (
                "current_key",
                "previous_key",
        ):
            key = normalize_memory_key(
                entry.get(
                    key_name,
                    "",
                )
            )

            if key:
                keys.add(
                    key
                )

    for entry in (
            changes.get(
                "removed",
                [],
            )
            or []
    ):
        key = normalize_memory_key(
            entry.get(
                "key",
                "",
            )
        )

        if key:
            keys.add(
                key
            )

    return keys


def count_l2_patch_keys(
        patches: list[dict],
) -> dict[str, int]:

    counts = {}

    for patch in patches:
        for key in extract_l2_patch_keys(
                patch
        ):
            counts[key] = (
                counts.get(
                    key,
                    0,
                )
                + 1
            )

    return counts


def get_repeated_l2_patch_keys(
        context,
) -> dict[str, int]:

    counts = count_l2_patch_keys(
        get_recent_l2_patches(
            context
        )
    )

    return {
        key: count
        for key, count in counts.items()
        if count >= L2_REPEATED_KEY_THRESHOLD
    }


def should_run_runtime_l2_memory(
        context,
) -> bool:

    ensure_runtime_l2_state(
        context
    )

    user_turn_count = get_runtime_l2_user_turn_count(
        context
    )
    turns_since_l2 = (
        user_turn_count
        - getattr(
            context,
            "runtime_l2_last_turn",
            0,
        )
    )

    recent_patches = get_recent_l2_patches(
        context
    )
    repeated_keys = count_l2_patch_keys(
        recent_patches
    )

    return (
        turns_since_l2 >= MIN_L2_TURNS
        and len(recent_patches) >= L2_PATCH_WINDOW
        and any(
            count >= L2_REPEATED_KEY_THRESHOLD
            for count in repeated_keys.values()
        )
    )


async def maybe_summarize_runtime_l2_memory(
        *,
        context,
) -> str:

    ensure_runtime_l2_state(
        context
    )

    if not should_run_runtime_l2_memory(
        context
    ):
        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    patches = get_recent_l2_patches(
        context
    )

    if not patches:
        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
    )

    if service_client is None:
        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    current_l2_memory = getattr(
        context,
        "runtime_l2_memory",
        DEFAULT_RUNTIME_L2_MEMORY,
    )

    try:
        response = await ask_runtime_l2_memory_model(
            context=context,
            service_client=service_client,
            current_l2_memory=current_l2_memory,
            patches=patches,
        )

        updated_l2_memory = extract_runtime_memory_text(
            response
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            skip_reason = "L2 summarizer response was truncated by max_tokens."

        elif (
                updated_l2_memory.strip()
                and looks_like_incomplete_runtime_memory(
            updated_l2_memory
        )
        ):
            skip_reason = "L2 summarizer returned text that looks structurally incomplete."

        if skip_reason:
            await safe_call(
                getattr(
                    getattr(
                        context,
                        "logger",
                        None,
                    ),
                    "log_error",
                    None,
                ),
                "[MEMORY] L2 memory update skipped",
                details=build_memory_update_skip_details(
                    reason=skip_reason,
                    previous_memory=current_l2_memory,
                    candidate_memory=updated_l2_memory,
                ),
            )

            return current_l2_memory

        context.runtime_l2_memory = updated_l2_memory
        context.runtime_l2_last_turn = get_runtime_l2_user_turn_count(
            context
        )
        context.runtime_l2_pending_patches = []

        await safe_call(
            getattr(
                getattr(
                    context,
                    "logger",
                    None,
                ),
                "log_service",
                None,
            ),
            "[MEMORY] L2 memory updated",
        )

        await log_runtime_summarizer_result(
            context,
            label="L2 pattern memory",
            result=updated_l2_memory,
        )

        await emit_runtime_memory_update(
            context
        )

        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        formatted_traceback = (
            traceback.format_exc()
        )

        await safe_call(
            getattr(
                getattr(
                    context,
                    "logger",
                    None,
                ),
                "log_error",
                None,
            ),
            "[MEMORY] L2 memory update failed",
            details=formatted_traceback,
        )

        return current_l2_memory


async def summarize_runtime_memory(
        *,
        context,
        user_message: str,
        assistant_message: str,
) -> str:

    if not assistant_message.strip():
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
    )

    if service_client is None:
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    current_memory = getattr(
        context,
        "runtime_memory",
        "",
    )

    try:
        response = await ask_runtime_memory_model(
            context=context,
            service_client=service_client,
            current_memory=current_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )

        updated_memory = extract_runtime_memory_text(
            response
        )

        if (
                is_runtime_memory_response_truncated(
                    response
                )
                or looks_like_incomplete_runtime_memory(
            updated_memory
        )
        ):
            await safe_call(
                getattr(
                    getattr(
                        context,
                        "logger",
                        None,
                    ),
                    "log_error",
                    None,
                ),
                "[MEMORY] runtime memory update skipped",
                details=build_memory_update_skip_details(
                    reason="Summarizer returned an incomplete memory update.",
                    previous_memory=current_memory,
                    candidate_memory=updated_memory,
                ),
            )

            return current_memory

        updates_counter = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

        if updated_memory or updates_counter == 0:
            context.runtime_memory = updated_memory
            context.runtime_memory_stable = updated_memory
            context.runtime_memory_updates = updates_counter + 1

            logger = getattr(
                context,
                "logger",
                None,
            )
            log_service = getattr(
                logger,
                "log_service",
                None,
            )

            await safe_call(
                log_service,
                "[MEMORY] runtime memory updated",
            )

            snapshot = await emit_runtime_memory_update(
                context
            )

            await record_runtime_l1_diff(
                context,
                snapshot,
                turns=[
                    {
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                    },
                ],
            )
            await maybe_summarize_runtime_l2_memory(
                context=context,
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        formatted_traceback = (
            traceback.format_exc()
        )

        logger = getattr(
            context,
            "logger",
            None,
        )
        log_error = getattr(
            logger,
            "log_error",
            None,
        )

        await safe_call(
            log_error,
            "[MEMORY] runtime memory update failed",
            details=formatted_traceback,
        )

        return getattr(
            context,
            "runtime_memory",
            "",
        )


async def summarize_runtime_memory_pending_turns(
        *,
        context,
) -> str:

    turns = list(
        context.runtime_memory_pending_turns
    )

    if not turns:
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
    )

    if service_client is None:
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    initial_memory = getattr(
        context,
        "runtime_memory_stable",
        "",
    )

    try:
        response = await ask_runtime_memory_batch_model(
            context=context,
            service_client=service_client,
            current_memory=initial_memory,
            turns=turns,
        )

        updated_memory = extract_runtime_memory_text(
            response
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            skip_reason = "Summarizer response was truncated by max_tokens."

        elif looks_like_incomplete_runtime_memory(updated_memory):
            skip_reason = "Summarizer returned text that looks structurally incomplete."

        if skip_reason:
            await safe_call(
                getattr(
                    getattr(
                        context,
                        "logger",
                        None,
                    ),
                    "log_error",
                    None,
                ),
                "[MEMORY] runtime memory update skipped",
                details=build_memory_update_skip_details(
                    reason="Summarizer returned an incomplete memory update.",
                    previous_memory=initial_memory,
                    candidate_memory=updated_memory,
                ),
            )

            return initial_memory

        updates_counter = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

        if updated_memory or updates_counter == 0:
            context.runtime_memory = updated_memory
            context.runtime_memory_stable = updated_memory
            context.runtime_memory_updates = updates_counter + 1

            context.runtime_memory_pending_turns = [
                turn
                for turn in context.runtime_memory_pending_turns
                if turn not in turns
            ]

            logger = getattr(
                context,
                "logger",
                None,
            )
            log_service = getattr(
                logger,
                "log_service",
                None,
            )

            await safe_call(
                log_service,
                "[MEMORY] runtime memory updated",
            )

            snapshot = await emit_runtime_memory_update(
                context
            )

            await record_runtime_l1_diff(
                context,
                snapshot,
                turns=turns,
            )
            await maybe_summarize_runtime_l2_memory(
                context=context,
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        formatted_traceback = (
            traceback.format_exc()
        )

        logger = getattr(
            context,
            "logger",
            None,
        )
        log_error = getattr(
            logger,
            "log_error",
            None,
        )

        await safe_call(
            log_error,
            "[MEMORY] runtime memory update failed",
            details=formatted_traceback,
        )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    finally:
        if (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is asyncio.current_task()
        ):
            context.runtime_memory_update_task = None


def schedule_runtime_memory_update(
        *,
        context,
        user_message: str,
        assistant_message: str,
) -> asyncio.Task | None:

    if not assistant_message.strip():
        return None

    context.runtime_memory_pending_turns.append({
        "user_message": user_message,
        "assistant_message": assistant_message,
    })

    previous_task = getattr(
        context,
        "runtime_memory_update_task",
        None,
    )

    if (
            previous_task is not None
            and not previous_task.done()
    ):
        previous_task.cancel()

    task = asyncio.create_task(
        summarize_runtime_memory_pending_turns(
            context=context,
        )
    )

    context.runtime_memory_update_task = task

    background_tasks = getattr(
        context,
        "background_tasks",
        None,
    )

    if background_tasks is None:
        background_tasks = set()
        context.background_tasks = background_tasks

    background_tasks.add(
        task
    )
    task.add_done_callback(
        background_tasks.discard
    )

    return task


def schedule_interrupted_runtime_memory_update(
        *,
        context,
) -> asyncio.Task | None:

    user_message = getattr(
        context,
        "runtime_turn_user_message",
        "",
    )

    assistant_message = (
        build_interrupted_assistant_message(
            user_message=user_message,
            assistant_message=getattr(
                context,
                "runtime_turn_assistant_response",
                "",
            ),
        )
    )

    if not user_message.strip():
        return None

    return schedule_runtime_memory_update(
        context=context,
        user_message=user_message,
        assistant_message=assistant_message,
    )


async def cancel_runtime_memory_update(
        context,
) -> None:

    task = getattr(
        context,
        "runtime_memory_update_task",
        None,
    )

    if (
            task is None
            or task.done()
    ):
        return

    task.cancel()

    with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
    ):
        await task

    context.runtime_memory_update_task = None

def build_memory_update_skip_details(
        *,
        reason: str,
        previous_memory: str,
        candidate_memory: str,
) -> str:

    return (
        f"{reason}\n\n"
        "Previous memory:\n"
        "----------------\n"
        f"{previous_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        "Candidate memory:\n"
        "-----------------\n"
        f"{candidate_memory.strip() or '<empty>'}"
    )

def parse_runtime_memory_lines(memory: str) -> list[dict]:
    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" in line:
            key, value = line.split(":", 1)
        else:
            key, value = "note", line

        lines.append({
            "key": key.strip(),
            "value": value.strip(),
            "status": "same",
        })

    return lines

def normalize_memory_key(
        key: str,
) -> str:

    return (
        key
        .strip()
        .lower()
    )

def find_best_previous_line(
        key: str,
        previous_lines: list[dict],
) -> dict | None:

    normalized_key = normalize_memory_key(
        key
    )

    best_line = None
    best_score = 0.0

    for previous_line in previous_lines:

        previous_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if not previous_key:
            continue

        score = SequenceMatcher(
            None,
            previous_key,
            normalized_key,
        ).ratio()

        if score > best_score:
            best_score = score
            best_line = previous_line

    if best_score >= 0.58:
        return best_line

    return None

def apply_runtime_memory_diff(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> list[dict]:

    if not previous_snapshot:
        for line in current_lines:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"

        return current_lines

    previous_lines = (
            previous_snapshot.get(
                "lines",
                []
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        value = (
                line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = (
                previous_by_normalized_key.get(
                    normalized_key
                )
                or find_best_previous_line(
            key,
            previous_lines,
        )
        )

        # -----------------------------------------
        # EXACT KEY NOT FOUND
        # -----------------------------------------

        if previous_line is None:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"

            continue

        previous_key = (
                previous_line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        previous_value = (
                previous_line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        key_delta = change_ratio(
            previous_key,
            key,
        )

        value_delta = change_ratio(
            previous_value,
            value,
        )

        line["key_change_ratio"] = key_delta
        line["value_change_ratio"] = value_delta

        line["key_status"] = (
            "changed"
            if key_delta > 0
            else "same"
        )

        line["value_status"] = (
            "changed"
            if value_delta > 0
            else "same"
        )

        if (
                line["key_status"] == "changed"
                or line["value_status"] == "changed"
        ):
            line["status"] = "changed"

        else:
            line["status"] = "same"

    return current_lines


def build_runtime_memory_patch(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> dict:

    patch = {
        "added": [],
        "changed": [],
        "removed": [],
    }
    total_diff = 0

    if not previous_snapshot:
        for line in current_lines:
            patch["added"].append({
                "key": line.get(
                    "key",
                    "",
                ),
                "value": line.get(
                    "value",
                    "",
                ),
            })
            total_diff += 30

        return {
            "patch": patch,
            "total_diff": total_diff,
        }

    previous_lines = (
            previous_snapshot.get(
                "lines",
                [],
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                "",
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    matched_previous_ids = set()

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    "",
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = (
                previous_by_normalized_key.get(
                    normalized_key
                )
                or find_best_previous_line(
            key,
            previous_lines,
        )
        )

        if previous_line is None:
            patch["added"].append({
                "key": key,
                "value": line.get(
                    "value",
                    "",
                ),
            })
            total_diff += 30
            continue

        matched_previous_ids.add(
            id(previous_line)
        )

        key_delta = line.get(
            "key_change_ratio",
            0,
        )
        value_delta = line.get(
            "value_change_ratio",
            0,
        )

        if key_delta or value_delta:
            patch["changed"].append({
                "previous_key": previous_line.get(
                    "key",
                    "",
                ),
                "previous_value": previous_line.get(
                    "value",
                    "",
                ),
                "current_key": key,
                "current_value": line.get(
                    "value",
                    "",
                ),
                "key_change_ratio": key_delta,
                "value_change_ratio": value_delta,
            })
            total_diff += round(
                (
                    key_delta
                    + value_delta
                )
                * 50,
                2,
            )

    for previous_line in previous_lines:
        if id(previous_line) in matched_previous_ids:
            continue

        patch["removed"].append({
            "key": previous_line.get(
                "key",
                "",
            ),
            "value": previous_line.get(
                "value",
                "",
            ),
        })
        total_diff += 20

    return {
        "patch": patch,
        "total_diff": total_diff,
    }


def build_runtime_memory_snapshot(
        context,
        memory: str,
) -> dict:

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    previous_snapshot = (
        snapshots[-1]
        if snapshots
        else None
    )

    lines = parse_runtime_memory_lines(
        memory
    )

    lines = apply_runtime_memory_diff(
        lines,
        previous_snapshot,
    )

    patch_details = build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    return {
        "session_id": getattr(context, "session_id", ""),
        "index": len(snapshots),
        "raw_memory": memory,
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }
