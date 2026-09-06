"""Backend-owned episode identities shared by L-T ingestion and recall."""
from __future__ import annotations

import re

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")


def normalize_sources(value) -> list[dict]:
    result = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        session = str(item.get("session_id") or "").strip()
        snapshot = str(item.get("runtime_snapshot_id") or "").strip()
        turn = str(item.get("turn_id") or "").strip()
        if (not _SAFE_ID.fullmatch(session)
                or not ((snapshot and _SAFE_ID.fullmatch(snapshot))
                        or (not snapshot and _SAFE_ID.fullmatch(turn)))):
            continue
        identity = (session, snapshot, "" if snapshot else turn)
        if identity not in seen:
            seen.add(identity)
            # FRAME is an episode; exact turn anchors come only from its archive.
            result.append({"session_id": session, **(
                {"runtime_snapshot_id": snapshot} if snapshot else {"turn_id": turn}
            )})
    return result


def merge_sources(*values) -> list[dict]:
    return normalize_sources([item for value in values if isinstance(value, list) for item in value])


def source_key(source: dict) -> str:
    return source["session_id"] + "/" + (source.get("runtime_snapshot_id") or "turn:" + source["turn_id"])
