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

    def test_metabolic_spots_keep_original_geometry_but_gain_value_driven_drift(self):
        metabolism = (ROOT / "ui/static/js/runtime/runtime-metabolism.js").read_text()
        avatar_css = (ROOT / "ui/static/css/runtime-avatar.css").read_text()

        self.assertIn("METABOLIC_SPOT_DRIFT_ENABLED = true", metabolism)
        self.assertIn("SPOT_GEOMETRY", metabolism)
        self.assertIn("dopamine: Object.freeze({ x: 22, y: 24, radius: 42 })", metabolism)
        self.assertIn("serotonin: Object.freeze({ x: 78, y: 20, radius: 43 })", metabolism)
        self.assertIn("getSpotRadiusPercent", metabolism)
        self.assertIn("getSpotDriftSpeed", metabolism)
        self.assertIn("scheduleSpotDrift", metabolism)
        self.assertIn("getRenderedSpotPosition", metabolism)
        self.assertIn("retargetSpotDriftForCurrentState", metabolism)
        self.assertIn("updateSpotSizes: true", metabolism)

        self.assertIn("@property --jin-metabolism-dopamine-x", avatar_css)
        self.assertIn("--jin-metabolism-dopamine-drift-duration", avatar_css)
        self.assertIn("--jin-metabolism-dopamine-radius 14s", avatar_css)
        self.assertIn("var(--jin-metabolism-dopamine-x, 22%)", avatar_css)
        self.assertIn("var(--jin-metabolism-dopamine-radius, 42%)", avatar_css)

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
