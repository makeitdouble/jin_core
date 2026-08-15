import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DelayedMemoryClientContractTests(unittest.TestCase):

    def test_unload_delayed_memory_does_not_rewrite_saved_reports(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "replaceDelayedMemoryReports",
            source,
        )
        self.assertNotRegex(
            source,
            r"delete\s+reports\s*\[",
        )

    def test_delayed_memory_load_metadata_is_persisted_client_side(self):

        storage_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(
            encoding="utf-8"
        )
        runtime_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "loaded_times",
            storage_source,
        )
        self.assertIn(
            "load_streak",
            storage_source,
        )
        self.assertIn(
            "last_loaded_session_id",
            storage_source,
        )
        self.assertIn(
            "all_loaded_session_ids",
            storage_source,
        )
        self.assertIn(
            "facts_ids",
            storage_source,
        )
        self.assertIn(
            'action === "load_delayed_memory"',
            runtime_actions_source,
        )
        self.assertIn(
            "data.delayed_memory_result.report",
            runtime_actions_source,
        )

    def test_delayed_memory_delete_sync_and_loaded_state_are_registered(self):

        runtime_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime.js"
        ).read_text(
            encoding="utf-8"
        )
        l4_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-l4-memory.js"
        ).read_text(
            encoding="utf-8"
        )
        socket_delayed_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "delayed-memory.js"
        ).read_text(
            encoding="utf-8"
        )
        runtime_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "loadedDelayedMemoryReportIds",
            runtime_source,
        )
        self.assertIn(
            "isDelayedMemoryReportLoaded",
            runtime_source,
        )
        self.assertIn(
            "markDelayedMemoryReportLoaded",
            runtime_source,
        )
        self.assertIn(
            "deleteDelayedMemoryReport: deleteDelayedMemoryReportAndRender",
            runtime_source,
        )
        self.assertIn(
            "restoreDelayedMemoryReport: restoreDelayedMemoryReportAndRender",
            runtime_source,
        )
        self.assertIn(
            "isDelayedMemoryReportLoaded(reportId, report)",
            l4_source,
        )
        self.assertIn(
            "loadedIds.forEach((factId) => {",
            l4_source,
        )
        self.assertIn(
            "deleted_delayed_memory_report_ids: deletedReportIds",
            socket_delayed_source,
        )
        self.assertIn(
            'action === "load_delayed_memory"',
            runtime_actions_source,
        )
        self.assertIn(
            'action === "unload_delayed_memory"',
            runtime_actions_source,
        )
        self.assertIn(
            "markDelayedMemoryReportLoaded(",
            runtime_actions_source,
        )

        self.assertIn(
            "options.forceRender !== true",
            runtime_source,
        )
        self.assertIn(
            "{ forceRender: true }",
            runtime_actions_source,
        )

    def test_console_loaded_delayed_memory_titles_open_report_modal(self):

        logger_source = (
            ROOT / "ui" / "static" / "js" / "logger" / "logger.js"
        ).read_text(encoding="utf-8")
        index_source = (
            ROOT / "ui" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "function openConsoleDelayedMemoryReport(report)",
            logger_source,
        )
        self.assertIn(
            "memoryView.openDelayedMemoryReportModal(report)",
            logger_source,
        )
        self.assertIn(
            '"jin-attached-files-name jin-attached-delayed-memory-name"',
            logger_source,
        )
        self.assertIn(
            'name.addEventListener("click", openReport)',
            logger_source,
        )
        self.assertIn(
            '/static/js/logger/logger.js?v=delayed-context-plaque-3',
            index_source,
        )

    def test_context_loaded_delayed_memory_highlights_report_and_linked_l4(self):

        runtime_source = (
            ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
        ).read_text(encoding="utf-8")
        memory_view_source = (
            ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
        ).read_text(encoding="utf-8")
        avatar_source = (
            ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
        ).read_text(encoding="utf-8")
        socket_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "delayed-memory.js"
        ).read_text(encoding="utf-8")

        self.assertIn("getLoadedDelayedMemoryReportIds", runtime_source)
        self.assertIn("replaceLoadedDelayedMemoryReportIds", runtime_source)
        self.assertIn("runtime-memory-context-loaded-hit", memory_view_source)
        self.assertIn("getContextLoadedDelayedMemoryFactIds", memory_view_source)
        self.assertIn("isDelayedMemoryReportInContext", memory_view_source)
        self.assertIn("is-context-loaded", avatar_source)
        self.assertIn("collectDelayedMemoryLinkedL4FactIds", avatar_source)
        self.assertIn("loaded_delayed_memory_ids", socket_source)
        self.assertIn("replaceLoadedDelayedMemoryReportIds", socket_source)

    def test_delayed_memory_unpin_resyncs_all_avatar_link_state(self):

        runtime_source = (
            ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
        ).read_text(encoding="utf-8")
        index_source = (
            ROOT / "ui" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        pin_start = runtime_source.index(
            "function setDelayedMemoryReportPinned("
        )
        pin_end = runtime_source.index(
            "function setDelayedMemoryReportAnchorFactIds(",
            pin_start,
        )
        pin_block = runtime_source[pin_start:pin_end]

        self.assertIn(
            "if (!syncDelayedMemoryStateToAvatar())",
            pin_block,
        )
        self.assertNotIn(
            "!setDelayedMemoryPinnedOnAvatar(",
            pin_block,
        )
        self.assertIn(
            '/static/js/runtime/runtime.js?v=delayed-unpin-avatar-sync-1',
            index_source,
        )

    def test_loaded_delayed_memory_bubbles_open_their_own_reports(self):

        runtime_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )
        chat_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )
        attachments_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-attachments.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "function getDelayedMemoryRuntimeActionPreview",
            runtime_actions_source,
        )
        self.assertIn(
            "delayedMemoryResult.report",
            runtime_actions_source,
        )
        self.assertIn(
            "delayedMemoryResult.id",
            runtime_actions_source,
        )
        self.assertIn(
            "function normalizeDelayedMemoryRuntimeActionId",
            runtime_actions_source,
        )
        self.assertIn(
            "reportScopedDelayedAction",
            runtime_actions_source,
        )
        self.assertIn(
            "delayedMemoryPreview.reportId",
            runtime_actions_source,
        )
        self.assertIn(
            "delayedMemoryPreview.title",
            runtime_actions_source,
        )
        self.assertIn(
            "counterOnly\n    && reportScopedDelayedAction",
            runtime_actions_source,
        )
        self.assertIn(
            '"load_delayed_memory",',
            chat_actions_source,
        )
        self.assertGreaterEqual(
            chat_actions_source.count(
                "bindDelayedMemoryReportPreview("
            ),
            2,
        )
        self.assertIn(
            "function getDelayedMemoryReportPreviewSource",
            attachments_source,
        )
        self.assertIn(
            "reports[requestedId]",
            attachments_source,
        )

    def test_runtime_action_detail_ignores_generic_marker_payload_titles(self):

        runtime_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        detail_start = runtime_actions_source.index(
            "function buildRuntimeActionDetail"
        )
        object_title_start = runtime_actions_source.index(
            "const objectTitle =",
            detail_start,
        )
        object_title_end = runtime_actions_source.index(
            "if (objectTitle)",
            object_title_start,
        )
        object_title_block = runtime_actions_source[
            object_title_start:object_title_end
        ]

        self.assertIn(
            "data.skill_result",
            object_title_block,
        )
        self.assertNotIn(
            "data.payload",
            object_title_block,
        )
        self.assertNotIn(
            "data.payloads",
            object_title_block,
        )
        self.assertNotIn(
            "return String(\n    data.payload",
            runtime_actions_source[detail_start:],
        )

    def test_runtime_action_key_includes_message_scope(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        key_start = source.index(
            "function buildRuntimeActionVisibleKey"
        )
        key_end = source.index(
            "function clearRuntimeActionGuardConfirmation",
            key_start,
        )
        key_block = source[key_start:key_end]

        self.assertIn(
            "options.runtimeMessageId",
            key_block,
        )
        self.assertIn(
            "`${actionName}:${runtimeMessageId}:${actionId}`",
            key_block,
        )

    def test_runtime_action_update_removes_duplicate_rows(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "function removeDuplicateRuntimeActionRows",
            source,
        )
        self.assertIn(
            "function removeLegacyRuntimeActionRows",
            source,
        )
        self.assertIn(
            "removeDuplicateRuntimeActionRows(\n        existingRow,",
            source,
        )
        self.assertIn(
            "removeLegacyRuntimeActionRows(\n        existingRow,",
            source,
        )
        self.assertIn(
            "removeDuplicateRuntimeActionRows(\n    row,",
            source,
        )

    def test_socket_runtime_actions_keep_message_scope_for_all_actions(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "runtimeMessageId:\n          getRuntimeActionMessageId(data)",
            source,
        )
        self.assertNotIn(
            'action === "jin_color"\n      ? getRuntimeActionMessageId(data)\n      : ""',
            source,
        )
        self.assertNotIn(
            'action === "jin_color"\n            ? getRuntimeActionMessageId(data)\n            : ""',
            source,
        )

    def test_jin_color_uses_one_live_aggregate_bubble(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        handle_start = source.index(
            "function handleRuntimeAction("
        )
        color_start = source.index(
            'if (action === "jin_color") {',
            handle_start,
        )
        color_end = source.index(
            "\n    return;\n  }",
            color_start,
        )
        color_block = source[color_start:color_end]

        self.assertIn(
            "aggregateMarkers: true",
            color_block,
        )
        self.assertNotIn(
            "aggregateMarkers,\n          counterOnly:",
            color_block,
        )

    def test_socket_runtime_actions_fade_terminal_failures_with_scope(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "const terminalFailure =",
            source,
        )
        self.assertIn(
            "counterFinal\n      || terminalFailure",
            source,
        )
        self.assertIn(
            "runtimeMessageId,\n        sceneEffect",
            source,
        )
        self.assertIn(
            "fallbackToLatestActive:\n          terminalFailure",
            source,
        )

    def test_deferred_runtime_actions_fade_with_message_scope(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        flush_start = source.index(
            "function flushRuntimeActionsAfterResponse"
        )
        flush_end = source.index(
            "function fadeRuntimeAction",
            flush_start,
        )
        flush_block = source[flush_start:flush_end]

        self.assertIn(
            "runtimeTurnId:\n            entry.runtimeTurnId || \"\"",
            flush_block,
        )
        self.assertIn(
            "runtimeMessageId:\n            entry.runtimeMessageId || \"\"",
            flush_block,
        )

    def test_session_snapshot_history_and_loaded_ids_are_persisted(self):

        storage_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(
            encoding="utf-8"
        )
        session_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-session.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "jin.savedSessionMemoryHistory.v1",
            storage_source,
        )
        self.assertIn(
            "archiveLatestSavedSessionMemory",
            storage_source,
        )
        self.assertIn(
            "readSavedSessionMemoryHistory",
            storage_source,
        )
        self.assertIn(
            "loaded_memory_ids",
            session_source,
        )
        self.assertIn(
            "getLoadedDelayedMemoryReportIds()",
            session_source,
        )


if __name__ == "__main__":
    unittest.main()
