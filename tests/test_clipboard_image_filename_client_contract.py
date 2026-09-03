from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRAGDROP = ROOT / "ui/static/js/dragdrop.js"


def test_default_clipboard_image_name_gets_local_date_and_time_suffix():
    source = DRAGDROP.read_text(encoding="utf-8")

    assert "function formatClipboardImageTimestamp(date)" in source
    assert 'if (name !== "image.png" || !mimeType.startsWith("image/")) return "";' in source
    assert 'return `image_${formatClipboardImageTimestamp(pastedAt)}.png`;' in source
    assert 'if (files.length) addFiles(files, {pastedAt: new Date()});' in source
    assert 'body.append("file", file, uploadName || file.name || "attachment");' in source
