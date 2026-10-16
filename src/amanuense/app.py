"""
app — the review app: a local web page to see every change, decide, edit and publish.

A standard-library HTTP server bound to 127.0.0.1. Only the tab it opens can drive it:
every API call carries a per-run token (given in the URL fragment, so it never reaches a
log), the Host header must be this server (no DNS rebinding) and a foreign Origin is
refused. Long work (searching for changes, the radiator, the delivery, asking the AI
again) runs in one background job; while it runs, edits wait.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import i18n
from . import service
from .service import Busy, Job  # noqa: F401  (kept importable from here)

WEB = Path(__file__).resolve().parent / "web"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css"}
MAX_BODY = 2_000_000
MAX_PLAN_BODY = 16_000_000  # the list of a big pile (path, size and hash of each file)
CSP = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


# ── The server ─────────────────────────────────────────────────────────────────

def _handler(ws: service.Workshop, token: str, port_box: dict):
    job = ws.job

    class Handler(BaseHTTPRequestHandler):
        server_version = "amanuense"
        sys_version = ""

        def log_message(self, *args):  # keep the console quiet: the page shows what matters
            pass

        def _headers(self, code: int, kind: str, length: int) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _json(self, code: int, data) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._headers(code, "application/json; charset=utf-8", len(raw))
            self.wfile.write(raw)

        def _allowed(self, api: bool) -> bool:
            port = port_box["port"]
            if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return False
            return not api or service.check_token(token, self.headers.get(service.TOKEN_HEADER))

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path in STATIC:
                if not self._allowed(api=False):
                    return self._json(403, {"error": "forbidden"})
                raw = (WEB / STATIC[url.path]).read_bytes()
                kind = mimetypes.guess_type(STATIC[url.path])[0] or "text/plain"
                self._headers(200, f"{kind}; charset=utf-8", len(raw))
                return self.wfile.write(raw)
            if not self._allowed(api=True):
                return self._json(403, {"error": "forbidden"})
            query = dict(urllib.parse.parse_qsl(url.query))
            try:
                if url.path == "/api/state":
                    return self._json(200, ws.state())
                if url.path == "/api/page":
                    return self._json(200, ws.detail(query.get("rel", "")))
                if url.path == "/api/job":
                    return self._json(200, job.snapshot())
                if url.path == "/api/task":
                    return self._json(200, ws.task(query.get("rel", "")))
            except Exception as exc:
                return self._error(exc)
            return self._json(404, {"error": "not found"})

        def _drain(self, left: int) -> None:
            """Reads a refused body away so the browser sees the answer, not a reset."""
            left = min(left, 8 * MAX_BODY)
            while left > 0:
                left -= len(self.rfile.read(min(left, 65536)) or b"x" * left)
            self.close_connection = True

        def _upload(self):
            """One file of a pile, sent as it is: POST /api/intake/file?batch=…&path=…"""
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/octet-stream":
                self._drain(int(self.headers.get("Content-Length") or 0))
                return self._json(415, {"error": "application/octet-stream expected"})
            size = int(self.headers.get("Content-Length") or 0)
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            counted = _Counted(self.rfile)
            try:
                stored = ws.upload(query.get("batch", ""), query.get("path", ""), counted, size,
                                   self.headers.get("X-Content-SHA256", ""))
            except Exception as exc:
                self._drain(size - counted.read_bytes)
                return self._error(exc)
            return self._json(200, {"stored": stored})

        def do_POST(self):
            if not self._allowed(api=True):
                return self._json(403, {"error": "forbidden"})
            if urllib.parse.urlsplit(self.path).path == "/api/intake/file":
                return self._upload()
            size = int(self.headers.get("Content-Length") or 0)
            limit = MAX_PLAN_BODY if urllib.parse.urlsplit(self.path).path == "/api/intake/plan" else MAX_BODY
            if size > limit:
                self._drain(size)
                return self._json(413, {"error": i18n.t("ui_too_big")})
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("JSON object expected")
            except ValueError:
                return self._json(400, {"error": "bad request"})
            path = urllib.parse.urlsplit(self.path).path
            try:
                if path == "/api/shutdown":
                    self._json(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if path == "/api/job":
                    name = str(body.get("name", ""))
                    if name not in service.JOBS:
                        return self._json(404, {"error": "unknown job"})
                    return self._json(200, ws.start_job(name, body))
                if path == "/api/open":
                    target = ws.target(str(body.get("what", "")))
                    webbrowser.open(target.resolve().as_uri())
                    return self._json(200, {"opened": str(target)})
                try:
                    return self._json(200, ws.act(path.removeprefix("/api/"), body))
                except service.Unknown:
                    return self._json(404, {"error": "not found"})
            except Exception as exc:
                return self._error(exc)

        def _error(self, exc: Exception):
            return self._json(*service.error_status(exc))

    return Handler


class _Counted:
    """A request body that remembers how much of it was read."""

    def __init__(self, stream):
        self.stream, self.read_bytes = stream, 0

    def read(self, n: int) -> bytes:
        data = self.stream.read(n)
        self.read_bytes += len(data)
        return data


def serve(root: Path, port: int = 0, lang: str | None = None) -> ThreadingHTTPServer:
    """Starts the app in a background thread; `server.url` opens it, `server.token` drives it."""
    ws = service.Workshop(root, lang)
    token = service.new_token()
    port_box: dict = {}
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(ws, token, port_box))
    server.daemon_threads = True
    port_box["port"] = server.server_address[1]
    server.token = token
    server.url = f"http://127.0.0.1:{port_box['port']}/#t={token}"
    server.stopped = threading.Event()

    def loop():
        try:
            server.serve_forever(poll_interval=0.05)
        finally:
            server.stopped.set()

    threading.Thread(target=loop, daemon=True).start()
    return server


def run_app(root: Path, open_browser: bool = True, lang: str | None = None) -> None:
    server = serve(root, lang=lang)
    print(i18n.t("ui_console", url=server.url), flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        while not server.stopped.wait(0.5):  # a short wait keeps Ctrl+C working on Windows
            pass
    except KeyboardInterrupt:
        server.shutdown()
    server.server_close()
