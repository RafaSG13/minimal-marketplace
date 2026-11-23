"""Runs every `bash` call of the model inside an OS sandbox: it can write only in the project and the temp folder. Install it with `/ext`.

Minimal's ``bash`` tool gives the model your whole account. This extension wraps its command (API 2.5,
``set_command_wrapper``) so the process can read the disk (except the folders in ``deny_read``: ``~/.ssh``, ``~/.aws``,
``~/.config/gh``, minimal's keys), write only under the working folder, the temp folder and ``extra_write``, and use
the network only when ``network`` is ``allow``. Backends: ``sandbox-exec`` (macOS), ``bwrap`` (Linux, bubblewrap) and
``docker`` (explicit: runs in ``docker_image`` with the project mounted). With no backend the wrapper refuses the
call: bash never runs unsandboxed while ``enabled`` is true. ``/sandbox`` shows the policy; ``/sandbox test`` proves
it (a write outside the project must fail, one inside must work). The default ``network = "deny"`` also stops
``git push`` and ``npm install`` in ``bash``: set ``network`` to ``allow`` for those.

Settings (``/ext settings sandbox``): ``enabled``, ``backend`` (``auto``, ``sandbox-exec``, ``bwrap``, ``docker``),
``network``, ``extra_write``, ``deny_read`` and ``docker_image``. Only the ``bash`` tool is wrapped: the ``read``,
``write`` and ``edit`` tools and extensions' own processes are not sandboxed by this.
"""

import os
import platform
import shutil
import tempfile
import uuid

__version__ = "1.0"
__api__ = "2.5"
__tags__ = ["safety", "sandbox"]

DEFAULTS = {
    "enabled": True,
    "backend": "auto",
    "network": "deny",
    "extra_write": [],
    "deny_read": ["~/.ssh", "~/.aws", "~/.config/gh", "~/.minimal/keys.json"],
    "docker_image": "",
}

SCHEMA = {
    "enabled": {"description": "Wrap every bash call in the sandbox; false leaves bash unsandboxed."},
    "backend": {"description": "auto: sandbox-exec on macOS, bwrap on Linux; docker only when chosen (with docker_image).", "enum": ["auto", "sandbox-exec", "bwrap", "docker"]},
    "network": {"description": "deny blocks network access in bash (git push, npm install, curl); allow permits it.", "enum": ["deny", "allow"]},
    "extra_write": {"description": "Folders bash may also write to besides the project and the temp folder; ~ is expanded."},
    "deny_read": {"description": "Paths bash may not read (files or folders); ~ is expanded."},
    "docker_image": {"description": "Image for the docker backend (it needs a shell, e.g. debian:stable-slim)."},
}

NO_BACKEND = "sandbox: no backend found (sandbox-exec, bwrap); install one or set sandbox.enabled to false"


def expand(paths):
    """``paths`` with ``~`` expanded and symlinks resolved (a sandbox profile must name real paths)."""
    return [os.path.realpath(os.path.expanduser(p)) for p in paths]


def sbpl(path):
    """``path`` as a SBPL string literal."""
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def choose_backend(backend, system, which, docker_image):
    """The backend to use, or ``None``: ``auto`` picks by operating system; an explicit one must be installed."""
    if backend == "auto":
        if system == "Darwin" and which("sandbox-exec"):
            return "sandbox-exec"
        if system == "Linux" and which("bwrap"):
            return "bwrap"
        return None
    if backend == "docker":
        return "docker" if docker_image and which("docker") else None
    return backend if which(backend) else None


def sandbox_exec_profile(cwd, tmp, deny_read, extra_write, network):
    """The macOS Seatbelt profile: read everything but ``deny_read``, write only the given places."""
    lines = ["(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)(allow signal)(allow file-read*)"]
    lines += [f"(deny file-read* (subpath {sbpl(p)}))" for p in deny_read]
    writable = [f"(subpath {sbpl(cwd)})", f"(subpath {sbpl(tmp)})", '(literal "/dev/null")', '(literal "/dev/tty")']
    writable += [f"(subpath {sbpl(p)})" for p in extra_write]
    lines.append("(allow file-write* " + " ".join(writable) + ")")
    if network == "allow":
        lines.append("(allow network*)")
    return "\n".join(lines)


def sandbox_exec_argv(argv, cwd, tmp, deny_read, extra_write, network):
    return ["sandbox-exec", "-p", sandbox_exec_profile(cwd, tmp, deny_read, extra_write, network), *argv]


