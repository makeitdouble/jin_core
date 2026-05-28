from urllib.parse import urlparse

import httpx


SERPER_SEARCH_URL = "https://google.serper.dev/search"


def extract_source(
    url: str,
) -> str:

    host = (
        urlparse(
            url or ""
        )
        .netloc
    )

    return host.removeprefix(
        "www."
    )


def normalize_serper_item(
    item: dict,
) -> dict:

    link = (
        item.get(
            "link",
            "",
        )
        or ""
    )

    snippet = (
        item.get(
            "snippet",
            "",
        )
        or ""
    )

    return {
        "title": (
            item.get(
                "title",
                "",
            )
            or ""
        ),
        "source": extract_source(
            link
        ),
        "url": link,
        "quote": snippet,
        "excerpt": snippet,
    }


async def serper_search(
    *,
    query: str,
    api_key: str,
    num_results: int,
    timeout: float,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict]:

    payload = {
        "q": query,
        "num": num_results,
    }
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    if http_client is not None:
        response = await http_client.post(
            SERPER_SEARCH_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

    else:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SERPER_SEARCH_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

    return [
        normalize_serper_item(
            item
        )
        for item in data.get(
            "organic",
            [],
        )
    ]
