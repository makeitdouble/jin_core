from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ACTIONS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
INPUT = ROOT / "ui" / "static" / "js" / "socket" / "input.js"
CHAT = ROOT / "ui" / "static" / "js" / "chat.js"
MEMORY_VIEW = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
AVATAR = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
INDEX = ROOT / "ui" / "templates" / "index.html"


class UpdateActiveMemoryHighlightClientContractTests(unittest.TestCase):
    def test_successful_update_reuses_existing_citation_highlight_by_stable_id(self):
        source = RUNTIME_ACTIONS.read_text(encoding="utf-8")

        self.assertIn(
            '"jin:think-runtime-citation-highlight"',
            source,
        )
        self.assertIn(
            "function highlightUpdatedActiveMemory(activeMemoryId)",
            source,
        )
        self.assertIn(
            "sourceId: `runtime-action:update-active-memory:${normalizedId}`",
            source,
        )
        self.assertIn("activeMemoryIds: [normalizedId]", source)
        self.assertIn(
            "window.JinRuntime.runtime.replaceActiveMemoryRecordById(\n      activeMemoryId,",
            source,
        )
        self.assertIn(
            "highlightUpdatedActiveMemory(\n      activeMemoryId",
            source,
        )

    def test_existing_user_send_clear_turns_off_update_highlight_everywhere(self):
        input_source = INPUT.read_text(encoding="utf-8")
        chat = CHAT.read_text(encoding="utf-8")
        memory_view = MEMORY_VIEW.read_text(encoding="utf-8")
        avatar = AVATAR.read_text(encoding="utf-8")

        self.assertIn("window.clearLatestJinMemoryReferenceText();", input_source)
        self.assertIn('dispatchJinMemoryReferenceHighlight(\n    "persistent",\n    "",\n    false', chat)
        self.assertIn("activeThinkMemoryCitationSources.clear();", memory_view)
        self.assertIn("activeThinkRuntimeCitationSources.clear();", avatar)

    def test_runtime_action_cache_key_includes_update_highlight_revision(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("active-memory-update-highlight=1", source)


if __name__ == "__main__":
    unittest.main()
