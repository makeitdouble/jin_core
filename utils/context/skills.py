# Formats the always-visible skill inventory and loaded skill state.
import re
from xml.sax.saxutils import escape

from utils.brain_client_utils import indent_xml
from utils.skills_asset_utils import list_skills


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


def _loaded_skill_names(
    context=None,
) -> set[str]:

    loaded_skills = list(
        getattr(
            context,
            "runtime_loaded_skills",
            [],
        )
        or []
    )
    names = set()

    for skill in loaded_skills:
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


def format_skills_inventory(
    skills,
    context=None,
) -> str:

    loaded_names = _loaded_skill_names(
        context
    )
    lines = []

    for index, skill in enumerate(
        (
            skill
            for skill in (skills or [])
            if isinstance(skill, dict)
        ),
        start=1,
    ):
        name = str(
            skill.get(
                "name",
                "",
            )
            or ""
        ).strip() or "(unnamed skill)"

        status = (
            " (loaded)"
            if _normalize_skill_status_name(name) in loaded_names
            else ""
        )
        modes = [
            str(mode).strip()
            for mode in skill.get(
                "modes",
                [],
            )
            or []
            if str(mode).strip()
        ]
        modes_suffix = (
            f" [modes: {', '.join(modes)}]"
            if modes
            else ""
        )

        lines.append(
            f"{index}. {name}{status}{modes_suffix}"
        )

    if not lines:
        lines.append(
            "No project skills available."
        )

    return "\n".join(
        lines
    )


def build_skills_inventory_context(
    context=None,
) -> str:

    result = list_skills()
    body = format_skills_inventory(
        result.get(
            "skills",
            [],
        ),
        context,
    )

    return (
        "<SKILLS>\n"
        f"{indent_xml(escape(body), spaces=4)}\n"
        "</SKILLS>"
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
        "You attempted to load a skill that does not exist: "
        f"{requested}"
    )
