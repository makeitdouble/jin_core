import re


TOOLS_RESULTS_BLOCK_RE = re.compile(
    r"<TOOLS_RESULTS(?:\s[^>]*)?>\s*(.*?)\s*</TOOLS_RESULTS>",
    re.IGNORECASE | re.DOTALL,
)
TOOL_RESULTS_BLOCK_RE = re.compile(
    r"<TOOL_RESULTS(?:\s[^>]*)?>.*?</TOOL_RESULTS>",
    re.IGNORECASE | re.DOTALL,
)
IDLE_TOOL_RESULTS_RE = re.compile(
    r"<TOOL_RESULTS\b[^>]*\btype\s*=\s*['\"]idle['\"][^>]*>",
    re.IGNORECASE,
)
TOOLS_RESULTS_CONTEXT_RE = re.compile(
    r"<TOOLS_RESULTS(?:\s[^>]*)?>.*?</TOOLS_RESULTS>"
    r"|<TOOL_RESULTS(?:\s[^>]*)?>.*?</TOOL_RESULTS>",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_spacing(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    return re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )


def split_tools_results_context(
    text: str,
) -> tuple[list[str], str]:
    """Extract every TOOL_RESULTS block and return the remaining context."""

    source = str(text or "")
    blocks: list[str] = []

    def remove_context(match: re.Match) -> str:
        matched = match.group(0).strip()
        if matched.upper().startswith(
            "<TOOLS_RESULTS"
        ):
            blocks.extend(
                block.strip()
                for block in TOOL_RESULTS_BLOCK_RE.findall(
                    matched
                )
                if block.strip()
            )
        elif matched:
            blocks.append(
                matched
            )
        return ""

    remainder = TOOLS_RESULTS_CONTEXT_RE.sub(
        remove_context,
        source,
    )

    unique_blocks: list[str] = []
    seen = set()
    for block in blocks:
        normalized = block.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_blocks.append(normalized)

    return unique_blocks, _normalize_spacing(remainder)


def build_tools_results_context(
    blocks=None,
) -> str:
    normalized_blocks = [
        str(block or "").strip()
        for block in (blocks or [])
        if str(block or "").strip()
    ]

    if not normalized_blocks:
        return "<TOOLS_RESULTS>\n</TOOLS_RESULTS>"

    return (
        "<TOOLS_RESULTS>\n"
        + "\n".join(normalized_blocks)
        + "\n</TOOLS_RESULTS>"
    )


def strip_tools_results_context(
    text: str,
) -> str:
    _, remainder = split_tools_results_context(
        text
    )
    return remainder


def is_idle_tool_results_block(
    block: str,
) -> bool:
    return bool(
        IDLE_TOOL_RESULTS_RE.search(
            str(block or "")
        )
    )
