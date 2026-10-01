from datetime import datetime, timezone


def format_utc_iso(value: datetime) -> str:
    """Return a second-precision, timezone-aware UTC ISO timestamp."""

    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return (
        timestamp.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_now_iso() -> str:
    return format_utc_iso(datetime.now(timezone.utc))
