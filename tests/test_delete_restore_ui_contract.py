from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = ROOT / "ui/static/js/runtime/runtime-memory-view.js"
DRAGDROP = ROOT / "ui/static/js/dragdrop.js"
CHAT_ATTACHMENTS = ROOT / "ui/static/js/chat-attachments.js"
LOG_ENTRIES = ROOT / "ui/static/js/logger/log-entries.js"
LT_MEMORY = ROOT / "ui/static/js/runtime/runtime-lt-memory.js"


def test_files_and_delayed_rows_share_hold_delete_open_behavior():
    source = MEMORY_VIEW.read_text(encoding="utf-8")

    assert "function configureOpenableMemoryRowHoldDelete(" in source
    assert "keepHiddenOnComplete: true" in source
    assert 'row.dataset.runtimeMemoryHoldDeleted = "true"' in source
    assert "return window.JinFiles.deleteFile(record.id);" in source
    assert "return deleteDelayedMemoryReport(" in source
    assert "configureDeleteHold: configureRuntimeMemoryDeleteHold" in source


def test_file_delete_keeps_browser_restore_payload_and_logs_restore_card():
    dragdrop = DRAGDROP.read_text(encoding="utf-8")
    logger = LOG_ENTRIES.read_text(encoding="utf-8")

    assert "const deletedFileRestoreCache = new Map();" in dragdrop
    assert "const blob = await backupResponse.blob();" in dragdrop
    assert '"[MEMORY:FILES:DELETED]"' in dragdrop
    assert "async function restoreDeletedFile(id)" in dragdrop
    assert "/restore`" in dragdrop
    assert "restoreDeletedFile," in dragdrop

    assert "function handleDeletedFileLog(" in logger
    assert '=== "file_deleted"' in logger
    assert "api.restoreDeletedFile(" in logger


def test_file_modal_delete_uses_same_hold_gesture():
    source = CHAT_ATTACHMENTS.read_text(encoding="utf-8")

    assert 'attachmentModalDeleteButton.title = "Hold to delete file";' in source
    assert "window.JinRuntime.memoryView.configureDeleteHold(" in source
    assert "deleteActiveAttachment" in source


def test_lt_restore_button_resolves_current_socket_after_reconnect():
    source = LT_MEMORY.read_text(encoding="utf-8")

    assert 'typeof window.sendSocketMessage !== "function"' in source
    assert "return window.sendSocketMessage(payload);" in source
    assert 'type: "lt_memory_restore_fact"' in source
