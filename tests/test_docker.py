"""tools/docker: a fake ``docker`` on PATH records its argv and prints canned output."""

import json
import os
import unittest
from unittest import mock

from support import ItemTest, have

ITEM = "tools/docker.py"
PS = "\n".join(
    json.dumps(r)
    for r in (
        {"Names": "web", "Image": "nginx:1", "Status": "Up 2 hours", "Ports": "0.0.0.0:80->80/tcp"},
        {"Names": "db", "Image": "postgres:16", "Status": "Exited (0) 1 day ago", "Ports": ""},
    )
)


@unittest.skipUnless(have("sh") and have("python3"), "needs sh and python3")
class DockerTest(ItemTest):
    def tool(self, name, outputs=None, input=None, **fake):
        self.cli = self.fake_cli("docker", outputs, **fake)
        registry, errors = self.load(ITEM, **self.settings) if getattr(self, "settings", None) else self.load(ITEM)
        self.assertEqual(errors, [])
        self.registry = registry
        return registry.tools[name].run(input or {}, self.ctx())

    def test_flags_of_every_tool(self):
        registry, _ = self.load(ITEM)
        for name in ("docker_ps", "docker_images", "docker_logs", "docker_inspect", "docker_stats"):
            tool = registry.tools[name]
            self.assertTrue(tool.read_only is True and not tool.confirm, name)
            self.assertIn("Prefer it over `bash docker", tool.description)
        for name in ("docker_exec", "docker_container"):
            self.assertTrue(registry.tools[name].confirm is True and not registry.tools[name].read_only, name)
        self.assertEqual(registry.tools["docker_exec"].subject_key, "container")
        self.assertEqual(sorted(registry.tools).count("docker_compose"), 1)

    def test_compose_is_read_only_exactly_for_ps_config_logs(self):
        tool = self.load(ITEM)[0].tools["docker_compose"]
        ctx = self.ctx()
        for action in ("ps", "config", "logs"):
            self.assertEqual((tool.read_only({"action": action}, ctx), tool.confirm({"action": action}, ctx)), (True, False), action)
        for action in ("up", "down", "restart", "stop", "start", "build", "nonsense"):
            self.assertEqual((tool.read_only({"action": action}, ctx), tool.confirm({"action": action}, ctx)), (False, True), action)

    def test_ps_and_images_and_stats_render_compact_lines(self):
        out = self.tool("docker_ps", {"ps": PS}, {"all": True})
        self.assertEqual(self.cli.calls(), [["ps", "-a", "--format", "{{json .}}"]])
        self.assertEqual(
            out, "web  nginx:1      Up 2 hours            0.0.0.0:80->80/tcp\ndb   postgres:16  Exited (0) 1 day ago"
        )
        out = self.tool("docker_images", {"images": json.dumps({"Repository": "nginx", "Tag": "1", "ID": "abc", "Size": "1MB", "CreatedSince": "2 days ago"})})
        self.assertEqual(out, "nginx:1  abc  1MB  2 days ago")
        stats = json.dumps({"Name": "web", "CPUPerc": "1%", "MemUsage": "5MiB / 1GiB", "MemPerc": "0.5%", "NetIO": "1kB / 2kB", "PIDs": "3"})
        out = self.tool("docker_stats", {"stats": stats})
        self.assertEqual(self.cli.calls()[-1], ["stats", "--no-stream", "--format", "{{json .}}"])
        self.assertEqual(out.splitlines()[1].split(), ["web", "1%", "5MiB", "/", "1GiB", "0.5%", "1kB", "/", "2kB", "3"])
        self.assertEqual(self.tool("docker_ps", {"ps": ""}), "(no containers)")

    def test_logs_merge_streams_filter_with_grep_and_cap_tail(self):
        out = self.tool(
            "docker_logs", {"logs": "ok 1\nERROR boom\nok 2\n", "stderr": "ERROR again\n"}, {"container": "web", "tail": 99999, "since": "10m", "grep": "ERROR"}
        )
        self.assertEqual(self.cli.calls(), [["logs", "--tail", "2000", "--since", "10m", "web"]])
        self.assertEqual(out, "ERROR boom\nERROR again\n")
        with self.assertRaisesRegex(ValueError, "^grep is not a valid regular expression"):
            self.registry.tools["docker_logs"].run({"container": "web", "grep": "("}, self.ctx())

    def test_logs_tail_is_capped_by_the_setting(self):
        self.settings = {"logs_max": 5}
        self.tool("docker_logs", {"logs": "x"}, {"container": "web"})
        self.assertEqual(self.cli.calls(), [["logs", "--tail", "5", "web"]])
        self.assertEqual(self.registry.tools["docker_logs"].input_schema["properties"]["tail"]["description"], "Lines from the end (default 200, at most 5)")

    def test_inspect_passes_the_format_attached(self):
        self.tool("docker_inspect", {"inspect": "running"}, {"target": "web", "format": "{{.State.Status}}"})
        self.assertEqual(self.cli.calls(), [["inspect", "--format={{.State.Status}}", "web"]])

    def test_compose_argv_up_is_detached_and_down_never_removes_volumes(self):
        for action, expected in (
            ("ps", ["compose", "-f", "c.yml", "ps", "api"]),
            ("up", ["compose", "-f", "c.yml", "up", "-d", "api"]),
            ("down", ["compose", "-f", "c.yml", "down", "api"]),
            ("logs", ["compose", "-f", "c.yml", "logs", "--no-color", "--tail", "50", "api"]),
            ("build", ["compose", "-f", "c.yml", "build", "api"]),
        ):
            with self.subTest(action):
                self.tool("docker_compose", {"compose": "ok\n"}, {"action": action, "service": "api", "file": "c.yml", "tail": 50})
                self.assertEqual(self.cli.calls()[-1], expected)
        self.assertNotIn("-v", self.cli.calls()[-1])

    def test_exec_runs_an_argv_without_a_shell(self):
        out = self.tool("docker_exec", {"exec": "total 0\n"}, {"container": "web", "command": ["ls", "-la", "; rm -rf /"]})
        self.assertEqual(self.cli.calls(), [["exec", "web", "ls", "-la", "; rm -rf /"]])
        self.assertEqual(out, "total 0\n")
        with self.assertRaisesRegex(ValueError, "^command must be a non-empty list of strings"):
            self.registry.tools["docker_exec"].run({"container": "web", "command": "ls -la"}, self.ctx())

    def test_container_start_stop_restart_only(self):
        self.assertEqual(self.tool("docker_container", {"stop": "web\ndb\n"}, {"action": "stop", "containers": ["web", "db"]}), "stop: web, db")
        self.assertEqual(self.cli.calls(), [["stop", "web", "db"]])
        for action in ("rm", "kill"):
            with self.assertRaisesRegex(ValueError, "^action must be start, stop or restart"):
                self.registry.tools["docker_container"].run({"action": action, "containers": ["web"]}, self.ctx())

    def test_names_that_could_be_options_are_rejected_before_docker_runs(self):
        self.tool("docker_images", {"images": ""})
        for tool, input in (
            ("docker_logs", {"container": "--help"}),
            ("docker_inspect", {"target": "-f"}),
            ("docker_exec", {"container": "a b", "command": ["ls"]}),
            ("docker_container", {"action": "stop", "containers": ["ok", "$(x)"]}),
            ("docker_compose", {"action": "ps", "service": "-x"}),
        ):
            with self.assertRaisesRegex(ValueError, "is not a valid name"):
                self.registry.tools[tool].run(input, self.ctx())
        self.assertEqual(len(self.cli.calls()), 1)  # only the images call above reached docker

    def test_daemon_down_and_other_failures_say_what_to_do(self):
        with self.assertRaises(RuntimeError) as caught:
            self.tool("docker_ps", stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock.", exit=1)
        self.assertEqual(str(caught.exception), "the Docker daemon is not running; start Docker Desktop and retry")
        with self.assertRaisesRegex(RuntimeError, r"^docker inspect failed \(exit 1\): Error: No such object: nope$"):
            self.tool("docker_inspect", stderr="Error: No such object: nope\n", exit=1, input={"target": "nope"})

    def test_missing_binary_gives_the_install_hint(self):
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            with self.assertRaises(ValueError) as caught:
                registry.tools["docker_ps"].run({}, self.ctx())
        self.assertEqual(
            str(caught.exception),
            "docker is not installed or not on PATH; install it with Docker Desktop or brew install --cask docker",
        )

    def test_long_output_is_clipped_with_a_hint(self):
        self.settings = {"max_chars": 1000}
        out = self.tool("docker_logs", {"logs": "line\n" * 1000}, {"container": "web"})
        self.assertRegex(out, r"\n\[clipped 4000 chars; lower tail or pass since or grep\]$")


if __name__ == "__main__":
    unittest.main()
