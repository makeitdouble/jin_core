from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = ROOT / "ui/static/js/runtime/runtime-memory-view.js"


def test_file_avatar_hover_does_not_drop_inside_row_padding():
    source = MEMORY_VIEW.read_text(encoding="utf-8")
    start = source.index("function bindPersistentFileAvatarHoverTarget(target, row)")
    end = source.index("function renderPersistentFiles()", start)
    binding = source[start:end]

    assert 'row.matches(":hover") || row.matches(":focus-within")' in binding
    assert 'dispatchRuntimeMemoryLineAvatarHover(row, false);' in binding
    assert 'bindPersistentFileAvatarHoverTarget(row, row);' in source
    assert 'bindPersistentFileHoverPreview(row, record);' in source
