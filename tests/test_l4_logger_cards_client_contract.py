from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOG_ENTRIES_JS = ROOT / "ui" / "static" / "js" / "logger" / "log-entries.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"
RUNTIME_L4_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-l4-memory.js"
SOCKET_EVENTS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class L4LoggerCardsClientContractTests(unittest.TestCase):

    def test_deleted_fact_card_exposes_full_payload_and_restore(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:L4:DELETED]"', source)
        self.assertIn('kind: "l4_fact"', source)
        self.assertIn('"payload"', source)
        self.assertIn('"restore"', source)
        self.assertIn('api.requestFactRestore(', source)
        self.assertIn('window.handleL4LoggerMemoryRestoreResult', source)
        self.assertIn('window.handleL4MemoryRestoreResult', source)
        self.assertIn('resolveDeletedL4FactNumber(fact)', source)
        self.assertIn('`${factNumber} · ${factTitle}`', source)

    def test_deleted_delayed_memory_card_exposes_payload_and_restore(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:DELAYED:DELETED]"', source)
        self.assertIn('kind: "delayed_memory_report"', source)
        self.assertIn('deleted_delayed_memory_report', source)
        self.assertIn('"payload"', source)
        self.assertIn('"restore"', source)
        self.assertIn('api.restoreDelayedMemoryReport(', source)

    def test_extraction_and_merge_request_response_cards_are_paired(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('`[MEMORY:L4:${phaseLabel}]`', source)
        self.assertIn('"summarizer_request"', source)
        self.assertIn('"summarizer_result"', source)
        self.assertIn('"request"', source)
        self.assertIn('"response"', source)
        self.assertIn('tone === "muted"', source)
        self.assertIn('kind: "l4_summarizer_response"', source)
        self.assertIn('responseSettled: false', source)
        self.assertIn('responseReady: false', source)
        self.assertIn('if (!state.responseReady)', source)
        self.assertIn('.find((candidate) => !candidate.responseSettled)', source)
        self.assertIn('setL4LoggerButtonVisible(', source)
        self.assertIn('settleL4SummarizerCardForTerminalEvent(', source)
        self.assertNotIn('.find((candidate) => !candidate.responseDetails)', source)

    def test_l4_response_modal_uses_structured_layout_and_no_changes_state(self):
        source = TRACE_MODAL_JS.read_text(encoding="utf-8")

        self.assertIn('parsed.kind === "l4_fact"', source)
        self.assertIn('parsed.kind === "l4_summarizer_response"', source)
        self.assertIn('parsed.kind === "l4_skip"', source)
        self.assertIn('"No changes"', source)
        self.assertIn('"What happened"', source)
        self.assertIn('"Retry behavior"', source)
        self.assertIn('parsed.reasoning_generated', source)
        self.assertIn('Array.isArray(payload.facts)', source)
        self.assertIn('Array.isArray(payload.operations)', source)

    def test_restore_message_round_trip_is_registered(self):
        runtime_source = RUNTIME_L4_JS.read_text(encoding="utf-8")
        socket_source = SOCKET_EVENTS_JS.read_text(encoding="utf-8")

        self.assertIn('type: "l4_memory_restore_fact"', runtime_source)
        self.assertIn('_restore_meta: restoreMeta', runtime_source)
        self.assertIn('requestFactRestore,', runtime_source)
        self.assertIn('"l4_memory_restore_result"', socket_source)
        self.assertIn('handleSocketL4MemoryRestoreResult', socket_source)
        self.assertIn('window.handleL4LoggerMemoryRestoreResult', socket_source)

    def test_delete_marks_local_l4_store_deleted_before_sync(self):
        runtime_source = RUNTIME_L4_JS.read_text(encoding="utf-8")

        self.assertIn("function deleteFactLocally(", runtime_source)
        self.assertIn("deleted_fact_ids: deletedFactIds", runtime_source)
        self.assertIn("deleteFactLocally(id)", runtime_source)
        self.assertIn("syncLongTermMemoryToRuntime();", runtime_source)

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('/static/css/runtime-memory.css?v=l4-report-link-1', source)
        self.assertIn('/static/js/runtime/runtime-l4-memory.js?v=delayed-loaded-facts-1', source)
        self.assertIn('/static/js/logger/logger.js?v=jin-size-5', source)
        self.assertIn('/static/js/logger/trace-modal.js?v=attached-files-1', source)
        self.assertIn('/static/js/logger/log-entries.js?v=delayed-fact-unlink-1', source)
        self.assertIn('/static/js/socket/event-handlers.js?v=l4-restore-2', source)


if __name__ == "__main__":
    unittest.main()
