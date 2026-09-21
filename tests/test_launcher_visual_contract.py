from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "jl.ps1"


class LauncherVisualContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = LAUNCHER.read_text(encoding="utf-8")

    def test_live_page_title_probe_suppresses_powershell_progress_rendering(self):
        start = self.source.index("function Get-JinPageTitle")
        end = self.source.index("function Test-JinBrowserTabOpen", start)
        title_probe = self.source[start:end]

        self.assertIn('$ProgressPreference = "SilentlyContinue"', title_probe)
        self.assertIn("Invoke-WebRequest -Uri $AppUrl", title_probe)


if __name__ == "__main__":
    unittest.main()
