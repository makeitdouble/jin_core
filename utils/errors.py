import httpx


def format_client_error(stage: str, url: str, model: str, error: Exception) -> str:
    """
    Форматирует HTTP и системные ошибки в читаемый многострочный блок.
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
            error_data = response.json().get("error", {})

            if message := error_data.get("message"):
                lines.append(f"message : {message}")

            if api_type := error_data.get("type"):
                lines.append(f"api     : {api_type}")

            if code := error_data.get("code"):
                lines.append(f"code    : {code}")

        except Exception:
            body = response.text.strip()
            body_text = f"{body[:300]}..." if len(body) > 300 else body
            lines.append(f"body    : {body_text}")

    else:
        lines.append(f"error   : {str(error)}")

    return "\n".join(lines)
