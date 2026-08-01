# Formats appended skill state and skill listing results for runtime context output.
import re

from rules.runtime import (
    NO_ENTRIES_FOUND_MESSAGE,
)


def _normalize_skill_status_name(
    name,
) -> str:

    normalized = str(
        name
        or ""
    ).strip()

    if normalized.lower().endswith(
        ".txt"
    ):
        normalized = normalized[:-4]

    normalized = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        normalized,
    ).strip(
        "_"
    ).lower()

    return re.sub(
        r"_+",
        "_",
        normalized,
    )


def _appended_skill_names(
    context=None,
) -> set[str]:

    appended_skills = list(
        getattr(
            context,
            "runtime_appended_skills",
            [],
        )
        or []
    )
    names = set()

    for skill in appended_skills:
        if isinstance(
            skill,
            dict,
        ):
            raw_name = skill.get(
                "name",
                "",
            )
        else:
            raw_name = skill

        name = _normalize_skill_status_name(
            raw_name
        )
        if name:
            names.add(
                name
            )

    return names


def format_list_skills_result(
    result: dict,
    context=None,
) -> str:

    lines = []

    skills = [
        skill
        for skill in result.get(
            "skills",
            [],
        )
        or []
        if isinstance(
            skill,
            dict,
        )
    ]

    if not skills:
        lines.append(
            NO_ENTRIES_FOUND_MESSAGE
        )
        return "\n".join(
            lines
        )

    appended_names = _appended_skill_names(
        context
    )

    for index, skill in enumerate(
        skills,
        start=1,
    ):
        name = str(
            skill.get(
                "name",
                "",
            )
            or ""
        ).strip()

        if not name:
            name = "(unnamed skill)"

        status = ""
        if _normalize_skill_status_name(
            name
        ) in appended_names:
            status = " (appended)"

        path = str(
            skill.get(
                "path",
                "",
            )
            or ""
        ).strip()
        path_suffix = (
            f" - {path}"
            if path
            else ""
        )

        lines.append(
            f"{index}. {name}{status}{path_suffix}"
        )

    return "\n".join(
        lines
    )


def format_missing_skill_result(
    result: dict,
) -> str:

    requested = str(
        result.get(
            "requested",
            "",
        )
        or ""
    ).strip()

    if not requested:
        requested = "unknown"

    return (
        "You attempted to append a skill that does not exist: "
        f"{requested}"
    )

