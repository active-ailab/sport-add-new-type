import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import sport_proto


class SportProtoTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.repo = Path(self.work.name) / "repo"
        (self.repo / ".repo").mkdir(parents=True)
        self.generator_dir = self.repo / "framework/utils/nanopb/generator"
        self.generator_dir.mkdir(parents=True)
        self._write_generator()
        self._write_profile("PHN", "PHN")
        self._write_profile("phn_plan", "phn_plan")

    def tearDown(self):
        self.work.cleanup()

    def _write_generator(self):
        generator = self.generator_dir / "nanopb_generator.py"
        generator.write_text(
            "import pathlib, sys\n"
            "proto = pathlib.Path(sys.argv[1])\n"
            "stem = proto.stem\n"
            "pathlib.Path(stem + '.pb.c').write_text('generated-c:' + stem + '\\n')\n"
            "pathlib.Path(stem + '.pb.h').write_text('generated-h:' + stem + '\\n')\n",
            encoding="utf-8",
        )

    def _write_profile(self, profile, stem):
        item = sport_proto.PROFILE_BY_NAME[profile]
        proto = self.repo / item.proto
        proto.parent.mkdir(parents=True, exist_ok=True)
        proto.write_text("syntax = 'proto2';\n", encoding="utf-8")
        if item.options:
            options = self.repo / item.options
            options.parent.mkdir(parents=True, exist_ok=True)
            options.write_text("# options\n", encoding="utf-8")
        for output in (self.repo / item.source, self.repo / item.header):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("old:" + stem + "\n", encoding="utf-8")

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = sport_proto.run(list(args), cwd=self.repo / "packages/services/sport/src/phn")
        return code, output.getvalue()

    def test_list_uses_repo_relative_existing_proto_paths(self):
        code, output = self.invoke("-L")
        self.assertEqual(0, code)
        self.assertIn("PHN       packages/services/sport/src/phn/phn_proto/PHN.proto", output)
        self.assertIn("phn_plan  packages/services/sport/src/phn/phn_proto/phn_plan.proto", output)
        self.assertIn("packages/services/sport/src/phn/phn_proto/PHN.proto", output)
        self.assertIn("packages/services/sport/src/phn/phn_proto/phn_plan.proto", output)
        self.assertIn("count: 2", output)

    def test_help_describes_compact_workflow(self):
        help_text = sport_proto.build_parser().format_help()
        self.assertIn("先使用 -l 获取 Profile，再使用 -p 预览；确认后追加 -w 回写。", help_text)

    def test_preview_keeps_targets_and_cleans_generator_directory(self):
        code, output = self.invoke("-P", "PHN")
        item = sport_proto.PROFILE_BY_NAME["PHN"]
        self.assertEqual(0, code)
        self.assertIn("temporary source: /tmp/sport-proto-", output)
        self.assertEqual("old:PHN\n", (self.repo / item.source).read_text(encoding="utf-8"))
        self.assertEqual([], list(self.generator_dir.glob("PHN.*")))

    def test_write_copies_from_tmp_and_reports_final_targets(self):
        code, output = self.invoke("-p", "PHN", "-w")
        item = sport_proto.PROFILE_BY_NAME["PHN"]
        self.assertEqual(0, code)
        self.assertEqual("generated-c:PHN\n", (self.repo / item.source).read_text(encoding="utf-8"))
        self.assertIn("output source: {} ({})".format(item.source, self.repo / item.source), output)
        self.assertNotIn("temporary source:", output)

    def test_repeated_profiles_run_serially_and_leave_generator_clean(self):
        code, output = self.invoke("-p", "PHN", "-p", "phn_plan")
        self.assertEqual(0, code)
        self.assertLess(output.index("profile: PHN"), output.index("profile: phn_plan"))
        self.assertEqual([], [path for path in self.generator_dir.iterdir() if path.name != "nanopb_generator.py"])


if __name__ == "__main__":
    unittest.main()
