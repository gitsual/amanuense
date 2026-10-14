"""
app — the review app: a local web page to see every change, decide, edit and publish.

A standard-library HTTP server bound to 127.0.0.1. Only the tab it opens can drive it:
every API call carries a per-run token (given in the URL fragment, so it never reaches a
log), the Host header must be this server (no DNS rebinding) and a foreign Origin is
refused. Long work (searching for changes, the radiator, the delivery, asking the AI
again) runs in one background job; while it runs, edits wait.
"""
from __future__ import annotations

import difflib
import hmac
import json
import mimetypes
import secrets
import shutil
import threading
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import i18n
from . import intake
from . import mind
from . import registro as log
from . import revision
from . import settings
from . import space
from . import taller as kit

WEB = Path(__file__).resolve().parent / "web"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css"}
MAX_BODY = 2_000_000
MAX_PLAN_BODY = 16_000_000  # the list of a big pile (path, size and hash of each file)
CSP = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Busy(Exception):
    """A job is running; edits wait for it."""


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"name": "", "running": False, "started": "", "finished": "", "result": None, "error": ""}

    def start(self, name: str, work) -> None:
        with self.lock:
            if self.state["running"]:
                raise Busy()
            self.state = {"name": name, "running": True, "started": log._now(), "finished": "", "result": None,
                          "error": "", "progress": {"stage": "", "done": 0, "total": 0}}

        def run():
            try:
                result = work()
            except Exception as exc:  # shown to the reviewer as it is
                result, error = None, str(exc) or exc.__class__.__name__
            else:
                error = ""
            with self.lock:
                self.state.update(running=False, finished=log._now(), result=result, error=error)

        threading.Thread(target=run, daemon=True).start()

    def running(self) -> bool:
        with self.lock:
            return self.state["running"]

    def progress(self, stage: str, done: int = 0, total: int = 0) -> None:
        with self.lock:
            self.state["progress"] = {"stage": stage, "done": done, "total": total}


# ── What the page shows ────────────────────────────────────────────────────────

def _texts() -> dict:
    return {k: v[i18n.current()] for k, v in i18n.TEXT.items() if k.startswith(("ui_", "status_", "origin_"))}


def _diff(before: str, after: str) -> list[dict]:
    a, b = before.splitlines(), after.splitlines()
    rows = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        rows.append({"op": op, "a": a[i1:i2], "b": b[j1:j2], "a_start": i1 + 1, "b_start": j1 + 1})
    return rows


def _detail(root: Path, rel: str) -> dict:
    out = root / i18n.name("out")
    d = out / rel
    proposal = revision.find(root, rel)
    result = (d / i18n.name("result")).read_text(encoding="utf-8")
    before_file = d / i18n.name("current" if not proposal["new"] else "local_copy")
    before = before_file.read_text(encoding="utf-8") if before_file.is_file() else ""
    entries = log._load(out / i18n.name("log_json"), [])
    requests = [{"by": e["by"], "text": e.get("request", ""), "change": e.get("cambio", ""),
                 "why": e.get("motivo", ""), "when": e["when"]}
                for e in entries if e["kind"] == "peticion" and e.get("page") == proposal["title"]]
    commits = [{"repo": e.get("repo", ""), "branch": e.get("branch", ""), "hash": e.get("hash", "")[:10],
                "by": e.get("by", ""), "what": e.get("what", ""), "when": e.get("when", "")}
               for e in entries if e["kind"] == "codigo"
               and any(r in log.code_task_pages(e) for r in [rel, *proposal["others"]])]
    history = [{"what": e["what"], "by": e["by"], "when": e["when"]}
               for e in entries if e["kind"] == "revision" and e.get("page") == proposal["title"]]
    return {"proposal": proposal, "result": result, "before": before, "diff": _diff(before, result),
            "preview": kit.markdown_to_html(result),
            "paste": kit.markdown_to_html(mind.strip_title(result, proposal["title"])), "triage": log._load(d / log.TRIAGE_FILE, {}),
            "requests": requests, "commits": commits, "history": history,
            "edited": (d / (Path(i18n.name("result")).stem + revision.AI_COPY)).is_file()}


def _planned_source(root: Path) -> dict:
    """What a comparison would read now: Confluence live, the Word export, or nothing."""
    data = settings.load()
    if data["url"] and data["token"] and data["space"]:
        return {"kind": "live", "space": data["space"], "root": data["root_page"], "base": data["url"]}
    exports = kit._inputs(root / i18n.name("export"), ".docx")
    if exports:
        return {"kind": "export", "files": [e.name for e in exports],
                "created": max((log.export_created(e) for e in exports), default="")}
    return {"kind": "none"}


