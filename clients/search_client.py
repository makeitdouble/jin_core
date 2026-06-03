from xml.etree import ElementTree
from xml.sax.saxutils import escape

import httpx

from app_settings import (
    settings,
)

from clients.search_provider import (
    serper_search,
)


def format_search_provider_error(
    error: Exception,
) -> str:

    if isinstance(
        error,
        httpx.HTTPStatusError,
    ):
        return (
            "HTTP "
            f"{error.response.status_code} "
            "from search provider"
        )

    return repr(
        error
    )


def build_empty_search_result(
    query: str,
) -> str:

    safe_query = (
        query
        or ""
    ).strip()

    return (
        "<SEARCH_RESULT>\n"
        "  <STATUS>NOT_FOUND</STATUS>\n"
        f"  <QUERY>{escape(safe_query)}</QUERY>\n"
        "  <SUMMARY>No search results found.</SUMMARY>\n"
        "  <RESULTS></RESULTS>\n"
        "</SEARCH_RESULT>"
    )


def build_failed_search_result(
    query: str,
) -> str:

    safe_query = (
        query
        or ""
    ).strip()

    return (
        "<SEARCH_RESULT>\n"
        "  <STATUS>FAILED</STATUS>\n"
        f"  <QUERY>{escape(safe_query)}</QUERY>\n"
        "  <SUMMARY>"
        "Search failed: provider error."
        "</SUMMARY>\n"
        "  <RESULTS></RESULTS>\n"
        "</SEARCH_RESULT>"
    )


def build_found_search_result(
    *,
    query: str,
    results: list[dict],
) -> str:

    safe_query = (
        query
        or ""
    ).strip()

    result_xml = []

    for item in results:
        title = escape(
            str(
                item.get(
                    "title",
                    "",
                )
                or ""
            )
        )
        source = escape(
            str(
                item.get(
                    "source",
                    "",
                )
                or ""
            )
        )
        url = escape(
            str(
                item.get(
                    "url",
                    "",
                )
                or ""
            )
        )
        quote = escape(
            str(
                item.get(
                    "quote",
                    "",
                )
                or ""
            )
        )
        excerpt = escape(
            str(
                item.get(
                    "excerpt",
                    "",
                )
                or ""
            )
        )

        result_xml.append(
            "    <RESULT>\n"
            f"      <TITLE>{title}</TITLE>\n"
            f"      <SOURCE>{source}</SOURCE>\n"
            f"      <URL>{url}</URL>\n"
            f"      <QUOTE>{quote}</QUOTE>\n"
            f"      <EXCERPT>{excerpt}</EXCERPT>\n"
            "    </RESULT>"
        )

    summary = (
        f"Found {len(results)} search result"
        f"{'' if len(results) == 1 else 's'}."
    )

    return (
        "<SEARCH_RESULT>\n"
        "  <STATUS>FOUND</STATUS>\n"
        f"  <QUERY>{escape(safe_query)}</QUERY>\n"
        f"  <SUMMARY>{escape(summary)}</SUMMARY>\n"
        "  <RESULTS>\n"
        f"{chr(10).join(result_xml)}\n"
        "  </RESULTS>\n"
        "</SEARCH_RESULT>"
    )


def normalize_search_results(
    results: list[dict],
    query: str,
) -> str:

    if not results:
        return build_empty_search_result(
            query
        )

    return build_found_search_result(
        query=query,
        results=results,
    )


def get_xml_text(
    element,
    tag: str,
) -> str:

    child = element.find(
        tag
    )

    if child is None:
        return ""

    return (
        child.text
        or ""
    ).strip()


def build_search_result_fallback_answer(
    search_result: str,
) -> str:

    source = (
        search_result
        or ""
    ).strip()

    if not source:
        return ""

    try:
        root = ElementTree.fromstring(
            source
        )

    except ElementTree.ParseError:
        return ""

    status = get_xml_text(
        root,
        "STATUS",
    )
    summary = get_xml_text(
        root,
        "SUMMARY",
    )

    if status != "FOUND":
        return summary

    lines = [
        summary
        or "Search results found.",
    ]

    result_items = root.findall(
        "./RESULTS/RESULT"
    )

    for item in result_items[:3]:
        title = get_xml_text(
            item,
            "TITLE",
        )
        source_name = get_xml_text(
            item,
            "SOURCE",
        )
        url = get_xml_text(
            item,
            "URL",
        )
        quote = get_xml_text(
            item,
            "QUOTE",
        )

        heading = title

        if source_name:
            heading = (
                f"{heading} ({source_name})"
                if heading
                else source_name
            )

        if heading:
            lines.append(
                f"- {heading}"
            )

        if quote:
            lines.append(
                f"  {quote}"
            )

        if url:
            lines.append(
                f"  {url}"
            )

    return "\n".join(
        lines
    )


async def run_search_provider(
    *,
    query: str,
    context=None,
) -> list[dict]:

    injected_provider = getattr(
        context,
        "search_provider",
        None,
    )

    if injected_provider is not None:
        return await injected_provider(
            query
        )

    provider = (
        settings.SEARCH_PROVIDER
        or ""
    ).lower()

    if provider != "serper":
        raise RuntimeError(
            f"Unsupported search provider: {settings.SEARCH_PROVIDER}"
        )

    if not settings.SEARCH_SERPER_API_KEY:
        raise RuntimeError(
            "Serper search is not configured"
        )

    http_client = None
    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
        if context is not None
        else None
    )

    if service_client is not None:
        http_client = getattr(
            service_client,
            "client",
            None,
        )

    return await serper_search(
        query=query,
        api_key=settings.SEARCH_SERPER_API_KEY,
        num_results=settings.SEARCH_MAX_RESULTS,
        timeout=settings.SEARCH_TIMEOUT,
        http_client=http_client,
    )


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

    try:
        results = await run_search_provider(
            context=context,
            query=query,
        )

        content = normalize_search_results(
            results,
            query,
        )

    except Exception as error:
        log_error = getattr(
            logger,
            "log_error",
            None,
        )

        if log_error is not None:
            await log_error(
                "[SEARCH] provider error",
                details=format_search_provider_error(
                    error
                ),
            )

        content = build_failed_search_result(
            query
        )

    if log_service is not None:
        await log_service(
            "[SEARCH] result ready"
        )

    return content
