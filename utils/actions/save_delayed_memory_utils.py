import json
import re

from .delayed_memory_utils import generate_delayed_memory_report_id


LONG_TERM_FACT_ID_RE = re.compile(
    r"^l4_[a-z0-9_-]+$",
    re.IGNORECASE,
)

DELAYED_MEMORY_FIELD_RE = re.compile(
    r"(?im)^[^\S\r\n]*(title|summary|tags|body|long_term_facts_ids)"
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
        ).strip().casefold()

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


def collect_long_term_fact_ids_from_reports(
    reports,
) -> set[str]:

    if not isinstance(reports, dict):
        return set()

    fact_ids = set()

    for report in reports.values():
        if not isinstance(report, dict):
            continue

        fact_ids.update(
            normalize_long_term_fact_ids(
                report.get(
                    "long_term_facts_ids",
                    [],
                )
            )
        )

    return fact_ids


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
        elif field_name == "long_term_facts_ids":
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
            "long_term_facts_ids": normalize_long_term_fact_ids(
                fields.get(
                    "long_term_facts_ids",
                    [],
                )
            ),
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
