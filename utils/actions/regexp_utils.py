from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Pattern


# These templates describe the broad marker envelopes supported by the runtime.
# Contracts only provide the canonical private marker and whether it is a block.
REGEXP_TEMPLATES: tuple[str, ...] = (
    (
        r"<\s*(?:INTERNAL_ACTION_)?(?P<name>{name})"
        r"\s+name\s*=\s*(?P<quote>['\"])"
        r"(?P<attribute_payload>[^\r\n<>]*?)"
        r"(?P=quote)\s*/?\s*>+"
    ),
    (
        r"<\|?tool_call\>\s*call\s*:\s*(?:INTERNAL_ACTION_)?"
        r"(?P<name>{name})"
        r"(?:\s*:\s*(?P<payload>(?:(?!</\s*>)[^\r\n>])*?))?"
        r"(?:\s*</\s*>+|\s*/?\s*>+|[^\S\r\n]*(?=\r?\n|$))"
    ),
    (
        r"(?m:^[^\S\r\n]*call\s*:\s*(?:INTERNAL_ACTION_)?"
        r"(?P<name>{name})"
        r"(?:\s*:\s*(?P<payload>[^\r\n]*?))?"
        r"[^\S\r\n]*$)"
    ),
    (
        r"(?m:^[^\S\r\n]*(?:INTERNAL_ACTION_)?"
        r"(?P<name>{name})"
        r"(?:\s*:\s*(?P<payload>[^\r\n]*?))?"
        r"[^\S\r\n]*$)"
    ),
    (
        r"(?m:^[^\S\r\n]*<\s*(?:INTERNAL_ACTION_)?"
        r"(?P<name>{name})"
        r"(?:\s*:\s*(?P<payload>[^\r\n>]*?))?"
        r"[^\S\r\n]*(?=\r?$))"
    ),
)


_PRIVATE_MARKER_RE = re.compile(
    (
        r"^\s*<\s*(?P<name>[A-Z][A-Z0-9_]*)"
        r"(?:\s*:\s*(?P<payload>.*?))?\s*>\s*$"
    ),
    re.IGNORECASE | re.DOTALL,
)

