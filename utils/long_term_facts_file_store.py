from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from runtime.LT_memory_utils import (
    normalize_lt_store,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_FACTS_ROOT = PROJECT_ROOT / "memory" / "facts"
LONG_TERM_FACTS_FILENAME = "long_term_facts.json"


def get_long_term_facts_path(
    *,
    root: Path | str = LONG_TERM_FACTS_ROOT,
) -> Path:

    return Path(root) / LONG_TERM_FACTS_FILENAME


def load_long_term_facts_store(
    *,
    root: Path | str = LONG_TERM_FACTS_ROOT,
) -> tuple[dict, list[str]]:

    path = get_long_term_facts_path(
        root=root,
    )

    if not path.exists():
        return normalize_lt_store({}), []

    try:
        raw_value = json.loads(
            path.read_text(
                encoding="utf-8-sig",
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return normalize_lt_store({}), [
            f"cannot load {path.name}: {error}",
        ]

    normalized = normalize_lt_store(
        raw_value,
    )

    # Persist one-way ID/schema migrations immediately so the file store never
    # oscillates between legacy hash IDs and compact F/PF IDs across restarts.
    if normalized != raw_value:
        try:
            persist_long_term_facts_store(
                normalized,
                root=root,
            )
        except OSError as error:
            return normalized, [
                f"cannot persist migrated {path.name}: {error}",
            ]

    return normalized, []


def persist_long_term_facts_store(
    store,
    *,
    root: Path | str = LONG_TERM_FACTS_ROOT,
) -> Path:

    root_path = Path(root)
    destination = get_long_term_facts_path(
        root=root_path,
    )
    payload = normalize_lt_store(
        store,
    )

    root_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    temporary_name = ""

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".long_term_facts_",
            suffix=".tmp",
            dir=root_path,
            delete=False,
        ) as temporary_file:
            temporary_file.write(
                serialized,
            )
            temporary_file.flush()
            os.fsync(
                temporary_file.fileno(),
            )
            temporary_name = temporary_file.name

        os.replace(
            temporary_name,
            destination,
        )
    finally:
        if temporary_name:
            temporary_path = Path(
                temporary_name,
            )
            if temporary_path.exists():
                temporary_path.unlink()

    for candidate in root_path.glob(
        "*.json",
    ):
        if candidate == destination or candidate.name.startswith("."):
            continue

        try:
            candidate.unlink()
        except OSError:
            pass

    return destination