def _state(root: Path, job: Job) -> dict:
    proposals = revision.proposals(root)
    snap = log._load(root / i18n.name("out") / i18n.name("snapshot"), {})
    with job.lock:
        job_state = dict(job.state)
    return {"lang": i18n.current(), "texts": _texts(), "user": log._user(), "workspace": str(root),
            "proposals": proposals, "set_aside": revision.set_aside(root), "job": job_state,
            "settings": settings.summary(), "engines": sorted(kit.ENGINES),
            "exported": snap.get("created", ""), "pages": sorted(snap.get("pages", {})),
            "source": space.last_summary(root), "planned_source": _planned_source(root),
            "intake": intake.load_summary(root), "formats": intake.READABLE,
            "limits": {"max_file": intake.MAX_FILE_BYTES, "max_batch": intake.MAX_BATCH_BYTES,
                       "max_files": intake.MAX_BATCH_FILES},
            "local_dir": i18n.name("local"), "export_dir": i18n.name("export"), "ignore_file": i18n.name("intake_ignore")}


def _source(root: Path, job: Job) -> space.Source:
    """Confluence live when configured (its cached copy when it does not answer), else the export."""
    job.progress("fetch")
    try:
        client = settings.mind_client()
    except mind.MindError as exc:  # e.g. an http:// address: say it, and read the export
        return space.Source("export", None, warning=str(exc))
    return space.resolve(root, client, settings.load()["root_page"])


# ── The server ─────────────────────────────────────────────────────────────────

