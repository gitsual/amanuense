"""The demo's stage: a made-up Confluence, AI and npm registry behind one local HTTP server.

Nothing here talks to a real service. It answers just enough of each API for amanuense to
run end to end through its real code paths:

- Confluence Data Center under /rest/api: page lookup by title, the space's pages page by page
  (start/limit, as the review app reads a live space), page history (who changed it), update
  and create, so the change log gets its authors and the review app can publish.
- An OpenAI-compatible /v1/chat/completions that answers every prompt from the demo's script
  (route a request, triage a commit, write a page), so the take is reproducible.
- An npm registry under /npm for the capability radiator.

    server = fakes.start(world)      # server.base is the address; stop with server.shutdown()
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPACE = "TRAMS"
TOKEN = "demo-token"
MODEL = "scripted"


def scripted_answer(world: dict, prompt: str) -> str:
    """What the scripted AI says to a prompt: a route, a triage verdict or a page."""
    if "\n## Pages\n" in prompt or "\n## Páginas\n" in prompt:
        return json.dumps(world["route"], ensure_ascii=False)
    if prompt.startswith(("You review whether commits", "Revisas si unos commits")):
        title = prompt.split("«", 1)[1].split("»", 1)[0]
        return json.dumps(world["triage"][title], ensure_ascii=False)
    first = prompt.splitlines()[0]
    titles = [t for t in world["results"] if t in first]
    if not titles and world.get("fallback"):  # a world that answers any page, e.g. an uploaded pile
        return world["fallback"](prompt)
    return world["results"][max(titles, key=len)]


def start(world: dict, port: int = 0) -> ThreadingHTTPServer:
    pages: dict[str, dict] = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, data: dict) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode()
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
            url = urllib.parse.urlsplit(self.path)
            if url.path.startswith("/npm/"):
                name = urllib.parse.unquote(url.path[len("/npm/"):])
                versions = world["registry"].get(name)
                if versions is None:
                    return self._send(404, {"error": "not found"})
                return self._send(200, {"name": name, "versions": {v: {} for v in versions}})
            if not self._allowed():
                return
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/rest/api/user/current":
                return self._send(200, {"displayName": world["editor"]})
            if url.path == "/rest/api/content" and "title" not in q:
                listed = [_current(p) for p in pages.values() if q.get("spaceKey") in (None, SPACE)]
                start, limit = int(q.get("start", 0)), int(q.get("limit", 25))
                links = {"base": server.base}
                if start + limit < len(listed):
                    links["next"] = f"/rest/api/content?spaceKey={SPACE}&start={start + limit}&limit={limit}"
                chunk = listed[start:start + limit]
                return self._send(200, {"results": chunk, "start": start, "limit": limit, "size": len(chunk),
                                        "_links": links})
            if url.path == "/rest/api/content":
                hits = [_current(p) for p in pages.values() if p["title"] == q.get("title")]
                return self._send(200, {"results": hits, "size": len(hits)})
            page = pages.get(url.path.rsplit("/", 1)[-1])
            if not page:
                return self._send(404, {"message": "Not found"})
            if q.get("status") == "historical":
                old = next((v for v in page["versions"] if v["number"] == int(q.get("version", 0))), None)
                return self._send(200, {**_current(page), "version": old}) if old else self._send(404, {})
            self._send(200, _current(page))

        def do_PUT(self):
            if not self._allowed():
                return
            body = self._body()
            with lock:
                page = pages[self.path.rsplit("/", 1)[-1]]
                if body["version"]["number"] != page["versions"][-1]["number"] + 1:
                    return self._send(409, {"message": "Version must be incremented"})
                page["versions"].append({"number": body["version"]["number"], "when": world["now"],
                                         "by": {"displayName": world["editor"]},
                                         "message": body["version"].get("message", "")})
                page["storage"] = body["body"]["storage"]["value"]
                page["title"] = body["title"]
            self._send(200, _current(page))

        def do_POST(self):
            if self.path.startswith("/v1/chat/completions"):
                prompt = self._body()["messages"][-1]["content"]
                time.sleep(world.get("ai_delay", 0))  # a demo can slow the AI down so its progress is readable
                answer = scripted_answer(world, prompt)
                return self._send(200, {"choices": [{"message": {"role": "assistant", "content": answer}}]})
            if not self._allowed():
                return
            body = self._body()
            with lock:
                pid = str(2000 + len(pages))
                pages[pid] = _page(pid, body["title"], [_version(1, world["now"], world["editor"])],
                                   body["body"]["storage"]["value"], server.base)
            self._send(200, _current(pages[pid]))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.base = f"http://127.0.0.1:{server.server_address[1]}"
    for i, (title, history, storage) in enumerate(world["confluence"], start=1000):
        versions = [_version(n, when, by, message) for n, when, by, message in history]
        pages[str(i)] = _page(str(i), title, versions, storage, server.base)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _version(number: int, when: str, by: str, message: str = "") -> dict:
    return {"number": number, "when": when, "by": {"displayName": by}, "message": message}


def _page(pid: str, title: str, versions: list[dict], storage: str, base: str) -> dict:
    return {"id": pid, "title": title, "versions": versions, "storage": storage, "base": base}


def _current(page: dict) -> dict:
    return {"id": page["id"], "type": "page", "title": page["title"], "space": {"key": SPACE},
            "version": page["versions"][-1],
            "body": {"storage": {"value": page["storage"], "representation": "storage"}},
            "_links": {"webui": f"/display/{SPACE}/{urllib.parse.quote_plus(page['title'])}",
                       "base": page["base"]}}
