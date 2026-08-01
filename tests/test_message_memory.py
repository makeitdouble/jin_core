"""Manual dispatcher for the split memory test modules."""

import importlib
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_SPLIT_MODULES = (
    "tests.test_l1_memory",
    "tests.test_l2_memory",
    "tests.test_l3_session_memory",
    "tests.test_brain_prompt_memory",
    "tests.test_memory_scheduler",
)


def suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()

    for module_name in _SPLIT_MODULES:
        module = importlib.import_module(module_name)
        test_suite.addTests(loader.loadTestsFromModule(module))

    return test_suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    raise SystemExit(not result.wasSuccessful())
