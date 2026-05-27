import httpx


def format_client_error(stage: str, url: str, model: str, error: Exception) -> str:
    """
    Format HTTP and system errors as a readable multiline block.
    """
    lines = [
        f"stage   : {stage}",
        f"model   : {model}",
        f"url     : {url}",
        f"type    : {type(error).__name__}",
    ]

    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        lines.append(f"status  : {response.status_code}")

        try:
            response_data = response.json()
        except ValueError:
            response_data = None

        error_data = {}

        if isinstance(response_data, dict):
            raw_error_data = response_data.get(
                "error",
                {},
            )

            if isinstance(raw_error_data, dict):
                error_data = raw_error_data

        if error_data:
            if message := error_data.get("message"):
                lines.append(f"message : {message}")

            if api_type := error_data.get("type"):
                lines.append(f"api     : {api_type}")

            if code := error_data.get("code"):
                lines.append(f"code    : {code}")

        else:
            body = response.text.strip()
            body_text = f"{body[:300]}..." if len(body) > 300 else body
            lines.append(f"body    : {body_text}")

    else:
        lines.append(f"error   : {str(error)}")

    return "\n".join(lines)
