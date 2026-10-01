import json
import re

from .delayed_memory_utils import generate_delayed_memory_report_id


LONG_TERM_FACT_ID_RE = re.compile(r"^F[1-9]\d*$", re.IGNORECASE)
ATTACHMENT_FILE_ID_RE = re.compile(r"^[a-z0-9]{6}$", re.IGNORECASE)

DELAYED_MEMORY_FIELD_RE = re.compile(
    r"(?im)^[^\S\r\n]*(title|summary|tags|body|anchor_lt_facts_ids|"
    r"lt_facts_ids|attachments_ids)"
    r"[^\S\r\n]*:[^\S\r\n]*(.*)$",
)


def _character_is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1

    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1

    return bool(backslashes % 2)


def _repair_json_quotes_inside_markdown_code(text: str) -> str:
    """Repair unescaped JSON quotes inside Markdown code spans/fences.

    A model can emit valid Markdown inside a JSON string, for example
    ``server returned `"unread_count": 1` ``, while forgetting that the inner
    quotes still need JSON escaping. Repair only quotes inside backtick-delimited
    Markdown so the surrounding JSON structure is not guessed or rewritten.
    """

    source = str(text or "")
    if "`" not in source or '"' not in source:
        return source

    repaired = []
    active_backtick_run = 0
    index = 0

    while index < len(source):
        character = source[index]

        if character == "`" and not _character_is_escaped(source, index):
            run_end = index + 1
            while run_end < len(source) and source[run_end] == "`":
                run_end += 1

            run_length = run_end - index
            repaired.append(source[index:run_end])

            if active_backtick_run == 0:
                active_backtick_run = run_length
            elif run_length >= active_backtick_run:
                active_backtick_run = 0

            index = run_end
            continue

        if (
            character == '"'
            and active_backtick_run
            and not _character_is_escaped(source, index)
        ):
            repaired.append('\\"')
        else:
            repaired.append(character)

        index += 1

    return "".join(repaired)


def normalize_long_term_fact_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    candidates = []

    for item in source:
        if isinstance(item, list):
            candidates.extend(
                normalize_long_term_fact_ids(item)
            )
            continue

        text = str(item or "").strip()

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                candidates.extend(
                    normalize_long_term_fact_ids(parsed)
                )
                continue

        candidates.extend(
            re.split(
                r"[,;\s]+",
                text,
            )
        )

    fact_ids = []
    seen = set()

    for candidate in candidates:
        fact_id = str(
            candidate
            or ""
        ).strip().strip(
            "\"'[]"
        ).upper()

        if (
            not fact_id
            or fact_id in seen
            or not LONG_TERM_FACT_ID_RE.fullmatch(
                fact_id
            )
        ):
            continue

        seen.add(fact_id)
        fact_ids.append(fact_id)

    return fact_ids


def normalize_delayed_memory_fact_ids(
    anchor_lt_facts_ids=None,
    lt_facts_ids=None,
) -> tuple[list[str], list[str]]:
    """Normalize delayed-memory L-T references.

    ``lt_facts_ids`` is the full set of L-T facts represented by the report.
    ``anchor_lt_facts_ids`` is a visible, important subset and is always folded
    into ``lt_facts_ids``.
    """

    anchor_ids = normalize_long_term_fact_ids(
        anchor_lt_facts_ids or []
    )
    fact_ids = normalize_long_term_fact_ids([
        *normalize_long_term_fact_ids(
            lt_facts_ids or []
        ),
        # Anchors are a highlighted subset, not a sorting key. Missing
        # anchors are folded into the full list, then the full list is kept
        # in normal numeric F-id order (F1, F15, ... F190).
        *anchor_ids,
    ])
    fact_ids.sort(
        key=lambda fact_id: int(fact_id[1:])
    )

    return anchor_ids, fact_ids


