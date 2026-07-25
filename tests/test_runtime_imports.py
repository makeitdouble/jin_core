import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RuntimeImportTests(unittest.TestCase):

    def run_import_check(
        self,
        source: str,
    ):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                source,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

    def test_context_exports_imports_without_runtime_cycle(self):
        self.run_import_check(
            "import utils.context.context_exports",
        )

    def test_runtime_package_does_not_eagerly_import_runtime_modules(self):
        self.run_import_check(
            "import sys; import runtime; "
            "assert not any(name.startswith('runtime.') for name in sys.modules)",
        )

    def test_clients_package_does_not_eagerly_import_client_modules(self):
        self.run_import_check(
            "import sys; import clients; "
            "assert not any(name.startswith('clients.') for name in sys.modules)",
        )

    def test_concrete_runtime_and_client_modules_import_without_cycle(self):
        self.run_import_check(
            "import runtime.runtime_context; import clients.brain_client",
        )


if __name__ == "__main__":
    unittest.main()
