from .active_memory_utils import (
    SHORT_RUNTIME_ID_RE,
    generate_short_runtime_id,
)


def slugify_delayed_memory_title(
    title: str,
) -> str:

    return generate_short_runtime_id()


def generate_delayed_memory_report_id(
    existing_ids=None,
) -> str:

    return generate_short_runtime_id(
        existing_ids
    )


def is_delayed_memory_report_id(
    value: str,
) -> bool:

    return bool(
        SHORT_RUNTIME_ID_RE.fullmatch(
            str(value or "").strip().casefold()
        )
    )
