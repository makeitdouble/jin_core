import json
import re
from pathlib import Path


PENDING_FRAME_DIR = (
    Path(__file__).resolve().parents[1]
    / "memory"
    / "frame"
)
PENDING_FRAME_SESSION_RE = re.compile(
    r"[^a-zA-Z0-9_.-]"
)


def migrate_legacy_runtime_journal(
        memory_root=None,
) -> dict:
    """Move live FRAME checkpoints out of the retired memory/runtime folder.

    Old ``*.l1_pending.json`` files are obsolete extraction queues and can be
    discarded. ``*.frame_pending.json`` remains crash-recovery state, so keep
    the newest copy when a destination already exists. Unknown files are left
    alone instead of being deleted blindly.
    """

    root = Path(memory_root) if memory_root is not None else PENDING_FRAME_DIR.parent
    legacy_dir = root / "runtime"
    frame_dir = root / "frame"
    stats = {
        "moved_frame": 0,
        "removed_l1": 0,
        "removed_temp": 0,
        "removed_runtime_dir": False,
    }

    if not legacy_dir.is_dir():
        return stats

    for source in legacy_dir.glob("*.frame_pending.json"):
        target = frame_dir / source.name
        try:
            frame_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                try:
                    source_is_newer = source.stat().st_mtime_ns > target.stat().st_mtime_ns
                except OSError:
                    source_is_newer = False
                if source_is_newer:
                    source.replace(target)
                else:
                    source.unlink()
            else:
                source.replace(target)
            stats["moved_frame"] += 1
        except OSError:
            # A failed migration must never destroy the only recovery copy.
            continue

    for pattern, stat_key in (
        ("*.l1_pending.json", "removed_l1"),
        ("*.tmp", "removed_temp"),
    ):
        for path in legacy_dir.glob(pattern):
            try:
                path.unlink()
                stats[stat_key] += 1
            except OSError:
                continue

    gitkeep = legacy_dir / ".gitkeep"
    try:
        gitkeep.unlink()
    except (FileNotFoundError, OSError):
        pass

    try:
        legacy_dir.rmdir()
        stats["removed_runtime_dir"] = True
    except OSError:
        # Preserve an unknown file rather than treating memory/runtime as a
        # disposable directory.
        pass

    return stats


def _pending_frame_path(
        context,
) -> Path | None:

    # Anonymous rooms are browser-ephemeral. They must never create or read a
    # crash-recovery journal under memory/frame.
    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        return None

    session_id = PENDING_FRAME_SESSION_RE.sub(
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

    return PENDING_FRAME_DIR / f"{session_id}.frame_pending.json"


def _pending_turns(
        context,
) -> list[dict]:

    return [
        {
            "turn_id": str(turn.get("turn_id") or ""),
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


def persist_pending_frame_update(
        context,
) -> bool:

    path = _pending_frame_path(
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


def restore_pending_frame_update(
        context,
) -> bool:

    path = _pending_frame_path(
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
            "turn_id": str(turn.get("turn_id") or ""),
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
        clear_pending_frame_update(
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


def clear_pending_frame_update(
        context,
) -> bool:

    path = _pending_frame_path(
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