def bwrap_argv(argv, cwd, tmp, deny_read, extra_write, network, exists=os.path.exists, isdir=os.path.isdir):
    out = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--bind", cwd, cwd, "--bind", tmp, tmp]
    for path in extra_write:
        out += ["--bind", path, path]
    for path in deny_read:
        if isdir(path):
            out += ["--tmpfs", path]
        elif exists(path):
            out += ["--ro-bind", "/dev/null", path]
    if network == "deny":
        out.append("--unshare-net")
    return [*out, "--die-with-parent", "--chdir", cwd, *argv]


def docker_argv(argv, cwd, image, network):
    out = ["docker", "run", "--rm", "-i", "-v", f"{cwd}:{cwd}", "-w", cwd]
    if network == "deny":
        out += ["--network", "none"]
    return [*out, image, *argv]


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    backend = choose_backend(settings["backend"], platform.system(), shutil.which, settings["docker_image"])
    if backend is None:
        wanted = settings["backend"]
        detail = "set docker_image and install docker" if wanted == "docker" else f"{wanted} is not installed" if wanted != "auto" else "none of sandbox-exec (macOS) or bwrap (Linux) is installed"
        minimal.report_problem(f"{detail}; every bash call is refused until you install a backend or set enabled to false")

    def policy(ctx):
        tmp = os.path.realpath(tempfile.gettempdir())
        return {
            "cwd": os.path.realpath(ctx.cwd),
            "tmp": tmp,
            "deny_read": expand(settings["deny_read"]),
            "extra_write": expand(settings["extra_write"]),
            "network": settings["network"],
        }

    def wrap(argv, ctx):
        if backend is None:
            raise RuntimeError(NO_BACKEND)
        p = policy(ctx)
        args = (argv, p["cwd"], p["tmp"], p["deny_read"], p["extra_write"], p["network"])
        if backend == "sandbox-exec":
            return sandbox_exec_argv(*args)
        if backend == "bwrap":
            return bwrap_argv(*args)
        return docker_argv(argv, p["cwd"], settings["docker_image"], p["network"])

    minimal.set_command_wrapper(wrap)

    def status(ctx):
        return f"sandbox:{backend}" if backend else ("sandbox:none", "error")

    minimal.register_status("sandbox", status, "left")

    def describe(ctx):
        p = policy(ctx)
        writable = [p["cwd"], p["tmp"], *p["extra_write"]]
        return "\n".join(
            [
                f"backend: {backend or 'none (bash is refused)'}",
                f"network: {p['network']}",
                "writable: " + ", ".join(writable),
                "unreadable: " + (", ".join(p["deny_read"]) or "(nothing)"),
                "/sandbox test checks that these rules hold.",
            ]
        )

    def probe(ctx):
        bash = ctx.tools["bash"]
        home_probe = os.path.join(os.path.expanduser("~"), f".minimal-sandbox-probe-{uuid.uuid4().hex[:8]}")
        inside = os.path.join(os.path.realpath(ctx.cwd), f".minimal-sandbox-probe-{uuid.uuid4().hex[:8]}")
        results = []
        try:
            for label, path, must_exist in (("write outside the project", home_probe, False), ("write inside the project", inside, True)):
                try:
                    bash.run({"command": f"echo probe > '{path}'", "timeout_ms": 15000}, ctx)
                except Exception as e:  # the wrapper refusing the call is a failure of the test
                    results.append(f"FAIL  {label}: {e}")
                    continue
                present = os.path.exists(path)
                results.append(f"{'PASS' if present == must_exist else 'FAIL'}  {label}: {'file created' if present else 'blocked'}")
        finally:
            for path in (home_probe, inside):
                try:
                    os.remove(path)
                except OSError:
                    pass
        verdict = "PASS" if all(r.startswith("PASS") for r in results) else "FAIL"
        return "\n".join([*results, f"sandbox test: {verdict}"])

    def sandbox(args, ctx):
        word = args.strip()
        if not word:
            return describe(ctx)
        if word == "test":
            return probe(ctx)
        return "usage: /sandbox [test]"

    minimal.register_command("sandbox", sandbox, description="show the bash sandbox policy; /sandbox test proves it", complete=lambda args, ctx: [w for w in ("test",) if w.startswith(args)])
