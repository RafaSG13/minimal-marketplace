"""Reviews a diff with parallel reviewer agents, one per lens (correctness, security, tests, maintainability), and writes one report.

``/review`` (no argument: the current branch against the default branch; ``<n>``: GitHub pull request n through
``gh``; ``<base>..<head>``; ``--staged``) and the tool ``review_changes`` split the diff into chunks and give every lens
x chunk to its own agent that may only use read-only tools. Findings are parsed from JSON, checked against the diff's
hunks (a finding on a line the diff does not show goes under *Unanchored*), de-duplicated and sorted by severity. The
report is saved under the project's data folder (``reviews/``) and shown. For a pull request it offers to post the
anchored findings as a review (``post``: ``ask`` or ``never``). It spends model tokens: one request loop per lens and
chunk. Settings (``/ext settings pr_review``): ``lenses``, ``max_parallel``, ``chunk_chars``, ``max_turns``, ``post``,
``model`` and ``reasoning_effort`` (empty: the current ones).

Install it with ``/ext``. Needs ``git``; pull requests need ``gh``.
"""

import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["agents", "github", "git"]

DEFAULTS = {
    "lenses": ["correctness", "security", "tests", "maintainability"],
    "max_parallel": 4,
    "chunk_chars": 40000,
    "max_turns": 12,
    "post": "ask",
    "model": "",
    "reasoning_effort": "",
}

SCHEMA = {
    "lenses": {"description": "The angles to review from; each one is a reviewer agent per chunk of the diff."},
    "max_parallel": {"description": "Reviewer agents that run at the same time.", "min": 1, "max": 16},
    "chunk_chars": {"description": "Largest piece of the diff one reviewer reads, in characters.", "min": 2000, "max": 500_000},
    "max_turns": {"description": "Most model requests one reviewer may make.", "min": 1, "max": 100},
    "post": {"description": "For a pull request: ask before posting the findings as a review, or never post.", "enum": ["ask", "never"]},
    "model": {"description": "Model for the reviewers (empty: the current one)."},
    "reasoning_effort": {"description": "Reasoning effort of the reviewers (empty: the current one).", "enum": ["", "low", "medium", "high"]},
}

SEVERITIES = ("blocker", "major", "minor", "nit")

REVIEW_SYSTEM = """You are a code reviewer. Review ONLY through this lens: {lens}. Ignore everything else.
You receive part of a diff. Use the read-only tools to open the surrounding code and verify a claim before you make it; do not guess.
Report only real problems in lines the diff adds or changes. For every finding give the file (as in the diff), the line number in the NEW file,
a severity (blocker, major, minor or nit), a short title, the detail, and a concrete suggestion.
Your final message must contain exactly one fenced ```json code block holding an array of objects with the keys
"file", "line", "severity", "title", "detail", "suggestion", and nothing else of substance. When you find nothing, the block is [].
"""

SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")
"""Variables a child process never inherits."""
CAPTURE = 1_000_000
"""Bytes kept of each stream of a command; the rest is read and dropped."""


def _env():
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", PAGER="cat", GIT_PAGER="cat", NO_COLOR="1")
    return env


def _drain(pipe, chunks):
    kept = 0
    for chunk in iter(lambda: pipe.read(65536), b""):
        if kept < CAPTURE:
            chunks.append(chunk[: CAPTURE - kept])
            kept += len(chunk)


def _run(argv, cwd, timeout, ctx, env=None, stdin=None):
    """Run ``argv`` in ``cwd``; return ``(exit code, stdout, stderr)``.

    The command gets its own process group: a timeout or the user's interrupt kills all of it. Raises ``RuntimeError``
    for either (``<program> timed out after Ns`` / ``interrupted``).
    """
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=_env() if env is None else env,
        stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    out, err = [], []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        if stdin is not None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass
            failure = None
            if ctx.cancelled:
                failure = "interrupted"
            elif time.monotonic() >= deadline:
                failure = f"{os.path.basename(argv[0])} timed out after {timeout}s"
            if failure:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
                raise RuntimeError(failure)
    finally:
        for reader in readers:
            reader.join(2)
        proc.stdout.close()
        proc.stderr.close()
    return proc.returncode, _decode(out), _decode(err)


