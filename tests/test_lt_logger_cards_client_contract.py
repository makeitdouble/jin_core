from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOG_ENTRIES_JS = ROOT / "ui" / "static" / "js" / "logger" / "log-entries.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"
RUNTIME_LT_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-lt-memory.js"
SOCKET_EVENTS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"
RUNTIME_MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
LT_MEMORY_PY = ROOT / "runtime" / "LT_memory.py"


class LTLoggerCardsClientContractTests(unittest.TestCase):

    def test_deleted_fact_card_exposes_full_payload_and_restore(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:L-T:DELETED]"', source)
        self.assertIn('kind: "lt_fact"', source)
        self.assertIn('"payload"', source)
        self.assertIn('"restore"', source)
        self.assertIn('api.requestFactRestore(', source)
        self.assertIn('window.handleLTLoggerMemoryRestoreResult', source)
        self.assertIn('window.handleLTMemoryRestoreResult', source)
        self.assertIn('resolveDeletedLTFactNumber(fact)', source)
        self.assertIn('`${factNumber} · ${factTitle}`', source)

    def test_deleted_delayed_memory_card_exposes_payload_and_restore(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:DELAYED:DELETED]"', source)
        self.assertIn('kind: "delayed_memory_report"', source)
        self.assertIn('deleted_delayed_memory_report', source)
        self.assertIn('"payload"', source)
        self.assertIn('"restore"', source)
        self.assertIn('api.restoreDelayedMemoryReport(', source)

    def test_extraction_merge_and_apply_share_one_sequence_card(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")
        css = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:L-T]"', source)
        self.assertIn('"summarizer_request"', source)
        self.assertIn('"summarizer_result"', source)
        self.assertIn(
            r'/^l-?t\s+(extraction|merge)\s+summarizer\s+/',
            source,
        )
        self.assertNotIn('startsWith("lt extraction summarizer ")', source)
        self.assertIn('"extract",\n      "extraction"', source)
        self.assertIn('"merge",\n      "merge"', source)
        self.assertIn('"apply",\n      "apply"', source)
        self.assertNotIn('arrow.textContent = "--->"', source)
        self.assertIn('showButton.disabled = true', source)
        self.assertIn('state.showButton.disabled = false', source)
        self.assertIn('buildLTSummarizerResponseTrace(', source)
        self.assertIn('meta.continues_to_merge === false', source)
        self.assertIn('state.diffTitle =\n        "L-T extraction response"', source)
        self.assertIn('state.elements.apply.label,\n        "success"', source)
        self.assertIn('state.elements.merge.label,\n        "idle"', source)
        self.assertIn('state.elements.merge.arrow,\n        "idle"', source)
        self.assertIn('state.diffDetails,\n        state.diffTitle', source)
        self.assertIn('moveLogToBottomWithFlip(', source)
        self.assertIn('inspectLTSequenceElement(', source)
        self.assertIn('phaseState.requestDetails', source)
        self.assertIn('phaseState.responseDetails', source)
        self.assertIn('phaseState.terminalDetails', source)
        self.assertIn('kind: "lt_summarizer_response"', source)
        self.assertIn('setLTSequenceInspectable(', source)
        self.assertIn('event === "extract_applied"', source)
        self.assertIn('event === "merge_applied"', source)
        self.assertIn('isLTSequenceTerminalFailure(event)', source)
        self.assertIn('.jin-lt-sequence-track', css)
        self.assertIn('padding-inline: 12px', css)
        self.assertIn('white-space: nowrap', css)
        self.assertIn('.jin-lt-sequence-arrow::before', css)
        self.assertIn('background: currentColor', css)
        self.assertIn('cursor: pointer', css)
        self.assertIn('opacity: 0.5', css)
        self.assertIn('[data-status="success"]', css)
        self.assertIn('[data-status="failed"]', css)

    def test_lt_response_modal_uses_structured_layout_and_no_changes_state(self):
        source = TRACE_MODAL_JS.read_text(encoding="utf-8")

        self.assertIn('parsed.kind === "lt_fact"', source)
        self.assertIn('parsed.kind === "lt_summarizer_response"', source)
        self.assertIn('parsed.kind === "lt_skip"', source)
        self.assertIn('"No changes"', source)
        self.assertIn('"What happened"', source)
        self.assertIn('"Retry behavior"', source)
        self.assertIn('parsed.reasoning_generated', source)
        self.assertIn('Array.isArray(payload.facts)', source)
        self.assertIn('Array.isArray(payload.operations)', source)

    def test_lt_runtime_emits_sequence_terminal_events(self):
        source = LT_MEMORY_PY.read_text(encoding="utf-8")

        self.assertIn('event="extract_applied"', source)
        self.assertIn('continues_to_merge=bool(', source)
        self.assertIn('event="merge_applied"', source)
        self.assertIn('details=merge_details or "No changes"', source)
        self.assertIn('event="update_failed"', source)

    def test_lt_merge_applied_modal_renders_intensity_scaled_green_diffs(self):
        source = TRACE_MODAL_JS.read_text(encoding="utf-8")
        css = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")
        index_source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("parseLegacyLTMergeAppliedTrace", source)
        self.assertIn("buildLTMergeAddedTokenDiff", source)
        self.assertIn("appendLTMergeDiffText", source)
        self.assertIn("renderLTMergeAppliedTrace", source)
        self.assertIn('"jin-lt-merge-trace-modal"', source)
        self.assertIn("jin-lt-merge-row-after.jin-lt-diff-level-1", css)
        self.assertIn("jin-lt-merge-row-after.jin-lt-diff-level-5", css)
        self.assertIn("jin-lt-merge-diff-token.jin-lt-diff-level-5", css)
        self.assertIn("lt-merge-diff=1", index_source)

    def test_lt_paused_card_is_rendered_as_a_red_memory_card(self):
        source = LOG_ENTRIES_JS.read_text(encoding="utf-8")
        index_source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('"[MEMORY:L-T:PAUSED]"', source)
        self.assertIn('bg-red-500/5', source)
        self.assertIn('border-red-500/15', source)
        self.assertIn('text-red-300 font-bold', source)
        self.assertIn('lt-double-batch=1', index_source)

    def test_restore_message_round_trip_is_registered(self):
        runtime_source = RUNTIME_LT_JS.read_text(encoding="utf-8")
        socket_source = SOCKET_EVENTS_JS.read_text(encoding="utf-8")

        self.assertIn('type: "lt_memory_restore_fact"', runtime_source)
        self.assertIn('_restore_meta: restoreMeta', runtime_source)
        self.assertIn('requestFactRestore,', runtime_source)
        self.assertIn('"lt_memory_restore_result"', socket_source)
        self.assertIn('handleSocketLTMemoryRestoreResult', socket_source)
        self.assertIn('window.handleLTLoggerMemoryRestoreResult', socket_source)

    def test_delete_marks_local_lt_store_deleted_before_sync(self):
        runtime_source = RUNTIME_LT_JS.read_text(encoding="utf-8")

        self.assertIn("function deleteFactLocally(", runtime_source)
        self.assertIn("deleted_fact_ids: deletedFactIds", runtime_source)
        self.assertIn("deleteFactLocally(id)", runtime_source)
        self.assertIn("syncLongTermMemoryToRuntime();", runtime_source)

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('/static/css/runtime-memory.css?v=delayed-collapsible-cards-2', source)
        self.assertIn('/static/js/runtime/runtime-lt-memory.js?v=server-lt-scheduler-1', source)
        self.assertIn('/static/js/logger/logger.js?v=delayed-context-plaque-4', source)
        self.assertIn('/static/js/logger/trace-modal.js?v=context-session-actions-1', source)
        self.assertIn('/static/js/logger/log-entries.js?v=update-lt-message-1', source)
        self.assertIn('/static/js/socket/event-handlers.js?v=stream-avatar-1', source)


if __name__ == "__main__":
    unittest.main()
