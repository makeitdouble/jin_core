"""Browser origin boundary for the chat transport."""

from urllib.parse import urlsplit


def _origin_tuple(value):
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or "?" in value
            or "#" in value
            or "\\" in value
            or parsed.netloc.endswith(":")
        ):
            return None
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname, port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def has_same_origin(websocket):
    """Require one HTTP(S) Origin matching the actual handshake scheme/Host.

    Missing/null origins fail closed. Forwarded headers are not an allowlist;
    any proxy scheme handling belongs to the server's trusted proxy setup.
    """
    origins = websocket.headers.getlist("origin")
    hosts = websocket.headers.getlist("host")
    if len(origins) != 1 or len(hosts) != 1:
        return False
    scheme = {"ws": "http", "wss": "https", "http": "http", "https": "https"}.get(websocket.scope.get("scheme"))
    if scheme is None:
        return False
    origin = _origin_tuple(origins[0])
    expected = _origin_tuple(f"{scheme}://{hosts[0]}")
    return origin is not None and expected is not None and origin == expected