def normalize_delayed_memory_attachment_ids(value) -> list[str]:
    """Normalize delayed-memory file references without imposing a count cap."""

    source = value if isinstance(value, list) else [value]
    candidates = []

    for item in source:
        if isinstance(item, list):
            candidates.extend(
                normalize_delayed_memory_attachment_ids(item)
            )
            continue

        text = str(item or "").strip()

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                candidates.extend(
                    normalize_delayed_memory_attachment_ids(parsed)
                )
                continue

        candidates.extend(
            re.split(
                r"[,;\s]+",
                text,
            )
        )

    attachment_ids = []
    seen = set()

    for candidate in candidates:
        attachment_id = str(
            candidate
            or ""
        ).strip().strip(
            "\"'[]"
        ).casefold()

        if (
            not attachment_id
            or attachment_id in seen
            or not ATTACHMENT_FILE_ID_RE.fullmatch(
                attachment_id
            )
        ):
            continue

        seen.add(attachment_id)
        attachment_ids.append(attachment_id)

    return attachment_ids


def collect_long_term_fact_ids_from_reports(
    reports,
) -> set[str]:
    """Compatibility name: return facts represented by delayed memory."""

    if not isinstance(reports, dict):
        return set()

    fact_ids = set()

    for report in reports.values():
        if not isinstance(report, dict):
            continue

        _anchor_ids, report_fact_ids = normalize_delayed_memory_fact_ids(
            report.get("anchor_lt_facts_ids", []),
            report.get("lt_facts_ids", []),
        )
        fact_ids.update(report_fact_ids)

    return fact_ids


def collect_anchor_fact_report_ids(
    reports,
) -> dict[str, list[str]]:
    """Map each anchor L-T fact id to delayed-memory report ids referencing it."""

    if not isinstance(reports, dict):
        return {}

    report_ids_by_fact: dict[str, list[str]] = {}

    for report_id, report in reports.items():
        if not isinstance(report, dict):
            continue

        normalized_report_id = str(report_id or "").strip().casefold()
        if not normalized_report_id:
            continue

        anchor_ids, _fact_ids = normalize_delayed_memory_fact_ids(
            report.get("anchor_lt_facts_ids", []),
            report.get("lt_facts_ids", []),
        )

        for fact_id in anchor_ids:
            report_ids_by_fact.setdefault(fact_id, [])
            if normalized_report_id not in report_ids_by_fact[fact_id]:
                report_ids_by_fact[fact_id].append(normalized_report_id)

    return report_ids_by_fact


def normalize_delayed_memory_tags(value) -> list[str]:
    """Return delayed-memory tags in one backwards-compatible format.

    Historical reports contain a mix of proper JSON arrays, comma-separated
    strings, hashtag lists and loose bracketed lists. Keep real multi-word
    tags intact when they are already separate array items, while cleaning the
    wrappers used by the legacy formats.
    """

    source = value if isinstance(value, list) else [value]
    candidates = []

    for item in source:
        if isinstance(item, (list, tuple, set)):
            candidates.extend(normalize_delayed_memory_tags(list(item)))
            continue

        text = str(item or "").strip()
        if not text:
            continue

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                candidates.extend(normalize_delayed_memory_tags(parsed))
                continue

        explicit_parts = [
            part.strip()
            for part in re.split(r"[,;\r\n]+", text)
            if part.strip()
        ]

        for part in explicit_parts:
            stripped = part.strip()
            bracketed = stripped.startswith("[") and stripped.endswith("]")
            hashtag_count = len(re.findall(r"(?<!\S)#", stripped))

            if bracketed:
                inner = stripped[1:-1].strip()
                if inner and not any(ch in inner for ch in '"\''):
                    candidates.extend(inner.split())
                    continue

            if hashtag_count >= 2:
                candidates.extend(stripped.split())
                continue

            candidates.append(stripped)

    tags = []
    seen = set()

    for candidate in candidates:
        tag = str(candidate or "").strip()
        tag = tag.strip("[]{}()\"'").strip()
        tag = re.sub(r"^#+", "", tag).strip()
        tag = re.sub(r"#+$", "", tag).strip()
        tag = tag.strip("[]{}()\"'").strip()

        if not tag:
            continue

        identity = tag.casefold()
        if identity in seen:
            continue

        seen.add(identity)
        tags.append(tag)

    return tags


