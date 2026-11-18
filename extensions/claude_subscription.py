"""Claude Pro/Max subscription as a provider: sign in with the browser instead of an API key.

Adds the provider `claude`. Sign in once with `minimal --login claude` (or `/login claude` inside minimal), then
pick it with `--provider claude`, `/provider claude` or in setup. The login (OAuth with PKCE against claude.ai)
is stored, with its refresh token, in this extension's global data folder
(`~/.minimal/data/global/claude_subscription/claude-auth.json`, mode 0600); a login stored by minimal 0.5 or
earlier in `~/.minimal/claude-auth.json` is moved there the first time it is needed.

It signs in with the client id of Claude Code and presents itself as Claude Code to the API, which the
subscription tokens require; whether that fits Anthropic's terms for your plan is yours to check.

Install it with `/ext`, or `minimal ext install claude_subscription` before the first start.
"""

__version__ = "1.1"
__api__ = "2.1"
__tags__ = ["provider"]

import base64
import dataclasses
import hashlib
import http.server
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from minimal.api import AnthropicProvider, ProviderSpec

if TYPE_CHECKING:
    from anthropic.lib.credentials import AccessToken

CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
CALLBACK_PORT = 54545
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT = 300
"""Seconds to wait for the browser."""
EXPIRY_SKEW = 300
"""Refresh this many seconds before the real expiry."""
OAUTH_BETA = "oauth-2025-04-20"
LEGACY_AUTH_FILE = Path.home() / ".minimal" / "claude-auth.json"
"""Where minimal 0.5 and earlier kept the login."""
NOT_LOGGED_IN = "Not logged in to Claude: run `minimal --login claude` (or /login claude in the terminal UI)."

_data_dir: Callable[[str], Path] | None = None
"""This extension's ``minimal.data_dir``, set by :func:`register`."""


@dataclass
class Credentials:
    """Stored login. ``expires_at`` is unix seconds with the skew already subtracted."""

    access: str
    refresh: str
    expires_at: int
    email: str | None = None


def auth_file() -> Path:
    """Where the login is stored; a login kept by an older minimal is moved here first."""
    assert _data_dir is not None, "register() has not run"
    path = _data_dir("global") / "claude-auth.json"
    if not path.exists() and LEGACY_AUTH_FILE.is_file():
        try:
            shutil.move(str(LEGACY_AUTH_FILE), str(path))
        except OSError:  # keep using it where it is
            return LEGACY_AUTH_FILE
    return path


def load() -> Credentials | None:
    """Read the stored login, or ``None`` if there is none.

    Raises:
        ValueError: if the file exists but cannot be parsed.
    """
    path = auth_file()
    if not path.exists():
        return None
    try:
        return Credentials(**json.loads(path.read_text()))
    except (ValueError, TypeError, KeyError):
        raise ValueError(f"{path} is unreadable; run `minimal --login claude` again.") from None


def save(creds: Credentials) -> None:
    """Write the login atomically with mode 0600 (the temporary file is created private)."""
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".claude-auth-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(dataclasses.asdict(creds), f)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def _token_request(body: dict, headers: dict[str, str] | None = None) -> dict:
    """POST ``body`` as JSON to the token endpoint and return the parsed reply."""
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Claude token request failed: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
        ) from None


def _credentials_from(data: dict, previous_refresh: str = "") -> Credentials:
    return Credentials(
        access=data["access_token"],
        refresh=data.get("refresh_token") or previous_refresh,
        expires_at=int(time.time()) + int(data.get("expires_in", 3600)) - EXPIRY_SKEW,
        email=(data.get("account") or {}).get("email_address"),
    )


