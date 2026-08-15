from pathlib import Path
from types import SimpleNamespace

import utils.attached_files_store as store
from rules.brain_context_builder import build_brain_context
from utils.context.tool_results import build_tool_results_context
from utils.tool_results import TOOL_RESULT_KIND_FILES, record_runtime_tool_result
from websocket.attachments import format_attachment_context


def _redirect_store(monkeypatch, tmp_path: Path):
    files_dir = tmp_path / "assets" / "files"
    monkeypatch.setattr(store, "FILES_DIR", files_dir)
    monkeypatch.setattr(store, "INDEX_FILE", files_dir / ".index.json")
    monkeypatch.setattr(store, "GITKEEP_FILE", files_dir / ".gitkeep")
    store.ensure_files_dir()
    return files_dir


def test_persistent_file_name_and_full_content_dedupe(monkeypatch, tmp_path):
    files_dir = _redirect_store(monkeypatch, tmp_path)
    first, created, error = store.store_uploaded_file(
        name="image.png",
        content=b"same-image",
        mime_type="image/png",
        width=768,
        height=543,
    )
    assert created is True
    assert error is None
    assert len(first["id"]) == 6
    assert first["stored_name"] == f"{first['id']}_image.png"
    assert first["context_path"] == f"/assets/files/{first['id']}_image.png"
    assert (files_dir / first["stored_name"]).read_bytes() == b"same-image"

    duplicate, created, error = store.store_uploaded_file(
        name="image.png",
        content=b"same-image",
        mime_type="image/png",
    )
    assert created is False
    assert error is None
    assert duplicate["id"] == first["id"]
    assert len([path for path in files_dir.iterdir() if not path.name.startswith(".")]) == 1


def test_max_five_pinned_files_is_deterministic(monkeypatch, tmp_path):
    _redirect_store(monkeypatch, tmp_path)
    records = []
    for index in range(6):
        record, _created, error = store.store_uploaded_file(
            name=f"{index}.txt",
            content=f"content-{index}".encode(),
            mime_type="text/plain",
        )
        records.append(record)
        assert error is None

    pinned_ids = store.get_pinned_file_ids()
    assert len(pinned_ids) == 5
    assert records[0]["id"] not in pinned_ids
    assert {record["id"] for record in records[1:]} == set(pinned_ids)


def test_sixth_pin_replaces_oldest_pin_by_id_not_duplicate_title(monkeypatch, tmp_path):
    _redirect_store(monkeypatch, tmp_path)
    records = []
    for index in range(6):
        record, _created, error = store.store_uploaded_file(
            name="image.png",
            content=f"image-{index}".encode(),
            mime_type="image/png",
            pin=False,
        )
        assert error is None
        records.append(record)

    clock = iter((100.0, 200.0, 300.0, 400.0, 500.0, 600.0))
    monkeypatch.setattr(store.time, "time", lambda: next(clock))

    for index in (1, 0, 2, 3, 4):
        updated, error = store.set_file_pinned(records[index]["id"], True)
        assert updated is not None
        assert error is None

    sixth, error = store.set_file_pinned(records[5]["id"], True)
    assert sixth is not None
    assert error is None

    pinned_ids = store.get_pinned_file_ids()
    assert records[1]["id"] not in pinned_ids
    assert {
        records[0]["id"],
        records[2]["id"],
        records[3]["id"],
        records[4]["id"],
        records[5]["id"],
    } == set(pinned_ids)


def test_text_hydration_and_attachment_context_path(monkeypatch, tmp_path):
    _redirect_store(monkeypatch, tmp_path)
    record, _created, _error = store.store_uploaded_file(
        name="Новый текстовый документ.txt",
        content="hello utf8".encode("utf-8"),
        mime_type="text/plain",
    )
    attachment = store.hydrate_attachment_ids([record["id"]])[0]
    assert attachment["text_content"] == "hello utf8"

    context = format_attachment_context({"attachments": [attachment]})
    assert f"/assets/files/{record['id']}_Новый текстовый документ.txt" in context
    assert f"[ id: {record['id']} ]" in context
    assert "BEGIN ATTACHMENT TEXT" in context
    assert "hello utf8" in context


def test_attached_files_context_sits_between_tools_and_delayed(monkeypatch, tmp_path):
    _redirect_store(monkeypatch, tmp_path)
    record, _created, _error = store.store_uploaded_file(
        name="note.txt",
        content=b"note",
        mime_type="text/plain",
    )
    context = SimpleNamespace(
        runtime_attached_file_ids=[record["id"]],
        delayed_memory_reports={
            "abc123": {"id": "abc123", "title": "Delayed", "summary": "Summary"}
        },
        runtime_tool_results=[],
        runtime_tool_result_created_ats=[],
    )

    prompt = build_brain_context(
        context,
        runtime_actions={},
        include_runtime_action_instructions=False,
        include_previous_chat_messages=False,
        include_previous_reasoning=False,
    )
    assert "<ATTACHED_FILES>" in prompt
    assert f"note.txt [ id: {record['id']} ]" in prompt
    assert prompt.index("<TOOLS_RESULTS") < prompt.index("<ATTACHED_FILES>")
    assert prompt.index("<ATTACHED_FILES>") < prompt.index("<DELAYED_MEMORY>")


def test_list_files_tool_result_format(monkeypatch, tmp_path):
    _redirect_store(monkeypatch, tmp_path)
    record, _created, _error = store.store_uploaded_file(
        name="image.png",
        content=b"image",
        mime_type="image/png",
        width=768,
        height=543,
    )
    context = SimpleNamespace()
    lines = store.format_list_files_lines([record])
    record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_FILES,
        {"action": "list_files", "ok": True, "files": [record], "lines": lines},
    )
    rendered = build_tool_results_context(context)
    assert 'name="LIST_FILES"' in rendered
    assert "1. image.png" in rendered
    assert "768x543" in rendered
    assert f"[ id: {record['id']} ]" in rendered
