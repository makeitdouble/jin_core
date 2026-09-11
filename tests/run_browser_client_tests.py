from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROWSER_TESTS = (
    "test_attach_file_by_id_client.js",
    "test_chat_log_search_client.js",
    "test_chat_log_search_modal.js",
    "test_malformed_actions_client.js",
    "test_runtime_transport_client.js",
)


def main() -> int:
    if not shutil.which("node"):
        print("Browser client tests require Node.js.")
        return 2

    playwright = subprocess.run(
        ["node", "-e", "require.resolve('playwright')"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if playwright.returncode != 0:
        print(
            "Browser client tests require Playwright to be available to Node "
            "(the existing scripts also launch the Edge channel)."
        )
        return 2

    for filename in BROWSER_TESTS:
        print(f"\n=== {filename} ===", flush=True)
        completed = subprocess.run(["node", str(ROOT / "tests" / filename)], cwd=ROOT)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
