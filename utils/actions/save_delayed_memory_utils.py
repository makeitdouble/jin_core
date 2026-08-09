import json
import re

from .delayed_memory_utils import generate_delayed_memory_report_id


LONG_TERM_FACT_ID_RE = re.compile(r"^F[1-9]\d*$", re.IGNORECASE)

DELAYED_MEMORY_FIELD_RE = re.compile(
    r"(?im)^[^\S\r\n]*(title|summary|tags|body|anchor_fact_ids|"
    r"absorbed_fact_ids|long_term_facts_ids)"
    r"[^\S\r\n]*:[^\S\r\n]*(.*)$",
)


def normalize_long_term_fact_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    candidates = []

    for item in source:
        candidates.extend(
            re.split(
                r"[,;\s]+",
                str(item or ""),
            )
        )

    fact_ids = []
    seen = set()

    for candidate in candidates:
        fact_id = str(
            candidate
            or ""
        ).strip().upper()

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


def normalize_delayed_memory_fact_roles(
    anchor_fact_ids=None,
    absorbed_fact_ids=None,
    legacy_long_term_fact_ids=None,
) -> tuple[list[str], list[str]]:
    """Normalize delayed-memory L4 references.

    Legacy ``long_term_facts_ids`` are treated as absorbed references.  A fact
    can only have one role inside a report; anchor wins when an id appears in
    both lists so an important fact can never be hidden by the same report.
    """

    anchor_ids = normalize_long_term_fact_ids(
        anchor_fact_ids or []
    )
    absorbed_ids = normalize_long_term_fact_ids([
        *normalize_long_term_fact_ids(
            absorbed_fact_ids or []
        ),
        *normalize_long_term_fact_ids(
            legacy_long_term_fact_ids or []
        ),
    ])
    anchor_set = set(anchor_ids)
    absorbed_ids = [
        fact_id
        for fact_id in absorbed_ids
        if fact_id not in anchor_set
    ]

    return anchor_ids, absorbed_ids


def collect_long_term_fact_ids_from_reports(
    reports,
) -> set[str]:
    """Compatibility name: return only facts absorbed by delayed memory."""

    if not isinstance(reports, dict):
        return set()

    fact_ids = set()

    for report in reports.values():
        if not isinstance(report, dict):
            continue

        _anchor_ids, absorbed_ids = normalize_delayed_memory_fact_roles(
            report.get("anchor_fact_ids", []),
            report.get("absorbed_fact_ids", []),
            report.get("long_term_facts_ids", []),
        )
        fact_ids.update(absorbed_ids)

    return fact_ids


def collect_anchor_fact_report_ids(
    reports,
) -> dict[str, list[str]]:
    """Map each anchor L4 fact id to delayed-memory report ids referencing it."""

    if not isinstance(reports, dict):
        return {}

    report_ids_by_fact: dict[str, list[str]] = {}

    for report_id, report in reports.items():
        if not isinstance(report, dict):
            continue

        normalized_report_id = str(report_id or "").strip().casefold()
        if not normalized_report_id:
            continue

        anchor_ids, _absorbed_ids = normalize_delayed_memory_fact_roles(
            report.get("anchor_fact_ids", []),
            report.get("absorbed_fact_ids", []),
            report.get("long_term_facts_ids", []),
        )

        for fact_id in anchor_ids:
            report_ids_by_fact.setdefault(fact_id, [])
            if normalized_report_id not in report_ids_by_fact[fact_id]:
                report_ids_by_fact[fact_id].append(normalized_report_id)

    return report_ids_by_fact


def parse_delayed_memory_content_payload(
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
            "anchor_fact_ids",
            "absorbed_fact_ids",
            "long_term_facts_ids",
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

    tags = [
        tag.strip()
        for tag in str(
            fields.get(
                "tags",
                "",
            )
            or ""
        ).split(",")
        if tag.strip()
    ]

    anchor_fact_ids, absorbed_fact_ids = normalize_delayed_memory_fact_roles(
        fields.get("anchor_fact_ids", []),
        fields.get("absorbed_fact_ids", []),
        fields.get("long_term_facts_ids", []),
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
            "anchor_fact_ids": anchor_fact_ids,
            "absorbed_fact_ids": absorbed_fact_ids,
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

    report = parse_delayed_memory_content_payload(
        query
    )

    if not report:
        return None

    return json.dumps(
        report,
        ensure_ascii=False,
    )
