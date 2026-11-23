"""tools/run_tests: tiny temp projects with the real unittest, and fake runners for the others."""

import json
import os
import unittest
from unittest import mock

from support import ItemTest, have

ITEM = "tools/run_tests.py"

TESTS_PY = """import unittest

class T(unittest.TestCase):
    def test_ok(self):
        pass

    def test_bad(self):
        self.assertEqual(1, 2)
"""


@unittest.skipUnless(have("python3") and have("sh"), "needs python3 and sh")
class RunTestsTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()

    def run_tool(self, registry=None, **input):
        registry = registry or self.load(ITEM)[0]
        return registry.tools["run_tests"].run(input, self.ctx(cwd=self.proj))

    def fake_runner(self, name, output, exit=1):
        """A ``name`` that logs its argv to argv.log, prints ``output`` and exits with ``exit``."""
        out = self.tmp / f"{name}.out"
        out.write_text(output)
        self.argv_log = self.tmp / "argv.log"
        self.argv_log.unlink(missing_ok=True)
        self.fake_bin(name, f'#!/bin/sh\necho "$@" >> {self.argv_log}\ncat {out}\nexit {exit}\n')

    def test_the_tool_confirms_and_says_when_to_use_it(self):
        tool = self.load(ITEM)[0].tools["run_tests"]
        self.assertTrue(tool.confirm is True and not tool.read_only)
        self.assertIn("Prefer it over `bash`", tool.description)

    def test_unittest_project_lists_failures_then_the_end_of_the_output(self):
        (self.proj / "tests").mkdir()
        (self.proj / "tests" / "test_x.py").write_text(TESTS_PY)
        out = self.run_tool()
        lines = out.splitlines()
        self.assertRegex(lines[0], r"^runner: python3? -m unittest discover -s tests  exit 1  \d+\.\ds$")
        self.assertEqual(lines[1:3], ["FAILED (1):", "  FAIL: test_bad (test_x.T.test_bad)"])
        self.assertIn("AssertionError: 1 != 2", out)
        self.assertTrue(out.rstrip().endswith("FAILED (failures=1)"))

    def test_target_for_unittest_names_a_test(self):
        (self.proj / "tests").mkdir()
        (self.proj / "tests" / "test_x.py").write_text(TESTS_PY)
        out = self.run_tool(target="tests.test_x.T.test_ok")
        self.assertRegex(out.splitlines()[0], r"^runner: python3? -m unittest tests\.test_x\.T\.test_ok  exit 0  ")
        self.assertNotIn("FAILED", out)

    def test_pytest_is_detected_from_the_configuration_and_failures_are_parsed(self):
        (self.proj / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'\n")
        self.fake_runner("python3", "F.\nFAILED tests/test_a.py::test_one - assert 1 == 2\n1 failed, 1 passed\n")
        out = self.run_tool(target="tests/test_a.py")
        self.assertEqual(self.argv_log.read_text().strip(), "-m pytest -q -rf --tb=short tests/test_a.py")
        self.assertIn("FAILED (1):\n  FAILED tests/test_a.py::test_one - assert 1 == 2\n", out)

    def test_uv_run_goes_in_front_when_there_is_a_lockfile(self):
        (self.proj / "pyproject.toml").write_text("dependencies = ['pytest']\n")
        (self.proj / "uv.lock").write_text("")
        self.fake_runner("uv", "ok\n", exit=0)
        self.assertRegex(self.run_tool().splitlines()[0], r"^runner: uv run python3? -m pytest -q -rf --tb=short  exit 0")
        self.assertRegex(self.argv_log.read_text().strip(), r"^run python3? -m pytest -q -rf --tb=short$")

    def test_node_go_and_cargo(self):
        (self.proj / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        (self.proj / "pnpm-lock.yaml").write_text("")
        self.fake_runner("pnpm", "all good\n", exit=0)
        self.assertTrue(self.run_tool().startswith("runner: pnpm test  exit 0"))
        with self.assertRaisesRegex(ValueError, r"^target is not supported for npm, yarn or pnpm test; set the command setting"):
            self.run_tool(target="a.test.js")
        (self.proj / "package.json").unlink()
        (self.proj / "go.mod").write_text("module x\n")
        self.fake_runner("go", "--- FAIL: TestA (0.00s)\nFAIL\n")
        out = self.run_tool(target="./pkg")
        self.assertEqual(self.argv_log.read_text().strip(), "test ./pkg")
        self.assertIn("FAILED (1):\n  --- FAIL: TestA (0.00s)", out)
        (self.proj / "go.mod").unlink()
        (self.proj / "Cargo.toml").write_text("[package]\n")
        self.fake_runner("cargo", "test a::b ... FAILED\ntest c ... ok\n")
        self.assertIn("FAILED (1):\n  test a::b ... FAILED", self.run_tool(target="a::b"))
        self.assertEqual(self.argv_log.read_text().strip(), "test a::b")

    def test_the_command_setting_replaces_the_detection(self):
        self.fake_runner("mytest", "FAIL: test_z (m.C.test_z)\n")
        registry, errors = self.load(ITEM, command=["mytest", "--fast"])
        self.assertEqual(errors, [])
        out = self.run_tool(registry)  # an empty folder: nothing to detect, the setting is used
        self.assertIn("runner: mytest --fast  exit 1", out)
        self.assertIn("FAILED (1):\n  FAIL: test_z (m.C.test_z)", out)

    def test_nothing_detected_and_missing_runner_say_how_to_fix_it(self):
        with self.assertRaisesRegex(ValueError, "^no test runner detected; set the command setting$"):
            self.run_tool()
        (self.proj / "Cargo.toml").write_text("")
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            with self.assertRaisesRegex(ValueError, "^cargo is not installed or not on PATH; install it or set the command setting$"):
                self.run_tool(registry)

    def test_target_must_not_look_like_an_option_and_timeout_is_explained(self):
        (self.proj / "Cargo.toml").write_text("")
        self.fake_runner("cargo", "")
        with self.assertRaisesRegex(ValueError, "does not start with '-'"):
            self.run_tool(target="--nocapture")
        self.fake_bin("cargo", "#!/bin/sh\nsleep 30\n")
        with self.assertRaisesRegex(RuntimeError, r"^cargo timed out after 1s; raise the timeout or pass a narrower target$"):
            self.run_tool(timeout=1)

    def test_long_output_keeps_the_tail_and_is_clipped(self):
        (self.proj / "Cargo.toml").write_text("")
        self.fake_runner("cargo", "".join(f"line {i}\n" for i in range(500)), exit=0)
        registry, _ = self.load(ITEM, tail_lines=5)
        out = self.run_tool(registry)
        self.assertEqual(out.splitlines()[1:], [f"line {i}" for i in range(495, 500)])
        registry, _ = self.load(ITEM, tail_lines=500, max_chars=1000)
        self.assertRegex(self.run_tool(registry), r"\n\[clipped \d+ chars; lower tail_lines or pass a narrower target\]$")


if __name__ == "__main__":
    unittest.main()
