# Formats asset action results for runtime context output.
import re

from .runtime_action_result_text import (
    format_runtime_action_result,
)
from .skills import (
    format_missing_skill_result,
)


def _format_action_result_name(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return ""

    raw_name = str(
        result.get(
            "runtime_action_name",
            "",
        )
        or result.get(
            "action",
            "",
        )
        or ""
    ).strip()

    if not raw_name:
        return ""

    name = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        raw_name,
    ).strip(
        "_"
    ).upper()
    name = re.sub(
        r"_+",
        "_",
        name,
    )

    return name


def format_asset_result_sections(
    payload,
    context=None,
) -> list[tuple[str, str]]:

    if not isinstance(
        payload,
        list,
    ):
        return [
            (
                "ASSETS",
                format_runtime_action_result(
                    payload,
                    runtime_action="ASSET_ACTION",
                ),
            ),
        ]

    sections = []
    pending_results = []
    def flush_pending_results() -> None:
        if not pending_results:
            return

        sections.append(
            (
                "ASSETS",
                "\n\n".join(
                    format_runtime_action_result(
                        result,
                        runtime_action=(
                            _format_action_result_name(result)
                            or "ASSET_ACTION"
                        ),
                    )
                    for result in pending_results
                ),
            )
        )
        pending_results.clear()

    for index, result in enumerate(
        payload,
    ):
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "load_skill"
            and result.get("ok") is False
            and result.get("error") == "skill_not_found"
        ):
            flush_pending_results()
            failure_result = dict(result)
            failure_result.setdefault(
                "detail",
                format_missing_skill_result(result),
            )
            sections.append(
                (
                    "LOAD_SKILL",
                    format_runtime_action_result(
                        failure_result,
                        runtime_action="LOAD_SKILL",
                    ),
                )
            )
            continue

        pending_results.append(
            result
        )

    flush_pending_results()

    return [
        section
        for section in sections
        if section[1]
    ]

