"""A made-up MIND for the demo: just enough of Confluence's /rest/api/content to publish.

Pages are seeded from the titles of the workshop's last export, all last edited before it, so
publishing goes through. Nothing here talks to a real Confluence.

    server = fake_mind.start(titles)   # server.base is the address to put in Settings
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPACE = "DOCS"
TOKEN = "demo-token"
EDITOR = "Rosa Vidal"


def start(titles: list[str], port: int = 0) -> ThreadingHTTPServer:
    pages: dict[str, dict] = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, data: dict) -> None:
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _allowed(self) -> bool:
            if self.headers.get("Authorization") == f"Bearer {TOKEN}":
                return True
            self._send(401, {"message": "Unauthorized"})
            return False

        def _body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        def do_GET(self):
            if not self._allowed():
                return
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/rest/api/user/current":
                return self._send(200, {"displayName": EDITOR})
            if url.path == "/rest/api/content":
                hits = [p for p in pages.values() if p["title"] == q.get("title")]
                return self._send(200, {"results": hits, "size": len(hits)})
            page = pages.get(url.path.rsplit("/", 1)[-1])
            self._send(200, page) if page else self._send(404, {"message": "Not found"})

        def do_PUT(self):
            if not self._allowed():
                return
            body = self._body()
            with lock:
                page = pages[self.path.rsplit("/", 1)[-1]]
                if body["version"]["number"] != page["version"]["number"] + 1:
                    return self._send(409, {"message": "Version must be incremented"})
                page["version"] = {"number": body["version"]["number"], "when": "2026-10-11T10:00:00.000+02:00",
                                   "by": {"displayName": EDITOR}, "message": body["version"].get("message", "")}
                page["body"]["storage"]["value"] = body["body"]["storage"]["value"]
                page["title"] = body["title"]
            self._send(200, page)

        def do_POST(self):
            if not self._allowed():
                return
            body = self._body()
            with lock:
                pid = str(2000 + len(pages))
                pages[pid] = _page(pid, body["title"], 1, body["body"]["storage"]["value"], server.base)
            self._send(200, pages[pid])

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.base = f"http://127.0.0.1:{server.server_address[1]}"
    for i, title in enumerate(sorted(titles), start=1000):
        pages[str(i)] = _page(str(i), title, 3, "<p>Text of today.</p>", server.base)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _page(pid: str, title: str, version: int, storage: str, base: str) -> dict:
    return {"id": pid, "type": "page", "title": title, "space": {"key": SPACE},
            "version": {"number": version, "when": "2026-10-08T09:00:00.000+02:00", "by": {"displayName": "Luis Pardo"}},
            "body": {"storage": {"value": storage, "representation": "storage"}},
            "_links": {"webui": f"/pages/viewpage.action?pageId={pid}", "base": base}}
