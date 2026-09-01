from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"


def test_trace_modal_backdrop_close_requires_pointerdown_on_backdrop():
    source = TRACE_MODAL_JS.read_text(encoding="utf-8")

    assert "let traceModalBackdropPointerDown = false;" in source
    assert '"pointerdown",' in source
    assert "event.target === traceModal;" in source
    assert (
        "event.target === traceModal\n"
        "        && traceModalBackdropPointerDown;"
    ) in source
    assert "traceModalBackdropPointerDown = false;" in source
