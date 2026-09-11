from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import pkgutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"


class _MonkeyPatch:
    """Minimal replacement for the only monkeypatch API used by legacy tests."""

    def __init__(self) -> None:
        self._undo = []

    def setattr(self, target, name: str, value) -> None:
        existed = hasattr(target, name)
        previous = getattr(target, name, None)
        setattr(target, name, value)

        def undo() -> None:
            if existed:
                setattr(target, name, previous)
            else:
                delattr(target, name)

        self._undo.append(undo)

    def undo(self) -> None:
        while self._undo:
            self._undo.pop()()


def _redirect_default_chat_logs(root: Path) -> None:
    """Keep fake test session ids out of the real project logs directory."""
    import runtime.LT_mention_backfill as lt_mention_backfill
    import utils.chat_log as chat_log
    import utils.session_restore as session_restore

    chat_log.CHAT_LOG_ROOT = root
    session_restore.CHAT_LOG_ROOT = root
    lt_mention_backfill.CHAT_LOG_ROOT = root


def _function_test_method(function):
    signature = inspect.signature(function)
    unsupported = [
        name
        for name in signature.parameters
        if name not in {"tmp_path", "monkeypatch"}
    ]
    if unsupported:
        raise TypeError(
            f"Unsupported function-style test arguments in {function.__module__}.{function.__name__}: "
            f"{', '.join(unsupported)}"
        )

    def test_method(self):
        temporary_dir = None
        monkeypatch = None
        kwargs = {}
        try:
            if "tmp_path" in signature.parameters:
                temporary_dir = tempfile.TemporaryDirectory(prefix="jin-test-")
                kwargs["tmp_path"] = Path(temporary_dir.name)
            if "monkeypatch" in signature.parameters:
                monkeypatch = _MonkeyPatch()
                kwargs["monkeypatch"] = monkeypatch

            result = function(**kwargs)
            if inspect.isawaitable(result):
                asyncio.run(result)
        finally:
            if monkeypatch is not None:
                monkeypatch.undo()
            if temporary_dir is not None:
                temporary_dir.cleanup()

    test_method.__name__ = function.__name__
    test_method.__doc__ = function.__doc__
    return test_method


def _discover_function_style_tests(pattern: str) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader

    for module_info in pkgutil.walk_packages([str(TESTS_DIR)], prefix="tests."):
        if module_info.ispkg:
            continue
        module_leaf = module_info.name.rsplit(".", 1)[-1]
        module_file = module_leaf + ".py"
        if not Path(module_file).match(pattern):
            continue

        module = importlib.import_module(module_info.name)
        methods = {}
        for name, value in vars(module).items():
            if (
                name.startswith("test_")
                and inspect.isfunction(value)
                and value.__module__ == module.__name__
            ):
                methods[name] = _function_test_method(value)

        if not methods:
            continue

        class_name = "".join(part.capitalize() for part in module_leaf.split("_")) + "Functions"
        test_case = type(class_name, (unittest.TestCase,), methods)
        test_case.__module__ = module.__name__
        suite.addTests(loader.loadTestsFromTestCase(test_case))

    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the JIN unittest suite safely.")
    parser.add_argument(
        "-p",
        "--pattern",
        default="test*.py",
        help="unittest discovery filename pattern",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="jin-test-chat-logs-") as temporary_dir:
        _redirect_default_chat_logs(Path(temporary_dir))
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(TESTS_DIR),
            pattern=args.pattern,
            top_level_dir=str(ROOT),
        )
        suite.addTests(_discover_function_style_tests(args.pattern))
        runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
        result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
