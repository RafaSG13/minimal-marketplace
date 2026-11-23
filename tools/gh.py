"""GitHub tools for the model through the ``gh`` CLI: pull requests, issues and workflow runs (read-only) and comments, reviews and PR creation (they ask first).

Prefer them over ``bash gh ...``: compact text from fixed ``--json`` fields, bounded diffs and logs, read calls in
parallel with no prompt, and comment bodies sent on stdin (no shell quoting). Needs the GitHub CLI, signed in
(``gh auth login``); the optional ``repo`` input (``owner/name``) targets another repository. Settings (``/ext settings
tools/gh``): ``max_chars`` (output cut) and ``timeout`` (seconds per command).

Install it with ``/ext``.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["github"]

DEFAULTS = {"max_chars": 30000, "timeout": 60}

SCHEMA = {
    "max_chars": {"description": "Longest output of one call in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "timeout": {"description": "Seconds one gh command may run before it is killed.", "min": 1, "max": 600},
}

REPO = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+")
FAIL = ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR")
PASS = ("SUCCESS", "NEUTRAL", "SKIPPED")

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



def _number(input, required=False):
    value = input.get("number")
    if value is None:
        if required:
            raise ValueError("number is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("number must be a positive integer")
    return value


def _plain(field, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if value.startswith("-"):
        raise ValueError(f"{field} must not start with '-'")
    return value


def _body(input):
    body = input.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body is required: write the text to post")
    return body


def _name(user):
    return (user or {}).get("login", "?") if isinstance(user, dict) else "?"


def _check_state(check):
    """``pass``, ``fail`` or ``pending`` for one entry of ``statusCheckRollup``."""
    verdict = (check.get("conclusion") or check.get("state") or "").upper()
    if verdict in PASS:
        return "pass"
    if verdict in FAIL:
        return "fail"
    return "pending"


def _sections(diff):
    """``(b-path, text)`` of every ``diff --git`` section of ``diff``."""
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    found = []
    for part in parts:
        m = re.match(r"diff --git a/(.*?) b/(.*)\n", part)
        if m:
            found.append((m.group(2), part))
    return found


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def gh(args, input, ctx, *, stdin=None, ok=(0,)):
        """Run ``gh <args>`` (with ``-R`` for a ``repo`` input); ``(stdout, stderr)``."""
        exe = shutil.which("gh")
        if exe is None:
            raise ValueError("gh is not installed or not on PATH; install it with brew install gh, then run `gh auth login`")
        repo = input.get("repo")
        if repo is not None:
            if not isinstance(repo, str) or not REPO.fullmatch(repo):
                raise ValueError("repo must look like owner/name")
            args = [*args, "-R", repo]
        env = {**_env(), "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        code, out, err = _run([exe, *args], ctx.cwd, settings["timeout"], ctx, env=env, stdin=stdin)
        if code not in ok:
            if "gh auth login" in err:
                raise RuntimeError("gh is not authenticated; run `gh auth login`")
            raise RuntimeError(f"gh {' '.join(args[:2])} failed (exit {code}): {(err.strip() or out.strip())[:500]}")
        return out, err

    def fetch(args, input, ctx, **kw):
        out, _ = gh(args, input, ctx, **kw)
        try:
            return json.loads(out)
        except ValueError:
            raise RuntimeError(f"gh {' '.join(args[:2])} returned something that is not JSON: {out[:200]}") from None

    def target(input):
        number = _number(input)
        return [str(number)] if number else []

    def clip(text, how):
        return _clip(text, settings["max_chars"], how)

    def pr_view(input, ctx):
        fields = "number,title,state,author,baseRefName,headRefName,reviewDecision,statusCheckRollup,files,body,url,isDraft"
        pr = fetch(["pr", "view", *target(input), "--json", fields], input, ctx)
        counts = {"pass": 0, "fail": 0, "pending": 0}
        for check in pr.get("statusCheckRollup") or []:
            counts[_check_state(check)] += 1
        files = pr.get("files") or []
        lines = [
            f"#{pr['number']} {pr['title']} [{pr['state']}{', draft' if pr.get('isDraft') else ''}] by {_name(pr.get('author'))}",
            f"{pr['baseRefName']} <- {pr['headRefName']}  review: {pr.get('reviewDecision') or 'none'}",
            pr.get("url", ""),
            f"checks: {counts['pass']} passing, {counts['fail']} failing, {counts['pending']} pending",
            f"files ({len(files)}):",
            *[f"  {f['path']} +{f.get('additions', 0)} -{f.get('deletions', 0)}" for f in files],
            "",
            (pr.get("body") or "").strip() or "(no description)",
        ]
        return clip("\n".join(lines), "ask for the diff of one file with gh_pr_diff")

    def pr_diff(input, ctx):
        out, _ = gh(["pr", "diff", *target(input), "--color=never"], input, ctx)
        path = input.get("path")
        if path:
            found = [text for name, text in _sections(out) if name == path]
            if not found:
                names = ", ".join(name for name, _ in _sections(out)[:10])
                raise ValueError(f"no section for {path} in the diff; files in it: {names or '(none)'}")
            out = "".join(found)
        limit = settings["max_chars"]
        if input.get("max_chars") is not None:
            if isinstance(input["max_chars"], bool) or not isinstance(input["max_chars"], int):
                raise ValueError("max_chars must be an integer")
            limit = max(1000, min(limit, input["max_chars"]))
        return _clip(out, limit, "pass path to read one file's diff") if out.strip() else "(empty diff)"

    def pr_list(input, ctx):
        state = input.get("state", "open")
        if state not in ("open", "closed", "merged", "all"):
            raise ValueError("state must be open, closed, merged or all")
        limit = input.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        args = ["pr", "list", "--state", state, "--limit", str(max(1, min(100, limit)))]
        if input.get("author"):
            args.append(f"--author={_plain('author', input['author'])}")
        if input.get("label"):
            args.append(f"--label={_plain('label', input['label'])}")
        prs = fetch([*args, "--json", "number,title,author,state,headRefName,isDraft"], input, ctx)
        if not prs:
            return "(no pull requests)"
        return clip(
            "\n".join(
                f"#{p['number']} [{p['state'].lower()}{', draft' if p.get('isDraft') else ''}] {p['title']} ({_name(p.get('author'))}, {p['headRefName']})"
                for p in prs
            ),
            "lower limit or filter by author or label",
        )

    def pr_checks(input, ctx):
        # gh exits 8 while checks are pending and 1 when one failed; the JSON is still printed
        checks = fetch(["pr", "checks", *target(input), "--json", "name,state,link,workflow"], input, ctx, ok=(0, 1, 8))
        if not checks:
            return "(no checks)"
        return clip(
            "\n".join(f"{c.get('state', '?'):<10} {c.get('workflow') or '-'} / {c['name']}  {c.get('link', '')}" for c in checks),
            "there are many checks",
        )

    def issue_view(input, ctx):
        number = _number(input, required=True)
        fields = "number,title,state,author,labels,body,url" + (",comments" if input.get("comments") else "")
        issue = fetch(["issue", "view", str(number), "--json", fields], input, ctx)
        labels = ", ".join(l["name"] for l in issue.get("labels") or []) or "none"
        lines = [
            f"#{issue['number']} {issue['title']} [{issue['state']}] by {_name(issue.get('author'))}",
            f"labels: {labels}",
            issue.get("url", ""),
            "",
            (issue.get("body") or "").strip() or "(no description)",
        ]
        for c in issue.get("comments") or []:
            lines += ["", f"--- {_name(c.get('author'))}:", (c.get("body") or "").strip()]
        return clip("\n".join(lines), "read without comments=true")

    def issue_list(input, ctx):
        state = input.get("state", "open")
        if state not in ("open", "closed", "all"):
            raise ValueError("state must be open, closed or all")
        limit = input.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        args = ["issue", "list", "--state", state, "--limit", str(max(1, min(100, limit)))]
        if input.get("author"):
            args.append(f"--author={_plain('author', input['author'])}")
        if input.get("label"):
            args.append(f"--label={_plain('label', input['label'])}")
        issues = fetch([*args, "--json", "number,title,state,author,labels"], input, ctx)
        if not issues:
            return "(no issues)"
        return clip(
            "\n".join(
                f"#{i['number']} [{i['state'].lower()}] {i['title']} ({_name(i.get('author'))})"
                + (f" {{{', '.join(l['name'] for l in i['labels'])}}}" if i.get("labels") else "")
                for i in issues
            ),
            "lower limit or filter by author or label",
        )

    def run_view(input, ctx):
        run_id = input.get("run_id")
        if run_id is None:
            branch_out, _ = _git_branch(ctx)
            args = ["run", "list", "--limit", "1", "--json", "databaseId,status,conclusion,name"]
            if branch_out:
                args += ["--branch", branch_out]
            runs = fetch(args, input, ctx)
            if not runs:
                return "(no workflow runs" + (f" on {branch_out}" if branch_out else "") + ")"
            run_id = runs[0]["databaseId"]
        if isinstance(run_id, bool) or not isinstance(run_id, (int, str)) or not str(run_id).isdigit():
            raise ValueError("run_id must be a number")
        args = ["run", "view", str(run_id)]
        if input.get("failed_only"):
            args.append("--log-failed")
        out, _ = gh(args, input, ctx)
        if not out.strip():
            return f"run {run_id}: no failed steps to show" if input.get("failed_only") else f"run {run_id}: (no output)"
        limit = settings["max_chars"]
        if len(out) <= limit:
            return out
        return f"{out[-limit:]}\n[clipped {len(out) - limit} chars; the start of the log was cut (failures are at the end); pass failed_only=true]"

    def _git_branch(ctx):
        git = shutil.which("git")
        if git is None:
            return "", ""
        code, out, err = _run([git, "rev-parse", "--abbrev-ref", "HEAD"], ctx.cwd, 10, ctx)
        name = out.strip()
        return ("" if code != 0 or name == "HEAD" else name), err

    def pr_comment(input, ctx):
        out, _ = gh(["pr", "comment", *target(input), "-F", "-"], input, ctx, stdin=_body(input))
        return out.strip() or "comment posted"

    def issue_comment(input, ctx):
        out, _ = gh(["issue", "comment", str(_number(input, required=True)), "-F", "-"], input, ctx, stdin=_body(input))
        return out.strip() or "comment posted"

    def pr_review(input, ctx):
        action = input.get("action")
        flags = {"approve": "--approve", "request_changes": "--request-changes", "comment": "--comment"}
        if action not in flags:
            raise ValueError("action must be approve, request_changes or comment")
        out, _ = gh(["pr", "review", *target(input), flags[action], "-F", "-"], input, ctx, stdin=_body(input))
        return out.strip() or f"review posted ({action})"

    def pr_create(input, ctx):
        title = input.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        args = ["pr", "create", f"--title={title}", "--body-file", "-"]
        if input.get("base"):
            args.append(f"--base={_plain('base', input['base'])}")
        if input.get("head"):
            args.append(f"--head={_plain('head', input['head'])}")
        if input.get("draft"):
            args.append("--draft")
        out, _ = gh(args, input, ctx, stdin=input.get("body") or "")
        return out.strip() or "pull request created"

    S = {"type": "string"}
    N = {"type": "integer", "description": "Number (default: the current branch's pull request)"}
    REPO_PROP = {**S, "description": "owner/name of another repository (default: the current one)"}
    PREFER = " Prefer it over `bash gh ...`: compact output, bounded size and no permission prompt."

    def read_tool(name, run, description, properties, required=()):
        minimal.register_tool(
            name,
            run,
            description + PREFER,
            {"type": "object", "properties": {**properties, "repo": REPO_PROP}, "required": list(required)},
            read_only=True,
        )

    def write_tool(name, run, description, properties, required=()):
        minimal.register_tool(
            name,
            run,
            description,
            {"type": "object", "properties": {**properties, "repo": REPO_PROP}, "required": list(required)},
            confirm=True,
        )

    read_tool("gh_pr_view", pr_view, "A pull request: title, state, review decision, check counts, changed files and description.", {"number": N})
    read_tool(
        "gh_pr_diff",
        pr_diff,
        "The diff of a pull request; pass path to get one file's section.",
        {"number": N, "path": {**S, "description": "Only this file's diff"}, "max_chars": {"type": "integer"}},
    )
    read_tool(
        "gh_pr_list",
        pr_list,
        "List pull requests, one per line.",
        {"state": {**S, "enum": ["open", "closed", "merged", "all"]}, "author": S, "label": S, "limit": {"type": "integer", "description": "Default 20, at most 100"}},
    )
    read_tool("gh_pr_checks", pr_checks, "The CI checks of a pull request: state, workflow, name, link.", {"number": N})
    read_tool(
        "gh_issue_view",
        issue_view,
        "An issue: title, state, labels and description; comments=true adds the comments.",
        {"number": {"type": "integer"}, "comments": {"type": "boolean"}},
        ["number"],
    )
    read_tool(
        "gh_issue_list",
        issue_list,
        "List issues, one per line.",
        {"state": {**S, "enum": ["open", "closed", "all"]}, "author": S, "label": S, "limit": {"type": "integer"}},
    )
    read_tool(
        "gh_run_view",
        run_view,
        "A GitHub Actions run (default: the latest on the current branch); failed_only=true shows only the failed steps' log, cut from the start.",
        {"run_id": {"type": "integer"}, "failed_only": {"type": "boolean"}},
    )
    write_tool("gh_pr_comment", pr_comment, "Comment on a pull request.", {"number": N, "body": S}, ["body"])
    write_tool("gh_issue_comment", issue_comment, "Comment on an issue.", {"number": {"type": "integer"}, "body": S}, ["number", "body"])
    write_tool(
        "gh_pr_review",
        pr_review,
        "Review a pull request: approve, request_changes or comment, with a body.",
        {"number": N, "action": {**S, "enum": ["approve", "request_changes", "comment"]}, "body": S},
        ["action", "body"],
    )
    write_tool(
        "gh_pr_create",
        pr_create,
        "Open a pull request from the current branch (or head) into base.",
        {"title": S, "body": S, "base": S, "head": S, "draft": {"type": "boolean"}},
        ["title", "body"],
    )
