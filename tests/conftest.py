from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_default_chat_log_roots(monkeypatch, tmp_path):
    """Tests may use fake session ids, but must never write them to real logs/."""
    import runtime.LT_mention_backfill as lt_mention_backfill
    import utils.chat_log as chat_log
    import utils.session_restore as session_restore

    root = Path(tmp_path) / "default-chat-logs"

    monkeypatch.setattr(chat_log, "CHAT_LOG_ROOT", root)
    monkeypatch.setattr(session_restore, "CHAT_LOG_ROOT", root)
    monkeypatch.setattr(lt_mention_backfill, "CHAT_LOG_ROOT", root)
