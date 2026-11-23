"""sandbox: argv construction is pure; the real sandbox-exec run is macOS only."""

import importlib.util
import os
import socket
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from support import ROOT, ItemTest, have

ITEM = "extensions/sandbox.py"
DARWIN = sys.platform == "darwin" and have("sandbox-exec")


def module():
    spec = importlib.util.spec_from_file_location("sandbox_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ArgvTest(unittest.TestCase):
    def setUp(self):
        self.mod = module()

    def test_sandbox_exec_profile_denies_reads_and_limits_writes(self):
        profile = self.mod.sandbox_exec_profile("/work", "/tmp/t", ["/home/u/.ssh"], ["/cache"], "deny")
        self.assertEqual(
            profile,
            "(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)(allow signal)(allow file-read*)\n"
            '(deny file-read* (subpath "/home/u/.ssh"))\n'
            '(allow file-write* (subpath "/work") (subpath "/tmp/t") (literal "/dev/null") (literal "/dev/tty") (subpath "/cache"))',
        )
        self.assertTrue(self.mod.sandbox_exec_profile("/w", "/t", [], [], "allow").endswith("\n(allow network*)"))

    def test_paths_are_escaped_for_the_profile(self):
        profile = self.mod.sandbox_exec_profile('/a"b\\c', "/t", [], [], "deny")
        self.assertIn('(subpath "/a\\"b\\\\c")', profile)

    def test_sandbox_exec_argv(self):
        argv = self.mod.sandbox_exec_argv(["/bin/bash", "-c", "ls"], "/w", "/t", [], [], "deny")
        self.assertEqual(argv[:2], ["sandbox-exec", "-p"])
        self.assertEqual(argv[3:], ["/bin/bash", "-c", "ls"])

    def test_bwrap_argv(self):
        exists = lambda p: p in ("/home/u/.ssh", "/home/u/keys.json")  # noqa: E731
        isdir = lambda p: p == "/home/u/.ssh"  # noqa: E731
        argv = self.mod.bwrap_argv(["/bin/bash", "-c", "ls"], "/w", "/t", ["/home/u/.ssh", "/home/u/keys.json", "/home/u/missing"], ["/cache"], "deny", exists, isdir)
        self.assertEqual(
            argv,
            ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--bind", "/w", "/w", "--bind", "/t", "/t", "--bind", "/cache", "/cache",
             "--tmpfs", "/home/u/.ssh", "--ro-bind", "/dev/null", "/home/u/keys.json", "--unshare-net", "--die-with-parent", "--chdir", "/w", "/bin/bash", "-c", "ls"],
        )
        self.assertNotIn("--unshare-net", self.mod.bwrap_argv(["x"], "/w", "/t", [], [], "allow"))

    def test_docker_argv(self):
        self.assertEqual(
            self.mod.docker_argv(["/bin/bash", "-c", "ls"], "/w", "debian:stable-slim", "deny"),
            ["docker", "run", "--rm", "-i", "-v", "/w:/w", "-w", "/w", "--network", "none", "debian:stable-slim", "/bin/bash", "-c", "ls"],
        )
        self.assertNotIn("--network", self.mod.docker_argv(["x"], "/w", "img", "allow"))

    def test_backend_choice(self):
        have_all = lambda name: f"/bin/{name}"  # noqa: E731
        none = lambda name: None  # noqa: E731
        choose = self.mod.choose_backend
        self.assertEqual(choose("auto", "Darwin", have_all, ""), "sandbox-exec")
        self.assertEqual(choose("auto", "Linux", have_all, ""), "bwrap")
        self.assertIsNone(choose("auto", "Linux", none, ""))
        self.assertIsNone(choose("auto", "Windows", have_all, "img"))  # docker only when chosen
        self.assertEqual(choose("docker", "Darwin", have_all, "img"), "docker")
        self.assertIsNone(choose("docker", "Darwin", have_all, ""))
        self.assertIsNone(choose("bwrap", "Linux", none, ""))


class BashMixin:
    def bash(self, app, command):
        return app.registry.tools["bash"].run({"command": command, "timeout_ms": 20000}, app.context)


