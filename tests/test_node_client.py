from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_TESTS = (
    "test_action_failure_presentation.js",
    "test_delayed_memory_dropdown.js",
    "test_recall_fact_context_client.js",
    "test_session_bootstrap_boundary.js",
    "test_tool_result_ids.js",
)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for client tests")
class NodeClientTests(unittest.TestCase):
    def _run_node_test(self, filename: str) -> None:
        completed = subprocess.run(
            ["node", str(ROOT / "tests" / filename)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(
                f"{filename} failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            ),
        )


for _filename in NODE_TESTS:
    _method_name = "test_" + _filename.removeprefix("test_").removesuffix(".js")

    def _test(self, filename=_filename):
        self._run_node_test(filename)

    _test.__name__ = _method_name
    setattr(NodeClientTests, _method_name, _test)

del _filename, _method_name, _test
