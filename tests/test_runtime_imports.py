import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RuntimeImportTests(unittest.TestCase):
    def test_import_boundaries_and_concrete_modules_share_one_clean_process(self):
        source = """
import sys

import runtime
assert not any(name.startswith('runtime.') for name in sys.modules)

import clients
assert not any(name.startswith('clients.') for name in sys.modules)

import utils.context.context_exports
import runtime.runtime_context
import clients.brain_client
"""
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
