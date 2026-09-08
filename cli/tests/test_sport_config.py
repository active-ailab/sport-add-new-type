import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import sport_config


class SportConfigCliTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.cwd = Path(self.work.name)
        self.report_dir = self.cwd / "reports"
        self.report_dir.mkdir()

    def tearDown(self):
        self.work.cleanup()

    def invoke(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = sport_config.run(list(arguments), cwd=self.cwd)
        return code, output.getvalue()

    def result(self, errors=0):
        return mock.Mock(error_count=errors)

    @mock.patch("sport_config.sport_config.write_report")
    @mock.patch("sport_config.sport_config.check_target")
    @mock.patch("sport_config.sport_config.resolve_target")
    def test_check_path_is_report_directory_and_r_is_target(self, resolve_target, check_target, write_report):
        resolve_target.return_value = mock.Mock()
        check_target.return_value = self.result()
        write_report.return_value = self.report_dir / "sport-config-check-report.xml"
        code, output = self.invoke("-c", str(self.report_dir), "-r", "/firmware")
        self.assertEqual(0, code)
        resolve_target.assert_called_once_with("/firmware")
        write_report.assert_called_once_with(check_target.return_value, str(self.report_dir))
        self.assertEqual("报告生成成功：{}\n".format(write_report.return_value), output)

    @mock.patch("sport_config.sport_config.write_report")
    @mock.patch("sport_config.sport_config.check_target")
    @mock.patch("sport_config.sport_config.resolve_target")
    def test_check_uses_cwd_as_default_report_directory(self, resolve_target, check_target, write_report):
        resolve_target.return_value = mock.Mock()
        check_target.return_value = self.result()
        write_report.return_value = self.cwd / "sport-config-check-report.xml"
        code, _ = self.invoke("CHECK")
        self.assertEqual(0, code)
        resolve_target.assert_called_once_with(self.cwd)
        write_report.assert_called_once_with(check_target.return_value, self.cwd)

    @mock.patch("sport_config.sport_config.generate")
    @mock.patch("sport_config.sport_config.check_target")
    @mock.patch("sport_config.sport_config.resolve_target")
    def test_gen_uses_same_target_and_blocks_only_on_errors(self, resolve_target, check_target, generate):
        target = mock.Mock()
        resolve_target.return_value = target
        check_target.return_value = self.result()
        generate.return_value = "diff"
        code, output = self.invoke("-G", "-r", "/firmware")
        self.assertEqual(0, code)
        generate.assert_called_once_with(target)
        self.assertIn("PASS: sport_gen.py completed", output)

    def test_help_keeps_short_actions(self):
        help_text = sport_config.sport_config.build_parser().format_help()
        self.assertIn("-c/check, -g/gen, -a/add", help_text)


if __name__ == "__main__":
    unittest.main()
