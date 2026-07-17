# Provides shared payload formatting helpers for context tool result sections.
import json
import re


def format_tool_result_payload(
    payload,
) -> str:

    formatted = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )

    lines = []

    for line in formatted.splitlines():
        indent = re.match(
            r"\s*",
            line,
        ).group(0)
        lines.append(
            line.replace(
                "\\n",
                "\n"
                + indent
                + "    ",
            )
        )

    return "\n".join(
        lines
    )
