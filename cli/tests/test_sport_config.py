import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import sport_config


class SportConfigTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.repo = Path(self.work.name) / "repo"
        (self.repo / ".repo").mkdir(parents=True)
        self.common = self.repo / sport_config.COMMON_RELATIVE
        self.common.mkdir(parents=True)
        (self.common / sport_config.XLSX_NAME).write_bytes(b"placeholder")
        (self.common / sport_config.GENERATOR_NAME).write_text(
            "from pathlib import Path\nPath('generated.marker').write_text('generated')\n",
            encoding="utf-8",
        )
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Sport Config Test")
        self._git("add", ".")
        self._git("commit", "-m", "initial")

    def tearDown(self):
        self.work.cleanup()

    def _git(self, *arguments):
        subprocess.run(["git", "-C", str(self.repo), *arguments], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = sport_config.run(list(args), cwd=self.common)
        return code, output.getvalue()

    def change_xlsx(self):
        (self.common / sport_config.XLSX_NAME).write_bytes(b"changed")

    def test_short_help_is_available(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                sport_config.run(["-h"], cwd=self.common)
        self.assertEqual(0, raised.exception.code)
        self.assertIn("-c/-C/-check/check", output.getvalue())

    def test_check_help_uses_the_single_global_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                sport_config.run(["check", "-h"], cwd=self.common)
        self.assertEqual(0, raised.exception.code)
        self.assertIn("ACTION:", output.getvalue())

    def test_check_aliases_skip_unchanged_xlsx(self):
        for alias in ("-c", "-C", "-check", "-CHECK", "check", "CHECK", "ChEcK"):
            with mock.patch("sport_config.check_xlsx") as checker:
                code, output = self.invoke(alias)
            self.assertEqual(0, code, alias)
            self.assertIn("SKIP: sports.xlsx unchanged", output, alias)
            checker.assert_not_called()

    def test_gen_aliases_skip_unchanged_xlsx(self):
        for alias in ("-g", "-G", "-gen", "-GEN", "gen", "GEN", "GeN"):
            with mock.patch("sport_config.run_generator") as generator:
                code, output = self.invoke(alias)
            self.assertEqual(0, code, alias)
            self.assertIn("SKIP: generation not run", output, alias)
            generator.assert_not_called()

    def test_check_skips_unchanged_xlsx_without_parsing(self):
        with mock.patch("sport_config.check_xlsx") as checker:
            code, output = self.invoke("check")
        self.assertEqual(0, code)
        self.assertIn("SKIP: sports.xlsx unchanged", output)
        checker.assert_not_called()

    def test_check_validates_changed_xlsx(self):
        self.change_xlsx()
        with mock.patch("sport_config.check_xlsx", return_value=[] ) as checker:
            code, output = self.invoke("check")
        self.assertEqual(0, code)
        self.assertIn("PASS: sports.xlsx check passed", output)
        checker.assert_called_once_with(self.common / sport_config.XLSX_NAME)

    def test_gen_skips_unchanged_xlsx(self):
        with mock.patch("sport_config.run_generator") as generator:
            code, output = self.invoke("gen")
        self.assertEqual(0, code)
        self.assertIn("SKIP: generation not run", output)
        generator.assert_not_called()

    def test_gen_runs_existing_script_after_changed_xlsx_passes_check(self):
        self.change_xlsx()
        with mock.patch("sport_config.check_xlsx", return_value=[]):
            code, output = self.invoke("gen")
        self.assertEqual(0, code)
        self.assertEqual("generated", (self.common / "generated.marker").read_text(encoding="utf-8"))
        self.assertIn("PASS: sport_gen.py completed", output)

    def test_changed_xlsx_returns_error_when_rules_fail(self):
        self.change_xlsx()
        findings = [sport_config.Finding("ERROR", "test.rule", "bad value")]
        with mock.patch("sport_config.check_xlsx", return_value=findings):
            with self.assertRaises(SystemExit) as raised:
                self.invoke("check")
        self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
