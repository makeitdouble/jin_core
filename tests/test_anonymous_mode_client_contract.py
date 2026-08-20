from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AnonymousModeClientContractTests(unittest.TestCase):

    def test_detector_reads_user_facing_switches_from_runtime_config(self):
        source = (
            ROOT
            / "ui/static/js/runtime/runtime-anonymous-mode.js"
        ).read_text(encoding="utf-8")

        self.assertIn("readAnonymousModeConfig", source)
        self.assertIn("payload.anonymousMode", source)
        self.assertIn(
            "anonymousModeConfig.ENABLE_DEFAULT_ANONYMOUS_MODE !== false",
            source,
        )
        self.assertIn(
            "anonymousModeConfig.ENABLE_GLOBAL_ANONYMOUS_MODE === true",
            source,
        )
        self.assertNotIn(
            "const ENABLE_DEFAULT_ANONYMOUS_MODE = true;",
            source,
        )
        self.assertNotIn(
            "const ENABLE_GLOBAL_ANONYMOUS_MODE = false;",
            source,
        )
        self.assertIn("shouldIsolateStorage", source)
        self.assertIn("storage.estimate()", source)

    def test_anonymous_switches_are_exposed_by_config_and_template(self):
        config_source = (ROOT / "config.example.py").read_text(encoding="utf-8")
        template_source = (
            ROOT / "ui/templates/index.html"
        ).read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn(
            "ENABLE_DEFAULT_ANONYMOUS_MODE = True",
            config_source,
        )
        self.assertIn(
            "ENABLE_GLOBAL_ANONYMOUS_MODE = False",
            config_source,
        )
        self.assertIn(
            '"anonymousMode": anonymous_mode_config',
            template_source,
        )
        self.assertIn("build_anonymous_mode_config", app_source)
        self.assertIn(
            '"ENABLE_DEFAULT_ANONYMOUS_MODE"',
            app_source,
        )
        self.assertIn(
            '"ENABLE_GLOBAL_ANONYMOUS_MODE"',
            app_source,
        )

    def test_anonymous_active_memory_uses_separate_browser_key(self):
        source = (
            ROOT
            / "ui/static/js/runtime/runtime-storage.js"
        ).read_text(encoding="utf-8")

        self.assertIn("jin.activeMemory.anonymous.v1", source)
        self.assertIn("getActiveMemoryStorageKey", source)
        self.assertIn("shouldIsolateAnonymousStorage", source)
        self.assertIn("readLatestSavedSessionSnapshot", source)
        self.assertIn("writeLatestSavedSessionSnapshot", source)

    def test_socket_waits_for_detection_and_marks_anonymous_connection(self):
        source = (
            ROOT
            / "ui/static/js/socket.js"
        ).read_text(encoding="utf-8")

        self.assertIn('"anonymous_mode",', source)
        self.assertIn('"1"', source)
        self.assertIn("anonymousMode.ready", source)
        self.assertIn('type: "active_memory_store_sync"', source)

    def test_restricted_write_failure_is_struck_through(self):
        source = (
            ROOT
            / "ui/static/js/socket/runtime-actions.js"
        ).read_text(encoding="utf-8")

        self.assertIn("restrictedWriteFailure", source)
        self.assertIn('=== "restricted_write"', source)
        self.assertIn("strikeThroughFailure", source)

    def test_detector_loads_before_storage_and_socket(self):
        source = (
            ROOT
            / "ui/templates/index.html"
        ).read_text(encoding="utf-8")

        detector = source.index("runtime-anonymous-mode.js")
        storage = source.index("runtime-storage.js")
        socket = source.index("static/js/socket.js")
        self.assertLess(detector, storage)
        self.assertLess(storage, socket)


if __name__ == "__main__":
    unittest.main()