def _decode(chunks):
    return b"".join(chunks).decode("utf-8", errors="replace").replace("\r\n", "\n")


def _clip(text, limit, how):
    """``text`` cut to ``limit`` characters, ending with how to narrow the call."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[clipped {len(text) - limit} chars; {how}]"



def split_chunks(diff, limit):
    """``(chunks, partial)``: the ``diff --git`` sections packed into texts of at most ``limit`` characters, and the
    files whose section alone is longer (their chunk is cut)."""
    sections = [s for s in re.split(r"(?m)^(?=diff --git )", diff) if s.strip()]
    chunks, partial, current = [], [], ""
    for section in sections:
        if len(section) > limit:
            if current:
                chunks.append(current)
                current = ""
            m = re.match(r"diff --git a/(.*?) b/(.*)\n", section)
            partial.append(m.group(2) if m else section.splitlines()[0])
            chunks.append(section[:limit])
        elif len(current) + len(section) > limit:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)
    return chunks, partial


def anchors(diff):
    """``{file: set of new-file line numbers}`` the diff shows (added and context lines)."""
    found = {}
    path, line = None, 0
    for text in diff.splitlines():
        if text.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", text)
            path = m.group(2) if m else None
            line = 0
            if path:
                found.setdefault(path, set())
        elif text.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", text)
            line = int(m.group(1)) if m else 0
        elif path and line and not text.startswith(("---", "+++", "\\")):
            if text.startswith("-"):
                continue
            found[path].add(line)
            line += 1
    return found


def parse_findings(text):
    """The findings of the last ```json fence of ``text``; ``ValueError`` if there is none or it is malformed."""
    fences = re.findall(r"```json\s*\n(.*?)```", text, re.S)
    if not fences:
        raise ValueError("no ```json block in the reply")
    try:
        data = json.loads(fences[-1])
    except ValueError as e:
        raise ValueError(f"the ```json block is not valid JSON ({e})") from None
    if not isinstance(data, list):
        raise ValueError("the ```json block is not an array")
    findings = []
    for item in data:
        if not isinstance(item, dict) or not all(k in item for k in ("file", "line", "severity", "title")):
            raise ValueError("a finding lacks file, line, severity or title")
        try:
            line = int(item["line"])
        except (TypeError, ValueError):
            raise ValueError(f"a finding has a line that is not a number: {item['line']!r}") from None
        severity = str(item["severity"]).lower()
        findings.append(
            {
                "file": re.sub(r"^(\./|b/)", "", str(item["file"]).strip()),
                "line": line,
                "severity": severity if severity in SEVERITIES else "minor",
                "title": str(item["title"]).strip(),
                "detail": str(item.get("detail") or "").strip(),
                "suggestion": str(item.get("suggestion") or "").strip(),
            }
        )
    return findings


