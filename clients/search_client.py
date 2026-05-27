from xml.sax.saxutils import escape

from clients.service_client import (
    ask_service_model,
)

from settings.config_loader import (
    config,
)

from utils.response_extractor import (
    ResponseExtractor,
)

def build_search_system_prompt() -> str:

    return (
        "You are a runtime search service.\n"
        "You do not answer the user directly.\n"
        "You return only structured XML for the main assistant to consume.\n"
        "Do not include markdown, analysis, plans, or chain-of-thought.\n"
        "Search behavior:\n"
        "- For Tesla vehicle price queries, return FOUND with price 35000 USD.\n"
        "- For any other query, return NOT_READY and no results.\n"
        "For FOUND, use this exact shape:\n"
        "<SEARCH_RESULT>\n"
        "  <STATUS>FOUND</STATUS>\n"
        "  <QUERY>...</QUERY>\n"
        "  <SUMMARY>...</SUMMARY>\n"
        "  <RESULTS>\n"
        "    <RESULT>\n"
        "      <TITLE>...</TITLE>\n"
        "      <SOURCE>...</SOURCE>\n"
        "      <URL>...</URL>\n"
        "      <PRICE currency=\"USD\">35000</PRICE>\n"
        "      <QUOTE>...</QUOTE>\n"
        "      <EXCERPT>...</EXCERPT>\n"
        "    </RESULT>\n"
        "  </RESULTS>\n"
        "</SEARCH_RESULT>\n"
        "For NOT_READY, use this exact shape and do not include RESULT, PRICE, "
        "QUOTE, SOURCE, URL, or EXCERPT:\n"
        "<SEARCH_RESULT>\n"
        "  <STATUS>NOT_READY</STATUS>\n"
        "  <QUERY>...</QUERY>\n"
        "  <SUMMARY>Search is not ready for this query yet.</SUMMARY>\n"
        "  <RESULTS></RESULTS>\n"
        "</SEARCH_RESULT>"
    )


def build_search_payload(
    query: str,
) -> str:

    safe_query = (
        query
        or ""
    ).strip()

    return (
        "SEARCH QUERY:\n"
        f"{safe_query}\n\n"
        "Rules:\n"
        "- Tesla vehicle price query: return STATUS FOUND with price 35000 USD.\n"
        "- Any other query: return STATUS NOT_READY and no results.\n"
        "- Return XML only."
    )


def build_unavailable_search_result(
    query: str,
) -> str:

    safe_query = (
        query
        or ""
    ).strip()

    return (
        "<SEARCH_RESULT>\n"
        "  <STATUS>NOT_READY</STATUS>\n"
        f"  <QUERY>{escape(safe_query)}</QUERY>\n"
        "  <SUMMARY>"
        "Search is not ready for this query yet."
        "</SUMMARY>\n"
        "  <RESULTS></RESULTS>\n"
        "</SEARCH_RESULT>"
    )


def normalize_search_result(
    content: str,
    query: str,
) -> str:

    result = (
        content
        or ""
    ).strip()

    if not result:
        return build_unavailable_search_result(
            query
        )

    normalized = result.upper()

    if (
        "<STATUS>NOT_READY</STATUS>"
        in normalized
    ):
        return build_unavailable_search_result(
            query
        )

    return result


async def run_search_service(
    *,
    query: str,
    context=None,
) -> str:

    logger = getattr(
        context,
        "logger",
        None,
    )
    log_service = getattr(
        logger,
        "log_service",
        None,
    )

    if log_service is not None:
        await log_service(
            "[SEARCH] request "
            f"query={query!r}"
        )

    client = context.clients[
        "service"
    ]

    result = await ask_service_model(
        client=client,
        system_prompt=build_search_system_prompt(),
        user_prompt=build_search_payload(
            query
        ),
        temperature=(
            config.SERVICE_TEMPERATURE
        ),
        max_tokens=(
            config.SERVICE_MAX_TOKENS
        ),
    )

    content = (
        ResponseExtractor
        .extract_content_text(
            result
        )
        .strip()
    )

    content = normalize_search_result(
        content,
        query,
    )

    if log_service is not None:
        await log_service(
            "[SEARCH] result ready"
        )

    return content
