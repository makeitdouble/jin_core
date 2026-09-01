import json
import re
from pathlib import Path


PENDING_L1_DIR = (
    Path(__file__).resolve().parents[1]
    / "memory"
    / "runtime"
)
PENDING_L1_SESSION_RE = re.compile(
    r"[^a-zA-Z0-9_.-]"
)


def _pending_l1_path(
        context,
) -> Path | None:

    # Anonymous rooms are browser-ephemeral. They must never create or read a
    # crash-recovery journal under memory/runtime.
    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        return None

    session_id = PENDING_L1_SESSION_RE.sub(
        "_",
        str(
            getattr(
                context,
                "session_id",
                "",
            )
            or ""
        ).strip(),
    ).strip(
        "._-"
    )[:80]

    if not session_id:
        return None

    return PENDING_L1_DIR / f"{session_id}.l1_pending.json"


def _pending_turns(
        context,
) -> list[dict]:

    return [
        {
            "user_message": str(
                turn.get("user_message", "")
                or ""
            ),
            "assistant_message": str(
                turn.get("assistant_message", "")
                or ""
            ),
        }
        for turn in getattr(
            context,
            "runtime_memory_pending_turns",
            [],
        )
        or []
        if (
            isinstance(turn, dict)
            and str(
                turn.get("user_message", "")
                or ""
            ).strip()
        )
    ]


def persist_pending_l1_update(
        context,
) -> bool:

    path = _pending_l1_path(
        context
    )
    turns = _pending_turns(
        context
    )

    if path is None or not turns:
        return False

    try:
        base_updates = int(
            getattr(
                context,
                "runtime_memory_pending_base_updates",
                getattr(
                    context,
                    "runtime_memory_updates",
                    0,
                ),
            )
            or 0
        )
    except (TypeError, ValueError):
        base_updates = 0

    payload = {
        "base_runtime_memory_updates": max(
            0,
            base_updates,
        ),
        "turns": turns,
    }

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temp_path = path.with_name(
            path.name + ".tmp"
        )
        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(
            path
        )
    except OSError:
        return False

    return True


def restore_pending_l1_update(
        context,
) -> bool:

    path = _pending_l1_path(
        context
    )

    if path is None or not path.is_file():
        return False

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return False

    if not isinstance(payload, dict):
        return False

    turns = payload.get(
        "turns",
        [],
    )
    if not isinstance(turns, list):
        return False

    context.runtime_memory_pending_turns = [
        {
            "user_message": str(
                turn.get("user_message", "")
                or ""
            ),
            "assistant_message": str(
                turn.get("assistant_message", "")
                or ""
            ),
        }
        for turn in turns
        if (
            isinstance(turn, dict)
            and str(
                turn.get("user_message", "")
                or ""
            ).strip()
        )
    ]

    if not context.runtime_memory_pending_turns:
        clear_pending_l1_update(
            context
        )
        return False

    try:
        context.runtime_memory_pending_base_updates = max(
            0,
            int(
                payload.get(
                    "base_runtime_memory_updates",
                    0,
                )
                or 0
            ),
        )
    except (TypeError, ValueError):
        context.runtime_memory_pending_base_updates = 0

    return True


def clear_pending_l1_update(
        context,
) -> bool:

    path = _pending_l1_path(
        context
    )

    if path is None:
        return False

    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False

    return True
