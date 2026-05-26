import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT),
)

os.environ[
    "JIN_RUN_TRANSLATION_MODEL_TESTS"
] = "1"

suite = unittest.defaultTestLoader.discover(
    start_dir=str(
        ROOT / "tests"
    ),
    pattern="test_translation_pipeline.py",
)

result = unittest.TextTestRunner(
    verbosity=2,
).run(
    suite
)

raise SystemExit(
    0
    if result.wasSuccessful()
    else 1
)
