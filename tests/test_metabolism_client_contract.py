from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MetabolismClientContractTests(unittest.TestCase):
    def test_palette_ambient_aura_and_memory_tint_hook_are_present(self):
        metabolism = (ROOT / "ui/static/js/runtime/runtime-metabolism.js").read_text()
        avatar = (ROOT / "ui/static/js/runtime/runtime-avatar.js").read_text()
        avatar_css = (ROOT / "ui/static/css/runtime-avatar.css").read_text()

        for color in ("#fbbf24", "#60a5fa", "#f472b6", "#f97316", "#34d399"):
            self.assertIn(color, metabolism)
            self.assertIn(color, avatar_css)

        self.assertIn("jin:metabolism-update", metabolism)
        self.assertIn("getDominantChannel", metabolism)
        self.assertIn('return metabolismApi ? "ambient" : ""', avatar)
        self.assertIn("refreshRenderedMetabolismTints", avatar)
        self.assertIn("--jin-metabolism-dopamine-aura", avatar_css)
        self.assertIn("-webkit-mask-image: radial-gradient(", avatar_css)
        self.assertIn("transparent 84%", avatar_css)

    def test_logger_card_pairs_request_response_and_reuses_trace_pattern(self):
        logger = (ROOT / "ui/static/js/logger/log-entries.js").read_text()
        modal = (ROOT / "ui/static/js/logger/trace-modal.js").read_text()
        css = (ROOT / "ui/static/css/runtime-memory.css").read_text()

        self.assertIn('createL4LoggerButton(\n      "request"', logger)
        self.assertIn('createL4LoggerButton(\n      "response"', logger)
        self.assertIn("metabolism_request_id", logger)
        self.assertIn("candidate.requestId === requestId", logger)
        self.assertIn("metabolism_request", modal)
        self.assertIn("Runtime actions", modal)
        self.assertIn("Service target", modal)
        self.assertIn("Applied delta", modal)
        self.assertIn("jin-metabolism-card", css)


if __name__ == "__main__":
    unittest.main()