def render(findings, unanchored, not_parsed, partial, header):
    """The Markdown report."""
    counts = {s: sum(1 for f in findings + unanchored if f["severity"] == s) for s in SEVERITIES}
    lines = [f"# Review: {header}", "", "Findings: " + ", ".join(f"{n} {s}" for s, n in counts.items()), ""]

    def one(f):
        out = [f"**{f['severity']}** {f['file']}:{f['line']} {f['title']}"]
        if f["detail"]:
            out.append(f["detail"])
        if f["suggestion"]:
            out.append(f"Suggestion: {f['suggestion']}")
        return "\n".join(out) + "\n"

    lines += [one(f) for f in findings] or ["No findings anchored to the diff.\n"]
    if unanchored:
        lines += ["## Unanchored", "(the file or line is not part of the diff)", ""] + [one(f) for f in unanchored]
    if not_parsed:
        lines += ["## Not parsed", ""] + [f"- {lens}: {why}\n{text[:1500]}\n" for lens, why, text in not_parsed]
    if partial:
        lines += ["## Partially reviewed", "(too large for one reviewer; cut to chunk_chars)", ""] + [f"- {p}" for p in partial]
    return "\n".join(lines).rstrip() + "\n"


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def run(argv, ctx, stdin=None):
        code, out, err = _run(argv, ctx.cwd, 60, ctx, stdin=stdin)
        if code != 0:
            raise RuntimeError(f"{os.path.basename(argv[0])} {argv[1]} failed (exit {code}): {(err.strip() or out.strip())[:500]}")
        return out

    def git(*args, ctx):
        exe = shutil.which("git")
        if exe is None:
            raise ValueError("git is not installed or not on PATH; install it with brew install git")
        return run([exe, *args], ctx)

    def gh(*args, ctx, stdin=None):
        exe = shutil.which("gh")
        if exe is None:
            raise ValueError("gh is not installed or not on PATH; install it with brew install gh, then run `gh auth login`")
        try:
            return run([exe, *args], ctx, stdin)
        except RuntimeError as e:
            if "gh auth login" in str(e):
                raise RuntimeError("gh is not authenticated; run `gh auth login`") from None
            raise

    def default_branch(ctx):
        exe = shutil.which("git")
        if exe is None:
            raise ValueError("git is not installed or not on PATH; install it with brew install git")
        code, out, _ = _run([exe, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], ctx.cwd, 10, ctx)
        if code == 0 and out.strip().startswith("origin/"):
            return out.strip()
        for name in ("main", "master"):
            if _run([exe, "rev-parse", "--verify", "-q", name], ctx.cwd, 10, ctx)[0] == 0:
                return name
        raise ValueError("no main or master branch to compare with; pass a target: /review <base>..<head>")

    def get_diff(target, ctx):
        """``(diff, label, pull request number or None)``."""
        target = (target or "").strip()
        if target == "--staged":
            return git("diff", "--no-ext-diff", "--cached", ctx=ctx), "staged changes", None
        if target.isdigit():
            return gh("pr", "diff", target, "--color=never", ctx=ctx), f"pull request #{target}", int(target)
        if ".." in target:
            base, _, head = target.partition("..")
            head = head.lstrip(".")
            for part in (base, head):
                if not part or part.startswith("-"):
                    raise ValueError("target must look like <base>..<head>, a pull request number or --staged")
            return git("diff", "--no-ext-diff", f"{base}...{head}", ctx=ctx), f"{base}...{head}", None
        if target:
            raise ValueError("target must be a pull request number, <base>..<head> or --staged (none: this branch against the default one)")
        base = default_branch(ctx)
        return git("diff", "--no-ext-diff", f"{base}...HEAD", ctx=ctx), f"{base}...HEAD", None

    def reviewer_tools(ctx):
        return [name for name, tool in ctx.tools.items() if tool.read_only is True]

    def review(target, lenses, ctx):
        lenses = lenses or settings["lenses"]
        if not isinstance(lenses, list) or not lenses or not all(isinstance(x, str) and x.strip() for x in lenses):
            raise ValueError("lenses must be a non-empty list of names such as correctness or security")
        diff, label, number = get_diff(target, ctx)
        if not diff.strip():
            return "no changes to review"
        chunks, partial = split_chunks(diff, settings["chunk_chars"])
        tools = reviewer_tools(ctx)
        jobs = [(lens, i, chunk) for lens in lenses for i, chunk in enumerate(chunks)]

        def work(job):
            lens, i, chunk = job
            prompt = f"Review this part of the diff ({i + 1} of {len(chunks)}).\n\n{chunk}"
            return job, ctx.run_agent_result(
                prompt,
                name=f"review:{lens}",
                system=REVIEW_SYSTEM.replace("{lens}", lens),
                tools=tools,
                max_turns=settings["max_turns"],
                model=settings["model"] or None,
                reasoning_effort=settings["reasoning_effort"] or None,
                cwd=ctx.cwd,
            )

        findings, not_parsed = [], []
        ctx.progress(f"reviewing {label}: {len(jobs)} reviewer(s)", key="pr_review")
        try:
            with ThreadPoolExecutor(max_workers=settings["max_parallel"]) as pool:
                results = list(pool.map(work, jobs))
        finally:
            ctx.progress(None, key="pr_review")
        for (lens, i, _), result in results:
            where = lens if len(chunks) == 1 else f"{lens} (part {i + 1})"
            if result.status != "done":
                not_parsed.append((where, f"the reviewer ended with status {result.status}" + (f": {result.error}" if result.error else ""), result.text))
                continue
            try:
                findings += parse_findings(result.text)
            except ValueError as e:
                not_parsed.append((where, str(e), result.text))
        shown = anchors(diff)
        anchored, unanchored, seen = [], [], set()
        for f in findings:
            key = (f["file"], f["line"], f["title"].lower())
            if key in seen:
                continue
            seen.add(key)
            (anchored if f["line"] in shown.get(f["file"], ()) else unanchored).append(f)
        order = lambda f: (SEVERITIES.index(f["severity"]), f["file"], f["line"])  # noqa: E731
        anchored.sort(key=order)
        unanchored.sort(key=order)
        report = render(anchored, unanchored, not_parsed, partial, label)
        folder = minimal.data_dir("project") / "reviews"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(report, encoding="utf-8")
        report += f"\nSaved to {path}\n"
        if number is not None and anchored and settings["post"] != "never":
            report += post(number, anchored, counts_line(report), ctx)
        return report

    def counts_line(report):
        return next((l for l in report.splitlines() if l.startswith("Findings:")), "Findings:")

    def post(number, anchored, summary, ctx):
        if not ctx.ui.ask(f"Post {len(anchored)} findings as a review on PR #{number}?"):
            return "Not posted (declined).\n"
        name = json.loads(gh("repo", "view", "--json", "nameWithOwner", ctx=ctx))["nameWithOwner"]
        body = {
            "event": "COMMENT",
            "body": f"Automated review by minimal. {summary}",
            "comments": [
                {
                    "path": f["file"],
                    "line": f["line"],
                    "side": "RIGHT",
                    "body": f"**{f['severity']}** {f['title']}\n\n{f['detail']}" + (f"\n\nSuggestion: {f['suggestion']}" if f["suggestion"] else ""),
                }
                for f in anchored
            ],
        }
        gh("api", f"repos/{name}/pulls/{number}/reviews", "-X", "POST", "--input", "-", ctx=ctx, stdin=json.dumps(body))
        return f"Posted {len(anchored)} findings to PR #{number}.\n"

    def review_command(args, ctx):
        try:
            ctx.show(review(args.strip(), None, ctx))
        except (ValueError, RuntimeError) as e:
            ctx.show(f"/review: {e}", "error")

    minimal.register_command("review", review_command, description="review the branch's changes with reviewer agents: /review [<pr-number> | <base>..<head> | --staged]")

    minimal.register_tool(
        "review_changes",
        lambda input, ctx: review(input.get("target"), input.get("lenses"), ctx),
        "Review a diff with parallel reviewer agents (one per lens and chunk) and return a Markdown report of anchored findings. "
        "It SPENDS MODEL TOKENS (several agent loops): use it when the user asks for a review, not for every change. "
        "target: a pull request number, <base>..<head>, --staged, or empty for this branch against the default one.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "PR number, base..head, --staged; empty: this branch vs the default branch"},
                "lenses": {"type": "array", "items": {"type": "string"}, "description": "Override the configured lenses"},
            },
        },
        confirm=False,
        read_only=False,
    )
