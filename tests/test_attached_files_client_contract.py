from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ui/templates/index.html"
DRAGDROP = ROOT / "ui/static/js/dragdrop.js"
MEMORY_VIEW = ROOT / "ui/static/js/runtime/runtime-memory-view.js"
TRACE_MODAL = ROOT / "ui/static/js/logger/trace-modal.js"
CHAT_ATTACHMENTS = ROOT / "ui/static/js/chat-attachments.js"


def test_attached_files_plaque_is_a_fixed_console_footer():
    source = INDEX.read_text(encoding="utf-8")
    console_stream = source.index('id="console-stream"')
    attached_files = source.index('id="attached-files"')
    console_end = source.index("</section>", console_stream)
    assert console_stream < attached_files < console_end
    assert "/static/js/dragdrop.js?v=console-auto-expand-2&file-restore-2&empty-files-plaque=1&unpin-logger-card=1" in source


def test_dragdrop_uses_persistent_api_and_max_five_context_files():
    source = DRAGDROP.read_text(encoding="utf-8")
    assert 'fetch("/api/files"' in source
    assert 'fetch("/api/files/upload"' in source
    assert "MAX_JIN_ATTACHMENTS = 5" in source
    assert 'type: "attachment_context_sync"' in source
    assert "await uploadQueue" in source
    assert "jin:files-store-changed" in source


def test_files_memory_panel_reuses_delayed_memory_visual_language():
    source = MEMORY_VIEW.read_text(encoding="utf-8")
    assert 'modes.push(\n          "files"' in source
    assert '"[ files ]"' in source
    assert "runtime-memory-delayed-row-pinned" in source
    assert "delayed-memory-modal-icon-button delayed-memory-modal-pin runtime-memory-delayed-pin" in source
    assert "window.openJinAttachmentModal(record)" in source


def test_context_trace_has_attached_files_pin_rows():
    source = TRACE_MODAL.read_text(encoding="utf-8")
    assert 'normalizedBlockTitle === "ATTACHED_FILES"' in source
    assert "jin-context-attached-file-pin" in source
    assert "window.JinFiles.setPinned" in source


def test_file_modal_reuses_delayed_memory_pin_delete_buttons():
    source = CHAT_ATTACHMENTS.read_text(encoding="utf-8")
    assert "attachmentModalPinButton" in source
    assert "attachmentModalDeleteButton" in source
    assert "delayed-memory-modal-delete" in source
    assert "window.JinFiles.deleteFile" in source


def test_attached_files_plaque_reuses_attachment_modal_and_100px_image_hover():
    dragdrop = DRAGDROP.read_text(encoding="utf-8")
    attachments = CHAT_ATTACHMENTS.read_text(encoding="utf-8")
    base_css = (ROOT / "ui/static/css/base.css").read_text(encoding="utf-8")
    memory_css = (ROOT / "ui/static/css/runtime-memory.css").read_text(encoding="utf-8")

    assert "bindAttachedFilesPlaqueName" in dragdrop
    assert "bindAttachedFilesPlaquePinPreview" in dragdrop
    assert "window.bindJinAttachmentBubble(element, attachment" in dragdrop
    assert "window.bindJinAttachmentHoverPreview(element, attachment" in dragdrop
    assert "hoverPreviewMaxPx: 100" in dragdrop
    assert 'pin.title = String(record.id || "")' in dragdrop
    assert 'new CustomEvent("jin:attachment-ui-ready")' in attachments
    assert "options.hoverPreviewMaxPx" in attachments
    assert "--jin-attachment-preview-max-px" in memory_css
    assert ".jin-attached-files-name.jin-attachment-bubble:hover" in base_css
    assert "background: transparent;" in base_css
    assert ".jin-attached-delayed-memory-name" in base_css

def test_files_panel_shows_square_left_panel_image_and_text_hover_cards():
    runtime_view = MEMORY_VIEW.read_text(encoding="utf-8")
    memory_css = (ROOT / "ui/static/css/runtime-memory.css").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert "const records = getPersistentFileRecords();" in runtime_view
    assert "runtimeMemoryPosition.textContent = String(records.length);" in runtime_view
    assert "bindPersistentFileHoverPreview(row, record);" in runtime_view
    assert '"runtime-memory-lt-hover-card runtime-memory-file-hover-card"' in runtime_view
    assert "positionLongTermMemoryHoverCard(" in runtime_view
    assert "window.JinFiles.resolveAttachment(record)" in runtime_view
    assert 'text.textContent =\n          inlineText || "loading...";' in runtime_view
    assert 'resolvedText || "[ empty file ]"' in runtime_view
    assert ".runtime-memory-file-hover-card {" in memory_css
    assert "--runtime-memory-file-hover-size: min(280px" in memory_css
    assert "width: var(--runtime-memory-file-hover-size);" in memory_css
    assert "height: var(--runtime-memory-file-hover-size);" in memory_css
    assert ".runtime-memory-file-hover-image {" in memory_css
    assert "object-fit: contain;" in memory_css
    assert ".runtime-memory-file-hover-text {" in memory_css
    assert "overflow: hidden;" in memory_css
    assert "white-space: pre-wrap;" in memory_css
    assert "file-preview-card=1" in index


def test_delayed_memory_modal_links_existing_files_by_original_name():
    runtime_view = MEMORY_VIEW.read_text(encoding="utf-8")
    storage = (ROOT / "ui/static/js/runtime/runtime-storage.js").read_text(encoding="utf-8")
    memory_css = (ROOT / "ui/static/css/runtime-memory.css").read_text(encoding="utf-8")

    assert "attachments_ids" in storage
    assert "appendDelayedMemoryAttachmentIdsField" in runtime_view
    assert "getDelayedMemoryAttachmentRecords" in runtime_view
    assert 'item.textContent = String(record.name || "attachment")' in runtime_view
    assert "window.bindJinAttachmentBubble(" in runtime_view
    assert "hoverPreviewMaxPx: 100" in runtime_view
    assert ".delayed-memory-modal-attachment" in memory_css