_BARE_PRIVATE_MARKER_RE = re.compile(
    (
        r"^\s*(?:INTERNAL_ACTION_)?(?P<name>[A-Z][A-Z0-9_]*)"
        r"(?:\s*:\s*(?P<payload>.*?))?\s*$"
    ),
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RuntimeActionRegexpMatch:
    start: int
    end: int
    raw: str
    name: str
    payload: str = ""
    source: str = "regexp"


def extract_private_marker_parts(private_marker: str) -> tuple[str, str]:
    value = str(private_marker or "")
    match = (
        _PRIVATE_MARKER_RE.fullmatch(value)
        or _BARE_PRIVATE_MARKER_RE.fullmatch(value)
    )

    if match is None:
        return "", ""

    return (
        str(match.group("name") or "").strip().upper(),
        str(match.group("payload") or "").strip(),
    )


def _runtime_action_aliases(
    private_marker: str,
    runtime_action: str = "",
) -> tuple[str, ...]:
    marker_name, _ = extract_private_marker_parts(private_marker)
    action_name = str(runtime_action or "").strip().upper()
    names: list[str] = []

    for name in (marker_name, action_name):
        if name and name not in names:
            names.append(name)

    # Keep compatibility with plural skill markers without putting aliases in
    # every contract.
    if action_name in {"APPEND_SKILL", "REMOVE_SKILL"}:
        plural_name = f"{action_name}S"
        if plural_name not in names:
            names.append(plural_name)

    return tuple(names)


def _name_pattern(
    private_marker: str,
    runtime_action: str = "",
) -> str:
    return "|".join(
        re.escape(name)
        for name in sorted(
            _runtime_action_aliases(private_marker, runtime_action),
            key=len,
            reverse=True,
        )
    )


@lru_cache(maxsize=None)
def compile_runtime_action_regexp(
    private_marker: str,
    runtime_action: str = "",
    close_tag: bool = False,
) -> Pattern[str]:
    name = _name_pattern(private_marker, runtime_action)

    if not name:
        return re.compile(r"(?!x)x")

    if close_tag:
        expression = (
            r"<\s*(?:INTERNAL_ACTION_)?(?P<name>"
            + name
            + r")\s*>"
            r"[^\S\r\n]*(?:\r?\n)?"
            r"(?P<payload>.*?)"
            r"(?:"
            r"<\s*/\s*(?:INTERNAL_ACTION_)?(?:"
            + name
            + r")\s*>+"
            r"|"
            r"<\s*(?:INTERNAL_ACTION_)?(?:"
            + name
            + r")\s*>"
            r")"
        )
        flags = re.IGNORECASE | re.DOTALL
    else:
        expression = (
            r"<\s*(?:INTERNAL_ACTION_)?(?P<name>"
            + name
            + r")"
            r"(?:\s*:\s*(?P<payload>(?:(?!</\s*>).)*?))?"
            r"\s*(?:</\s*>+|/?>+)"
        )
        flags = re.IGNORECASE

    return re.compile(expression, flags)


@lru_cache(maxsize=None)
def compile_runtime_action_template_regexps(
    private_marker: str,
    runtime_action: str = "",
    regexp_templates: tuple[str, ...] = REGEXP_TEMPLATES,
) -> tuple[Pattern[str], ...]:
    name = _name_pattern(private_marker, runtime_action)

    if not name:
        return ()

    return tuple(
        re.compile(template.format(name=name), re.IGNORECASE)
        for template in regexp_templates
    )


@lru_cache(maxsize=None)
def compile_runtime_action_start_regexp(
    private_marker: str,
    runtime_action: str = "",
) -> Pattern[str]:
    name = _name_pattern(private_marker, runtime_action)

    if not name:
        return re.compile(r"(?!x)x")

    return re.compile(
        r"<\s*(?:INTERNAL_ACTION_)?(?P<name>" + name + r")\s*>",
        re.IGNORECASE,
    )


@lru_cache(maxsize=None)
def compile_runtime_action_end_regexp(
    private_marker: str,
    runtime_action: str = "",
) -> Pattern[str]:
    name = _name_pattern(private_marker, runtime_action)

    if not name:
        return re.compile(r"(?!x)x")

    return re.compile(
        r"<\s*/\s*(?:INTERNAL_ACTION_)?(?:" + name + r")\s*>+",
        re.IGNORECASE,
    )


@lru_cache(maxsize=None)
def compile_runtime_action_tag_regexp(
    private_marker: str,
    runtime_action: str = "",
) -> Pattern[str]:
    name = _name_pattern(private_marker, runtime_action)

    if not name:
        return re.compile(r"(?!x)x")

    return re.compile(
        (
            r"<\s*(?P<slash>/)?\s*(?:INTERNAL_ACTION_)?"
            r"(?P<name>" + name + r")\s*>+"
        ),
        re.IGNORECASE,
    )


def _payload_from_match(match: re.Match[str]) -> str:
    groups = match.groupdict()

    return str(
        groups.get("payload")
        or groups.get("attribute_payload")
        or ""
    ).strip()


def match_regexp(
    text: str,
    regexp: Pattern[str] | str,
) -> tuple[RuntimeActionRegexpMatch, ...]:
    """Match a concrete regexp and return parsed action names and payloads."""
    compiled = re.compile(regexp, re.IGNORECASE) if isinstance(regexp, str) else regexp
    matches: list[RuntimeActionRegexpMatch] = []

    for match in compiled.finditer(str(text or "")):
        name = str(match.groupdict().get("name") or "").strip().upper()

        if not name:
            continue

        matches.append(
            RuntimeActionRegexpMatch(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                name=name,
                payload=_payload_from_match(match),
                source="regexp",
            )
        )

    return tuple(matches)


def match_regexp_templates(
    text: str,
    private_marker: str,
    runtime_action: str = "",
    regexp_templates: tuple[str, ...] = REGEXP_TEMPLATES,
) -> tuple[RuntimeActionRegexpMatch, ...]:
    """Match the shared marker envelopes used for legacy and tool-call forms."""
    matches: list[RuntimeActionRegexpMatch] = []

    for regexp in compile_runtime_action_template_regexps(
        private_marker,
        runtime_action,
        regexp_templates,
    ):
        for item in match_regexp(text, regexp):
            matches.append(
                RuntimeActionRegexpMatch(
                    start=item.start,
                    end=item.end,
                    raw=item.raw,
                    name=item.name,
                    payload=item.payload,
                    source="regexp_template",
                )
            )

    return tuple(matches)


def select_non_overlapping_regexp_matches(
    matches: Iterable[RuntimeActionRegexpMatch],
) -> tuple[RuntimeActionRegexpMatch, ...]:
    ordered = sorted(
        matches,
        key=lambda item: (
            item.start,
            -(item.end - item.start),
            0 if item.source == "regexp" else 1,
        ),
    )
    selected: list[RuntimeActionRegexpMatch] = []
    cursor = -1

    for item in ordered:
        if item.start < cursor:
            continue

        selected.append(item)
        cursor = item.end

    return tuple(selected)


def find_runtime_action_matches(
    text: str,
    private_marker: str,
    runtime_action: str = "",
    close_tag: bool = False,
    regexp: Pattern[str] | str | None = None,
    regexp_templates: tuple[str, ...] = REGEXP_TEMPLATES,
) -> tuple[RuntimeActionRegexpMatch, ...]:
    """Use a concrete regexp first and shared templates as the fallback set."""
    concrete_regexp = regexp or compile_runtime_action_regexp(
        private_marker,
        runtime_action,
        close_tag,
    )
    matches = [
        *match_regexp(text, concrete_regexp),
        *match_regexp_templates(
            text,
            private_marker,
            runtime_action,
            regexp_templates,
        ),
    ]

    return select_non_overlapping_regexp_matches(matches)


def get_runtime_action_start_markers(
    private_marker: str,
    runtime_action: str = "",
) -> tuple[str, ...]:
    markers: list[str] = []
    _, placeholder_payload = extract_private_marker_parts(
        private_marker
    )
    payload_suffix = ":" if placeholder_payload else ""

    for name in _runtime_action_aliases(private_marker, runtime_action):
        angle_marker = f"<{name}{payload_suffix}"
        internal_angle_marker = f"<INTERNAL_ACTION_{name}{payload_suffix}"

        if not placeholder_payload:
            angle_marker += ">"
            internal_angle_marker += ">"

        candidates = [
            angle_marker,
            internal_angle_marker,
            f"<|tool_call>call:{name}{payload_suffix}",
            f"<|tool_call>call:INTERNAL_ACTION_{name}{payload_suffix}",
            f"<tool_call>call:{name}{payload_suffix}",
            f"<tool_call>call:INTERNAL_ACTION_{name}{payload_suffix}",
            f"call:{name}{payload_suffix}",
            f"call:INTERNAL_ACTION_{name}{payload_suffix}",
            f"{name}{payload_suffix}",
            f"INTERNAL_ACTION_{name}{payload_suffix}",
        ]

        if placeholder_payload:
            candidates.extend((
                f"<{name} name=",
                f"<INTERNAL_ACTION_{name} name=",
            ))

        for marker in candidates:
            if marker not in markers:
                markers.append(marker)

    return tuple(markers)


def find_unclosed_runtime_action_start(
    text: str,
    private_marker: str,
    runtime_action: str = "",
    close_tag: bool = False,
) -> int | None:
    value = str(text or "")

    if not value:
        return None

    if close_tag:
        opening_match: re.Match[str] | None = None
        opening_end = 0

        for tag_match in compile_runtime_action_tag_regexp(
            private_marker,
            runtime_action,
        ).finditer(value):
            if tag_match.group("slash"):
                opening_match = None
                opening_end = 0
                continue

            if opening_match is None:
                opening_match = tag_match
                opening_end = tag_match.end()
                continue

            # A repeated opening tag is accepted as the closing delimiter by
            # the generic block regexp. With no payload between the tags, keep
            # the latest one as a possible fresh opening marker.
            if value[opening_end:tag_match.start()].strip():
                opening_match = None
                opening_end = 0
            else:
                opening_match = tag_match
                opening_end = tag_match.end()

        if opening_match is not None:
            return opening_match.start()

    upper_value = value.upper()
    best_start: int | None = None

    for marker in get_runtime_action_start_markers(private_marker, runtime_action):
        marker_upper = marker.upper()
        start = upper_value.rfind(marker_upper)

        if start < 0:
            continue

        if not marker.startswith("<"):
            line_start = max(
                value.rfind("\n", 0, start),
                value.rfind("\r", 0, start),
            ) + 1
            if value[line_start:start].strip():
                continue

        candidate = value[start:]

        if "\n" in candidate or "\r" in candidate:
            continue

        if marker.startswith("<|tool_call>") or marker.startswith("<tool_call>"):
            suffix = candidate[len(marker):]
            if ">" in suffix:
                continue
        elif marker.startswith("<") and ">" in candidate:
            continue

        if best_start is None or start > best_start:
            best_start = start

    return best_start