def parse_delayed_memory_payload(
    payload: str,
    *,
    created_session_id: str = "",
    created_time: str = "",
) -> dict:

    text = str(
        payload
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    if not text:
        return {}

    fields = None

    try:
        parsed = json.loads(
            text
        )
    except json.JSONDecodeError:
        repaired_text = _repair_json_quotes_inside_markdown_code(
            text
        )

        if repaired_text != text:
            try:
                parsed = json.loads(
                    repaired_text
                )
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None

    if isinstance(
        parsed,
        dict,
    ):
        if "title" in parsed:
            fields = parsed
        elif len(parsed) == 1:
            nested = next(
                iter(parsed.values())
            )
            if isinstance(
                nested,
                dict,
            ) and "title" in nested:
                fields = nested

    if fields is None:
        # Compatibility path for reports produced before the JSON marker
        # contract. New prompts never advertise this text-field format.
        field_matches = list(
            DELAYED_MEMORY_FIELD_RE.finditer(
                text
            )
        )

        if not field_matches:
            return {}

        fields = {}

        for index, match in enumerate(
            field_matches
        ):
            field_name = match.group(
                1
            ).casefold()
            inline_value = (
                match.group(
                    2
                )
                or ""
            ).strip()
            next_start = (
                field_matches[index + 1].start()
                if index + 1 < len(field_matches)
                else len(text)
            )
            block_value = text[
                match.end():next_start
            ].strip(
                "\n"
            )

            if field_name == "body":
                value = "\n".join(
                    part
                    for part in (
                        inline_value,
                        block_value,
                    )
                    if part
                ).strip()
            elif field_name in {
                "anchor_lt_facts_ids",
                "lt_facts_ids",
            }:
                value = normalize_long_term_fact_ids(
                    " ".join(
                        part
                        for part in (
                            inline_value,
                            block_value,
                        )
                        if part
                    )
                )
            elif field_name == "attachments_ids":
                value = normalize_delayed_memory_attachment_ids(
                    " ".join(
                        part
                        for part in (
                            inline_value,
                            block_value,
                        )
                        if part
                    )
                )
            else:
                value = inline_value

            fields[field_name] = value

    title = str(
        fields.get(
            "title",
            "",
        )
        or ""
    ).strip()

    if not title:
        return {}

    tags = normalize_delayed_memory_tags(
        fields.get(
            "tags",
            [],
        )
    )

    anchor_lt_facts_ids, fact_ids = normalize_delayed_memory_fact_ids(
        fields.get("anchor_lt_facts_ids", []),
        fields.get("lt_facts_ids", []),
    )
    attachment_ids = normalize_delayed_memory_attachment_ids(
        fields.get("attachments_ids", [])
    )

    report_id = generate_delayed_memory_report_id(
        ()
    )

    return {
        report_id: {
            "title": title,
            "summary": str(
                fields.get(
                    "summary",
                    "",
                )
                or ""
            ).strip(),
            "tags": tags,
            "body": str(
                fields.get(
                    "body",
                    "",
                )
                or ""
            ).strip(),
            "pinned": False,
            "anchor_lt_facts_ids": anchor_lt_facts_ids,
            "lt_facts_ids": fact_ids,
            "attachments_ids": attachment_ids,
            "created_session_id": str(
                created_session_id
                or ""
            ).strip(),
            "created_time": str(
                created_time
                or ""
            ).strip(),
        },
    }


def build_save_delayed_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    report = parse_delayed_memory_payload(
        query
    )

    if not report:
        return None

    return json.dumps(
        report,
        ensure_ascii=False,
    )