class SandboxTest(BashMixin, ItemTest):

    def test_no_backend_refuses_every_bash_call_with_the_fix(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            app = self.make_app(ITEM, [])
        marker = self.tmp / "ran"
        with self.assertRaises(RuntimeError) as caught:
            self.bash(app, f"touch {marker}")
        self.assertEqual(
            str(caught.exception),
            "command wrapper failed: sandbox: no backend found (sandbox-exec, bwrap); install one or set sandbox.enabled to false",
        )
        self.assertFalse(marker.exists())
        self.assertTrue(any("every bash call is refused" in p for p in app.registry.problems + app.extension_problems))

    def test_disabled_wraps_nothing(self):
        app = self.make_app(ITEM, [], settings={"enabled": False})
        self.assertIsNone(app.registry.command_wrapper)
        self.assertNotIn("sandbox", app.registry.status)
        self.assertEqual(self.bash(app, "echo free"), "free\n\n[exit 0]")

    def test_status_segment_and_command_describe_the_policy(self):
        app = self.make_app(ITEM, [], settings={"extra_write": [str(self.tmp / "cache")], "network": "allow"})
        text = app.registry.commands["sandbox"].run("", app.context)
        self.assertIn(f"network: allow\nwritable: {os.path.realpath(self.tmp)}", text)
        self.assertIn(str(Path(os.path.realpath(self.tmp / "cache"))), text)
        self.assertIn(os.path.realpath(os.path.expanduser("~/.ssh")), text)
        if DARWIN:
            self.assertEqual(app.registry.status["sandbox"].render(app.context), "sandbox:sandbox-exec")

    def test_the_command_wrapper_receives_bash_and_returns_the_sandbox_argv(self):
        app = self.make_app(ITEM, [], settings={"backend": "docker", "docker_image": "img"}) if have("docker") else None
        if app is None:
            self.skipTest("needs docker on PATH to select the docker backend")
        wrapped = app.registry.command_wrapper(["/bin/bash", "-c", "ls"], app.context)
        self.assertEqual(wrapped[:3], ["docker", "run", "--rm"])
        self.assertEqual(wrapped[-4:], ["img", "/bin/bash", "-c", "ls"])


@unittest.skipUnless(DARWIN, "needs macOS sandbox-exec")
class RealSandboxTest(BashMixin, ItemTest):
    def setUp(self):
        super().setUp()
        self.secret = self.tmp / "secret"
        self.secret.mkdir()
        (self.secret / "key.txt").write_text("top secret")

    def app(self, **settings):
        return self.make_app(ITEM, [], settings={"deny_read": [str(self.secret)], **settings})

    def test_writes_inside_the_project_work_and_outside_are_denied(self):
        app = self.app()
        out = self.bash(app, "echo hi > inside.txt && cat inside.txt")
        self.assertEqual(out, "hi\n\n[exit 0]")
        outside = Path.home() / f".minimal-sandbox-test-{uuid.uuid4().hex[:8]}"
        try:
            out = self.bash(app, f"echo no > '{outside}'")
            self.assertIn("Operation not permitted", out)
            self.assertFalse(outside.exists())
        finally:
            outside.unlink(missing_ok=True)
        self.assertIn("[exit 0]", self.bash(app, f"echo tmp > '{os.path.realpath(self.tmp)}/sub.txt'"))

    def test_reading_a_denied_path_fails_but_other_reads_work(self):
        app = self.app()
        out = self.bash(app, f"cat '{self.secret}/key.txt'")
        self.assertIn("Operation not permitted", out)
        self.assertNotIn("top secret", out)
        self.assertIn("[exit 0]", self.bash(app, "ls /usr/bin > /dev/null"))

    def test_extra_write_opens_one_more_place(self):
        extra = Path.home() / f".minimal-sandbox-extra-{uuid.uuid4().hex[:8]}"
        extra.mkdir()
        try:
            app = self.app(extra_write=[str(extra)])
            self.assertIn("[exit 0]", self.bash(app, f"echo ok > '{extra}/f.txt'"))
            self.assertTrue((extra / "f.txt").exists())
        finally:
            for p in extra.glob("*"):
                p.unlink()
            extra.rmdir()

    def listener(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        self.addCleanup(server.close)
        server.settimeout(5)

        def accept():
            try:
                for _ in range(2):
                    server.accept()[0].close()
            except OSError:
                pass

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 6)
        return server.getsockname()[1]

    def test_network_is_blocked_by_default_and_allowed_by_setting(self):
        port = self.listener()
        command = f"exec 3<>/dev/tcp/127.0.0.1/{port}"
        denied = self.bash(self.app(), command)
        self.assertNotIn("[exit 0]", denied)
        self.assertIn("[exit 0]", self.bash(self.app(network="allow"), command))

    def test_sandbox_test_command_passes(self):
        app = self.app()
        out = app.registry.commands["sandbox"].run("test", app.context)
        self.assertEqual(
            out.splitlines(),
            ["PASS  write outside the project: blocked", "PASS  write inside the project: file created", "sandbox test: PASS"],
        )
        self.assertEqual(app.registry.status["sandbox"].render(app.context), "sandbox:sandbox-exec")


if __name__ == "__main__":
    unittest.main()