def refresh(creds: Credentials) -> Credentials:
    """Exchange the refresh token for a new access token.

    Raises:
        RuntimeError: if the login expired or was revoked.
    """
    try:
        data = _token_request(
            {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": creds.refresh},
            {"anthropic-beta": OAUTH_BETA},
        )
    except RuntimeError as e:
        raise RuntimeError(f"Claude login expired or was revoked ({e}). Run `minimal --login claude` (or /login).") from None
    new = _credentials_from(data, creds.refresh)
    new.email = new.email or creds.email
    return new


def login(open_browser: Callable[[str], object] = webbrowser.open, timeout: float = LOGIN_TIMEOUT) -> Credentials:
    """Sign in through the browser, store the tokens and return them.

    Raises:
        TimeoutError: if the browser does not come back within ``timeout`` seconds.
        RuntimeError: if the authorization or the token exchange fails.
    """
    verifier = base64.urlsafe_b64encode(os.urandom(96)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_hex(16)
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self._reply(404, "Not found")
                return
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            if query.get("state") != state:
                self._reply(400, "State mismatch")
                return
            if "error" in query:
                result["error"] = query.get("error_description") or query["error"]
                self._reply(400, result["error"])
                done.set()
            elif "code" in query:
                result["code"] = query["code"]
                self._reply(200, "Logged in to minimal. You can close this tab.", "text/html")
                done.set()
            else:
                self._reply(400, "Missing code")

        def _reply(self, status: int, text: str, content_type: str = "text/plain") -> None:
            body = text.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    try:
        server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    except OSError:  # port busy
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://localhost:{server.server_port}{CALLBACK_PATH}"
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()

    try:
        url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
            {
                "code": "true",
                "client_id": CLIENT_ID,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            }
        )
        print(f"Opening the browser to sign in to Claude. If it does not open, visit:\n{url}", flush=True)
        open_browser(url)
        if not done.wait(timeout):
            raise TimeoutError("Claude login timed out")
        if "error" in result:
            raise RuntimeError(f"Claude login failed: {result['error']}")
    finally:
        server.shutdown()
        server.server_close()

    data = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "state": state,
        }
    )
    creds = _credentials_from(data)
    save(creds)
    print(f"Logged in to Claude as {creds.email}." if creds.email else "Logged in to Claude.")
    return creds


def logout() -> None:
    """Delete the stored login."""
    path = auth_file()
    if path.exists():
        path.unlink()
        print("Logged out of Claude.")
    else:
        print("Not logged in to Claude.")


class TokenProvider:
    """``anthropic`` SDK credentials provider backed by the stored login.

    Re-reads the file on every call (the SDK calls only near expiry or after a
    401), so a new login, a logout or another process's refresh is picked up.
    """

    def __call__(self, *, force_refresh: bool = False) -> "AccessToken":
        from anthropic.lib.credentials import AccessToken

        creds = load()
        if creds is None:
            raise RuntimeError(NOT_LOGGED_IN)
        if force_refresh or time.time() >= creds.expires_at:
            creds = refresh(creds)
            save(creds)
        return AccessToken(token=creds.access, expires_at=creds.expires_at)


class ClaudeProvider(AnthropicProvider):
    """Anthropic provider authenticated with the stored subscription login."""

    name = "claude"
    identity = CLAUDE_CODE_IDENTITY

    def __init__(self, client: Any = None) -> None:
        if client is None:
            if load() is None:
                raise ValueError(NOT_LOGGED_IN)
            import anthropic

            client = anthropic.Anthropic(credentials=TokenProvider())
        super().__init__(client)


def _login() -> None:
    login()


def _account() -> str | None:
    try:
        stored = load()
    except ValueError:  # an unreadable file counts as logged out: a new login replaces it
        return None
    return None if stored is None else stored.email or "logged in"


def register(minimal):
    global _data_dir
    _data_dir = minimal.data_dir
    minimal.add_provider(
        ProviderSpec(
            name="claude",
            create=ClaudeProvider,
            default_model="claude-sonnet-5-5",
            description="Claude Pro/Max subscription (minimal --login claude)",
            login=_login,
            logout=logout,
            account=_account,
        )
    )
