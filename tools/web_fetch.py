"""Fetch a web page or API response for the model: HTML becomes Markdown, JSON is pretty-printed, text stays text.

`web_fetch(url)` complements ``web_search``: search finds the page, this reads it. Only ``urllib`` is used (no
dependencies). It follows at most 5 redirects, reads at most 2 MB, and refuses hosts that resolve to loopback, private
or link-local addresses (checked again after every redirect) unless ``allow_private`` is set, so a model cannot be
steered into probing your network. Scripts, styles, navigation and footers are dropped from HTML. Settings (``/ext
settings tools/web_fetch``): ``max_chars`` (output cut), ``timeout`` (seconds), ``user_agent`` and ``allow_private``.

Install it with ``/ext``.
"""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["workflow", "search"]

DEFAULTS = {"max_chars": 30000, "timeout": 20, "user_agent": "minimal-web-fetch/1.0", "allow_private": False}

SCHEMA = {
    "max_chars": {"description": "Longest output in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "timeout": {"description": "Seconds to wait for the server.", "min": 1, "max": 300},
    "user_agent": {"description": "User-Agent header to send."},
    "allow_private": {"description": "Fetch hosts that resolve to loopback, private or link-local addresses (localhost, your LAN)."},
}

MAX_BYTES = 2_000_000
"""Most bytes of a body that are read; the rest is dropped."""
MAX_REDIRECTS = 5
SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "noscript", "template", "svg", "iframe"})
BLOCKS = frozenset({"p", "div", "section", "article", "header", "main", "aside", "ul", "ol", "table", "blockquote", "figure", "form", "dl"})


