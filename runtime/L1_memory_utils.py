import re

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES,
    RUNTIME_USER_IDLE_KEY,
)
from runtime.L2_memory_utils import (
    extract_runtime_l2_pattern_evidence_lines,
)



PLACEHOLDER_MEMORY_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "unknown",
    "not applicable",
    "not_applicable",
    "no",
    "нет",
    "неизвестно",
    "не применимо",
}

CONFIRMATION_SUFFIX_RE = re.compile(
    r"\s*\(confirmed:\s*[^)]*\)\s*$",
    re.IGNORECASE,
)


def strip_runtime_memory_confirmation_suffix(
        value: str,
) -> str:

    return CONFIRMATION_SUFFIX_RE.sub(
        "",
        value or "",
    ).strip()


def is_runtime_memory_placeholder_value(
        value: str,
) -> bool:

    cleaned = strip_runtime_memory_confirmation_suffix(
        value
    )

    cleaned = cleaned.strip().strip(".。;；")

    return cleaned.lower() in PLACEHOLDER_MEMORY_VALUES


def remove_runtime_memory_placeholder_lines(
        memory: str,
) -> str:

    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" not in line:
            lines.append(
                raw_line
            )
            continue

        _, value = line.split(
            ":",
            1,
        )

        if is_runtime_memory_placeholder_value(
            value
        ):
            continue

        lines.append(
            raw_line
        )

    return "\n".join(
        lines
    ).strip()

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

    if context is not None:
        for evidence_line in extract_runtime_l2_pattern_evidence_lines(
                getattr(
                    context,
                    "runtime_l2_memory",
                    "",
                )
        ):
            if evidence_line not in lines:
                lines.append(
                    evidence_line
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
        "Do not write the current turn, turn_number, or user_message_count into ordinary L1 memory lines such as session status. "
        "Trusted runtime context already carries those counters; only open_contract and countdown_contract may store turn progress when the user created a turn-based obligation.\n"
        "Do not explain why a memory line was kept, changed, or removed.\n"
        "Do not record analysis of the user's personality, motives, or long-term behavior.\n"

        # Keeps output stable and parseable.
        "Every memory line must be a complete key:value entry.\n"
        "One line must contain one semantic entity.\n"
        "Do not use nested bullets, numbered lists, JSON, markdown tables, or headings.\n"
        "Do not output empty keys or bare values.\n"
        "Do not create placeholder memory fields. Never write values like N/A, none, unknown, null, not applicable, or empty just to satisfy a key. If there is no concrete value for a key, omit that line entirely.\n"
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

        "Always keep a separate user_message field containing the latest user message as a direct verbatim quote. "
        "Use this exact format: user_message: \"<latest user message exactly as written>\". "
        "If the latest user message includes runtime repetition metadata, keep it outside the quote as an exact suffix: user_message: \"<latest user message exactly as written>\" [ repeated: N ]. "
        "Do not put [ repeated: N ] inside the quote. Do not invent the suffix; preserve it only when supplied by runtime. "
        "Do not translate, summarize, normalize, or replace the user's wording with an English intent label. "
        "This field is runtime evidence for L2 counters and must update on every L1 snapshot. "

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
        "L2_pattern_evidence_N lines are owned by L2 and are immutable for L1: never edit, rewrite, remove, rename, append to, or add metadata to those lines.\n"
        "When the latest turn resolves, cancels, corrects, explains, or identifies an L2_pattern_evidence_N item as a test, L1 MUST create or update a separate companion key using this exact shape: L2_pattern_evidence_N_status: status: <resolved|cancelled|corrected|test>; reason: <short reason>. "
        "For example: L2_pattern_evidence_1_status: status: resolved; reason: identified as a test. Leave the original L2_pattern_evidence_N line unchanged.\n"
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
        "This list names protected key types, not a required schema. Preserve only durable lines that already exist with concrete values. "
        "Never invent missing durable keys and never fill absent durable keys with N/A, none, unknown, null, or not applicable placeholders. "
        "These existing concrete lines are immune to shallow summarization, topic switches, memory pressure, and low-signal turns. "
        "If you are about to produce output that does not contain all concrete durable lines from the current memory, stop and add them back.\n"
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
        strength_zones: dict | None = None,
) -> str:

    hot_traces = ""
    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        hot_traces = (
            f"hot_traces: {hot}\n\n"
        )

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        f"{hot_traces}"
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
        strength_zones: dict | None = None,
) -> str:

    lines = [
        "Current runtime memory:",
        current_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
    ]

    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        lines.extend([
            f"hot_traces: {hot}",
            "",
        ])

    lines.extend([
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