def _handler(root: Path, token: str, job: Job, port_box: dict):
    by = log._user

    def need(body: dict, *keys: str) -> list:
        missing = [k for k in keys if not str(body.get(k) or "").strip()]
        if missing:
            raise ValueError(i18n.t("ui_missing", fields=", ".join(missing)))
        return [body[k] for k in keys]

    def client():
        c = settings.mind_client()
        if not c:
            raise ValueError(i18n.t("ui_mind_not_configured"))
        return c

    def history():
        data = settings.load()
        if data["url"] and data["token"]:
            return log.ConfluenceHistory(data["url"], data["token"], data["space"], data["user"])
        return None

    def ai():
        c = settings.ai_client()
        if not c:
            raise ValueError(i18n.t("ui_ai_not_configured"))
        return c

    def open_target(what: str) -> dict:
        out = root / i18n.name("out")
        targets = {"log": out / i18n.name("log_html"), "radiator": out / "radiador" / "index.html",
                   "workspace": root, "output": out}
        deliveries = sorted(out.glob(i18n.name("delivery") + "-*"))
        if deliveries:
            targets["delivery"] = [p for p in deliveries if p.is_dir()][-1]
        path = targets.get(what)
        if not path or not path.exists():
            raise ValueError(i18n.t("ui_nothing_to_open"))
        webbrowser.open(path.resolve().as_uri())
        return {"opened": str(path)}

    def compare(batch: str = ""):
        if batch:
            intake.batch_dir(root, batch)  # an unknown batch is refused before the job starts
        # Dropped files are compared with what was fetched last: fetching every repo first
        # takes minutes without VPN. "Look for changes" still fetches them.

        def work() -> dict:
            source = _source(root, job)
            result = kit.run_workspace(root, None, None, settings.ai_client(), history(), source=source,
                                       progress=job.progress, sync_repos=not batch)
            out = _summary(result)
            out["source"] = result.get("source") or {}
            if batch:
                out["batch_name"] = batch
                out["batch"] = (intake.load_summary(root).get("batches") or {}).get(batch, {})
            return out
        return work

    ledger = intake.Ledger(root)
    started: set[str] = set()  # batches this session opened: only these can be cancelled

    def start_batch(_body: dict) -> dict:
        batch = intake.new_batch(root)
        started.add(batch)
        return {"batch": batch, "folder": f"{i18n.name('local')}/{batch}"}

    def cancel_batch(body: dict) -> dict:
        batch = str(body.get("batch", ""))
        folder = intake.batch_dir(root, batch)
        if batch not in started:
            raise ValueError(i18n.t("intake_bad_batch"))
        shutil.rmtree(folder)
        started.discard(batch)
        return {"ok": True}

    jobs = {
        "run": lambda body: compare(),
        "intake": lambda body: compare(need(body, "batch")[0]),
        "radiator": lambda body: lambda: str(kit.radiator_workspace(root)),
        "deliver": lambda body: lambda: str(kit.deliver_workspace(root, make_zip=True)),
        "rework": lambda body: (lambda rel, instruction, model=ai():
                                lambda: revision.rework(root, rel, instruction, model, by())["title"])(
                                    *need(body, "rel", "instruction")),
    }

    def detail(rel: str) -> dict:
        return _detail(root, rel)

    def acted(action):
        """An action on one page; the answer is the page as it is now."""
        def call(b: dict) -> dict:
            rel = need(b, "rel")[0]
            action(rel, b)
            return detail(rel)
        return call

    posts = {
        "/api/preview": lambda b: {"html": kit.markdown_to_html(str(b.get("markdown", "")))},
        "/api/save": acted(lambda rel, b: revision.save_text(root, rel, need(b, "markdown")[0], by=by())),
        "/api/resolve": acted(lambda rel, b: revision.resolve_notice(root, rel, *need(b, "notice", "decision"),
                                                                     by=by())),
        "/api/approve": acted(lambda rel, b: revision.approve(root, rel, by=by())),
        "/api/reopen": acted(lambda rel, b: revision.reopen(root, rel, by=by())),
        "/api/discard": acted(lambda rel, b: revision.discard(root, rel, by=by(), reason=need(b, "reason")[0])),
        "/api/mark-published": acted(lambda rel, b: revision.mark_published(
            root, rel, by=by(), mode="manual", url=need(b, "url")[0], version=None)),
        "/api/publish": acted(lambda rel, b: mind.publish(root, rel, client(), by(), parent=b.get("parent") or None,
                                                          accept_warnings=bool(b.get("accept_warnings")))),
        "/api/undo": acted(lambda rel, b: mind.undo(root, rel, client(), by())),
        "/api/promote": lambda b: (revision.promote(root, need(b, "rel")[0], by=by()), {"ok": True})[1],
        "/api/preflight": lambda b: mind.preflight(root, need(b, "rel")[0], client(), parent=b.get("parent") or None),
        "/api/settings": lambda b: (settings.save(b), settings.summary())[1],
        "/api/settings/forget": lambda b: (settings.forget_token(), settings.summary())[1],
        "/api/settings/test": lambda b: {"user": client().me()},
        "/api/open": lambda b: open_target(str(b.get("what", ""))),
        "/api/intake/plan": lambda b: intake.plan(root, [f for f in b.get("files") or [] if isinstance(f, dict)]),
        "/api/intake/start": start_batch,
        "/api/intake/cancel": cancel_batch,
        "/api/intake/promote": lambda b: {"promoted": intake.promote(root, need(b, "rel")[0])},
    }
    reads_only = {"/api/preview", "/api/preflight", "/api/settings/test", "/api/open", "/api/intake/plan"}

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
            return not api or hmac.compare_digest(self.headers.get("X-Amanuense-Token", ""), token)

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
                    return self._json(200, _state(root, job))
                if url.path == "/api/page":
                    return self._json(200, detail(query.get("rel", "")))
                if url.path == "/api/job":
                    with job.lock:
                        return self._json(200, dict(job.state))
                if url.path == "/api/task":
                    path = root / i18n.name("out") / revision.find(root, query.get("rel", ""))["rel"] / i18n.name("task")
                    return self._json(200, {"text": path.read_text(encoding="utf-8")})
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
                if job.running():
                    raise Busy()
                if size > intake.MAX_FILE_BYTES:
                    raise intake.TooBig(i18n.t("intake_file_too_big", path=query.get("path", "?"),
                                               mb=intake.MAX_FILE_BYTES // (1024 * 1024)))
                stored = ledger.store(query.get("batch", ""), query.get("path", ""), counted, size,
                                      self.headers.get("X-Content-SHA256", ""))
            except Exception as exc:
                self._drain(size - counted.read_bytes)
                if isinstance(exc, intake.TooBig):
                    return self._json(413, {"error": str(exc)})
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
                    if name not in jobs:
                        return self._json(404, {"error": "unknown job"})
                    job.start(name, jobs[name](body))
                    with job.lock:
                        return self._json(200, dict(job.state))
                if path not in posts:
                    return self._json(404, {"error": "not found"})
                if path not in reads_only and job.running():
                    raise Busy()
                return self._json(200, posts[path](body))
            except Exception as exc:
                return self._error(exc)

        def _error(self, exc: Exception):
            if isinstance(exc, Busy):
                return self._json(423, {"error": i18n.t("ui_busy")})
            if isinstance(exc, revision.ReviewError):
                return self._json(409, {"error": str(exc)})
            if isinstance(exc, (mind.MindError, ValueError, FileNotFoundError)):
                return self._json(400, {"error": str(exc)})
            traceback.print_exc()
            return self._json(500, {"error": f"{exc.__class__.__name__}: {exc}"})

    return Handler


class _Counted:
    """A request body that remembers how much of it was read."""

    def __init__(self, stream):
        self.stream, self.read_bytes = stream, 0

    def read(self, n: int) -> bytes:
        data = self.stream.read(n)
        self.read_bytes += len(data)
        return data


def _summary(result: dict) -> dict:
    return {"ready": len(result.get("ready", [])), "tasks": len(result.get("tasks", [])),
            "warnings": [str(x) for x in result.get("log_errors", [])],
            "errors": {str(k): str(v) for k, v in (result.get("errors") or {}).items()}}


def serve(root: Path, port: int = 0, lang: str | None = None) -> ThreadingHTTPServer:
    """Starts the app in a background thread; `server.url` opens it, `server.token` drives it."""
    root = Path(root).resolve()
    i18n.choose(root, lang)
    kit.init_workspace(root, lang)
    token = secrets.token_urlsafe(24)
    port_box: dict = {}
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(root, token, Job(), port_box))
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
