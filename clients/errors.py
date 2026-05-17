import httpx


def format_client_error(stage: str, url: str, model: str, error: Exception) -> str:
    parts = [
        f"stage={stage}",
        f"type={type(error).__name__}",
        f"url={url}",
        f"model={model}",
        f"error={repr(error)}",
    ]

    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        parts.append(f"status={response.status_code}")
        parts.append(f"body={response.text[:500]}")

    return "; ".join(parts)
