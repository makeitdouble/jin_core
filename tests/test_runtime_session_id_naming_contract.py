from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHAT_LOG = ROOT / "utils" / "chat_log.py"
STORAGE_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-storage.js"
ANON_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-anonymous-mode.js"
SOCKET_JS = ROOT / "ui" / "static" / "js" / "socket.js"


class RuntimeSessionIdNamingContractTests(unittest.TestCase):
    def test_backend_fallback_log_session_id_is_uuid(self):
        source = CHAT_LOG.read_text(encoding="utf-8")

        self.assertIn("from uuid import uuid4", source)
        self.assertIn("generated = str(uuid4())", source)
        self.assertNotIn('f"session_{', source)
        self.assertNotIn("secrets.token_hex", source)

    def test_browser_session_fallback_keeps_uuid_shape(self):
        source = STORAGE_JS.read_text(encoding="utf-8")

        self.assertIn("function generateRuntimeSessionId()", source)
        self.assertIn("window.crypto.randomUUID()", source)
        self.assertIn("const bytes = new Uint8Array(16);", source)
        self.assertIn("bytes[6] = (bytes[6] & 0x0f) | 0x40;", source)
        self.assertIn("bytes[8] = (bytes[8] & 0x3f) | 0x80;", source)
        self.assertNotIn('"session",\n      Date.now()', source)

    def test_anonymous_session_generation_uses_only_uuid_anon(self):
        source = ANON_JS.read_text(encoding="utf-8")

        self.assertIn('ANONYMOUS_SESSION_SUFFIX = "_anon"', source)
        self.assertIn('const ANONYMOUS_SESSION_SUFFIXES = [', source)
        self.assertIn('"-anon",', source)
        self.assertIn("new Uint8Array(16)", source)
        self.assertNotIn('"session",\n          Date.now()', source)

    def test_socket_reuses_canonical_runtime_session_generator(self):
        source = SOCKET_JS.read_text(encoding="utf-8")

        self.assertIn("window.JinRuntime.storage.generateRuntimeSessionId()", source)
        self.assertNotIn("`${Date.now()}-${Math.random()", source)


if __name__ == "__main__":
    unittest.main()