def assert_public(host, allow_private):
    """``ValueError`` when ``host`` resolves to an address that is not public (unless ``allow_private``)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}: {e.strerror or e}; check the URL") from None
    if allow_private:
        return
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if address.is_loopback or address.is_private or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified:
            raise ValueError(f"{host} resolves to a private address; set allow_private to fetch it")


class Markdown(HTMLParser):
    """HTML to Markdown (``plain``: the same without the markup characters)."""

    def __init__(self, plain=False):
        super().__init__(convert_charrefs=True)
        self.plain = plain
        self.out = []
        self.skip = 0
        self.pre = 0
        self.title = ""
        self.in_title = False
        self.links = []
        self.lists = []
        self.cells = 0

    def _text(self):
        return "".join(self.out)

    def _nl(self, n):
        """End the current line and leave ``n - 1`` blank lines, without piling up newlines."""
        text = self._text()
        if not text:
            return
        have = len(text) - len(text.rstrip("\n"))
        if have < n:
            self.out.append("\n" * (n - have))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self._nl(2)
            self.out.append("" if self.plain else "#" * int(tag[1]) + " ")
        elif tag in BLOCKS:
            self._nl(1 if self.lists and tag in ("ul", "ol") else 2 if tag in ("p", "ul", "ol", "table", "blockquote") else 1)
            if tag in ("ul", "ol"):
                self.lists.append([tag, 0])
            if tag == "blockquote" and not self.plain:
                self.out.append("> ")
        elif tag == "li":
            self._nl(1)
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self.out.append("  " * max(0, len(self.lists) - 1) + (f"{kind[1]}. " if kind[0] == "ol" else "- "))
        elif tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self._nl(2)
            self.out.append("---")
            self._nl(2)
        elif tag == "pre":
            self._nl(2)
            self.pre += 1
            self.out.append("```\n")
        elif tag == "code" and not self.pre and not self.plain:
            self.out.append("`")
        elif tag == "a":
            href = a.get("href") or ""
            self.links.append(href if href and not href.startswith(("#", "javascript:")) else "")
            if self.links[-1] and not self.plain:
                self.out.append("[")
        elif tag in ("b", "strong") and not self.plain:
            self.out.append("**")
        elif tag in ("em", "i") and not self.plain:
            self.out.append("*")
        elif tag == "tr":
            self._nl(1)
            self.cells = 0
        elif tag in ("td", "th"):
            if self.cells:
                self.out.append(" | ")
            self.cells += 1
        elif tag == "img" and a.get("alt") and not self.plain:
            self.out.append(f"[image: {a['alt']}]")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag):
            self._nl(2)
        elif tag in BLOCKS:
            if tag in ("ul", "ol") and self.lists:
                self.lists.pop()
            self._nl(1 if self.lists and tag in ("ul", "ol") else 2 if tag in ("p", "ul", "ol", "table", "blockquote") else 1)
        elif tag == "li":
            self._nl(1)
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self._nl(1)
            self.out.append("```")
            self._nl(2)
        elif tag == "code" and not self.pre and not self.plain:
            self.out.append("`")
        elif tag == "a" and self.links:
            href = self.links.pop()
            if href and not self.plain:
                self.out.append(f"]({href})")
        elif tag in ("b", "strong") and not self.plain:
            self.out.append("**")
        elif tag in ("em", "i") and not self.plain:
            self.out.append("*")
        elif tag == "tr":
            self._nl(1)

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        if self.pre:
            self.out.append(data)
            return
        text = re.sub(r"\s+", " ", data)
        current = self._text()
        if not current or current.endswith(("\n", " ")) or current.endswith("> "):
            text = text.lstrip()
        self.out.append(text)

    def result(self):
        text = re.sub(r"[ \t]+\n", "\n", self._text())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        title = " ".join(self.title.split())
        return f"# {title}\n\n{text}" if title and not self.plain and not text.startswith(f"# {title}\n") else text


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    opener = urllib.request.build_opener(NoRedirect)

    def fetch(url, ctx):
        """``(final url, content type, charset, body bytes, truncated)``."""
        for hop in range(MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError(f"{url} is not an http or https URL")
            assert_public(parts.hostname, settings["allow_private"])
            request = urllib.request.Request(url, headers={"User-Agent": settings["user_agent"], "Accept": "text/html,application/json,text/*;q=0.9,*/*;q=0.5"})
            try:
                response = opener.open(request, timeout=settings["timeout"])
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                    url = urllib.parse.urljoin(url, e.headers["Location"])
                    e.close()
                    continue
                body = e.read(300).decode("utf-8", errors="replace").strip()
                e.close()
                raise RuntimeError(f"{url} answered HTTP {e.code} {e.reason}" + (f": {body[:200]}" if body else "")) from None
            except urllib.error.URLError as e:
                raise RuntimeError(f"cannot fetch {url}: {e.reason}; check the URL and your connection") from None
            with response:
                kind = response.headers.get_content_type()
                charset = response.headers.get_content_charset()
                data = response.read(MAX_BYTES + 1)
            return url, kind, charset, data[:MAX_BYTES], len(data) > MAX_BYTES
        raise RuntimeError(f"too many redirects (more than {MAX_REDIRECTS}) from the first URL; fetch the final address directly")

    def web_fetch(input, ctx):
        url = input.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url is required")
        form = input.get("format", "markdown")
        if form not in ("markdown", "text", "raw"):
            raise ValueError("format must be markdown, text or raw")
        limit = settings["max_chars"]
        if input.get("max_chars") is not None:
            if isinstance(input["max_chars"], bool) or not isinstance(input["max_chars"], int):
                raise ValueError("max_chars must be an integer")
            limit = max(1000, min(limit, input["max_chars"]))
        host = urllib.parse.urlsplit(url.strip()).hostname or url
        ctx.progress(f"fetching {host}")
        try:
            final, kind, charset, data, cut = fetch(url.strip(), ctx)
        finally:
            ctx.progress(None)
        try:
            text = data.decode(charset or "utf-8", errors="replace")
        except LookupError:
            text = data.decode("utf-8", errors="replace")
        if kind in ("text/html", "application/xhtml+xml"):
            if form != "raw":
                parser = Markdown(plain=form == "text")
                parser.feed(text)
                parser.close()
                text = parser.result()
        elif kind == "application/json" or kind.endswith("+json"):
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        elif not (kind.startswith("text/") or kind.endswith("+xml") or kind in ("application/xml", "application/javascript")):
            raise ValueError(f"unsupported content type {kind}; web_fetch reads HTML, JSON and text (download other files with bash)")
        notes = []
        if cut:
            notes.append(f"the response was cut at {MAX_BYTES // 1_000_000} MB")
        if len(text) > limit:
            text = f"{text[:limit]}\n[clipped {len(text) - limit} chars; fetch a more specific URL or raise max_chars (at most {settings['max_chars']})]"
        if notes:
            text += f"\n[{'; '.join(notes)}]"
        return f"{final}\n\n{text}" if final != url.strip() else text

    minimal.register_tool(
        "web_fetch",
        web_fetch,
        "Fetch a URL and return it as Markdown (HTML), pretty JSON or text. Use it to read a page found with web_search or a "
        "documentation link; prefer it over `bash curl` (clean text, size limits, no private addresses).",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http or https URL"},
                "max_chars": {"type": "integer", "description": "Cut the output to this many characters"},
                "format": {"type": "string", "enum": ["markdown", "text", "raw"], "description": "How to show HTML (default markdown)"},
            },
            "required": ["url"],
        },
        read_only=True,
    )
