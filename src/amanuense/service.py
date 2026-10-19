"""
service — the workshop as a framework-free core.

Everything the review screens need (what to show, what a reviewer can do, the one
background job) lives here, with no web framework in sight. Two thin adapters drive it:
the standard-library server in `app` and, when FastAPI is installed, the router in `api`.
"""
from __future__ import annotations

import difflib
import hmac
import secrets
import shutil
import threading
import traceback
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from . import i18n
from . import intake
from . import mind
from . import registro as log
from . import revision
from . import settings
from . import space
from . import taller as kit

TOKEN_HEADER = "X-Amanuense-Token"
READS_ONLY = frozenset({"preview", "preflight", "settings/test", "intake/plan"})  # allowed while a job runs
JOBS = frozenset({"run", "intake", "radiator", "deliver", "rework"})
# actions whose body names a page of the workshop; `rel` is checked before any of them runs
PAGE_ACTIONS = frozenset({"save", "resolve", "approve", "reopen", "discard", "promote",
                          "mark-published", "publish", "undo", "preflight"})


class Busy(Exception):
    """A job is running; edits wait for it."""


class Unknown(KeyError):
    """No such action or job."""


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"name": "", "running": False, "started": "", "finished": "", "result": None, "error": "",
                      "progress": {"stage": "", "done": 0, "total": 0}}

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

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)


# ── Token and errors ───────────────────────────────────────────────────────────

def new_token() -> str:
    return secrets.token_urlsafe(24)


def check_token(expected: str, given: str | None) -> bool:
    return hmac.compare_digest(expected.encode(), (given or "").encode())


def error_status(exc: Exception) -> tuple[int, dict]:
    """The HTTP status and JSON body every transport answers with for a failed call."""
    if isinstance(exc, Busy):
        return 423, {"error": i18n.t("ui_busy")}
    if isinstance(exc, Unknown):
        return 404, {"error": "not found"}
    if isinstance(exc, revision.ReviewError):
        return 409, {"error": str(exc)}
    if isinstance(exc, intake.TooBig):
        return 413, {"error": str(exc)}
    if isinstance(exc, settings.Invalid):
        return 400, {"error": str(exc), "fields": exc.fields}
    if isinstance(exc, settings.Conflict):
        return 409, {"error": str(exc), "revision": exc.revision}
    if isinstance(exc, (mind.MindError, ValueError, FileNotFoundError)):
        return 400, {"error": str(exc)}
    traceback.print_exc()
    return 500, {"error": f"{exc.__class__.__name__}: {exc}"}


# ── What the page shows ────────────────────────────────────────────────────────

def ui_texts() -> dict:
    return {k: v[i18n.current()] for k, v in i18n.TEXT.items() if k.startswith(("ui_", "status_", "origin_"))}


def diff(before: str, after: str) -> list[dict]:
    a, b = before.splitlines(), after.splitlines()
    return [{"op": op, "a": a[i1:i2], "b": b[j1:j2], "a_start": i1 + 1, "b_start": j1 + 1}
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()]


def page_rel(rel) -> str:
    """The `rel` of an action: a non-empty string, then the same rule as `safe_rel`."""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(i18n.t("ui_missing", fields="rel"))
    return safe_rel(rel)


def safe_rel(rel: str) -> str:
    """A page path as sent on the wire: relative and inside the workshop, whatever the separators."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).anchor or ".." in parts:
        raise ValueError("bad path")
    return "/".join(parts)


def _checked(name: str, names: frozenset, body: dict) -> dict:
    """The body with a clean `rel`, or ValueError, for the actions that name a page."""
    return {**body, "rel": page_rel(body.get("rel"))} if name in names else body


def need(body: dict, *keys: str) -> list:
    missing = [k for k in keys if not str(body.get(k) or "").strip()]
    if missing:
        raise ValueError(i18n.t("ui_missing", fields=", ".join(missing)))
    return [body[k] for k in keys]


def web_url(value) -> str:
    """The address as typed, only when it is an http(s) link with a host: it ends up as an href."""
    url = str(value or "").strip()
    try:
        parts = urlsplit(url)
        ok = parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(i18n.t("ui_bad_url"))
    return url


def summary(result: dict) -> dict:
    return {"ready": len(result.get("ready", [])), "tasks": len(result.get("tasks", [])),
            "warnings": [str(x) for x in result.get("log_errors", [])],
            "errors": {str(k): str(v) for k, v in (result.get("errors") or {}).items()}}


def _client():
    c = settings.mind_client()
    if not c:
        raise ValueError(i18n.t("ui_mind_not_configured"))
    return c


def _history():
    data = settings.load()
    if data["url"] and data["token"]:
        return log.ConfluenceHistory(data["url"], data["token"], data["space"], data["user"])
    return None


def _ai():
    c = settings.ai_client()
    if not c:
        raise ValueError(i18n.t("ui_ai_not_configured"))
    return c


class Workshop:
    """One workshop folder, its single background job and the batches opened in this process."""

    def __init__(self, root: Path, lang: str | None = None, *, init: bool = True, vault: Path | None = None,
                 on_vault_changed=None):
        self.root = Path(root).resolve()
        i18n.choose(self.root, lang)
        if init:
            kit.init_workspace(self.root, lang)
        self.vault, self.on_vault_changed = vault, on_vault_changed
        self.job = Job()
        self.ledger = intake.Ledger(self.root)
        self._started: set[str] = set()  # batches this process opened: only these can be cancelled
        self._started_lock = threading.Lock()
        self._jobs = {
            "run": lambda body: self._compare(),
            "intake": lambda body: self._compare(need(body, "batch")[0]),
            "radiator": lambda body: lambda: str(kit.radiator_workspace(self.root)),
            "deliver": lambda body: lambda: str(kit.deliver_workspace(self.root, make_zip=True)),
            "rework": self._rework,
        }
        self._actions = self._build_actions()

    # reads
    def state(self, *, texts: bool = True) -> dict:
        root = self.root
        snap = log._load(root / i18n.name("out") / i18n.name("snapshot"), {})
        out = {"lang": i18n.current(), "user": log._user(), "workspace": str(root),
               "proposals": revision.proposals(root), "set_aside": revision.set_aside(root),
               "job": self.job.snapshot(), "settings": settings.summary(), "engines": sorted(kit.ENGINES),
               "exported": snap.get("created", ""), "pages": sorted(snap.get("pages", {})),
               "source": space.last_summary(root), "planned_source": self._planned_source(),
               "intake": intake.load_summary(root), "formats": intake.READABLE,
               "limits": {"max_file": intake.MAX_FILE_BYTES, "max_batch": intake.MAX_BATCH_BYTES,
                          "max_files": intake.MAX_BATCH_FILES},
               "local_dir": i18n.name("local"), "export_dir": i18n.name("export"),
               "ignore_file": i18n.name("intake_ignore")}
        return {**out, "texts": ui_texts()} if texts else out

    def detail(self, rel: str) -> dict:
        root = self.root
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
        return {"proposal": proposal, "result": result, "before": before, "diff": diff(before, result),
                "preview": kit.markdown_to_html(result),
                "paste": kit.markdown_to_html(mind.strip_title(result, proposal["title"])),
                "triage": log._load(d / log.TRIAGE_FILE, {}), "requests": requests, "commits": commits,
                "history": history,
                "edited": (d / (Path(i18n.name("result")).stem + revision.AI_COPY)).is_file()}

    def task(self, rel: str) -> dict:
        path = self.root / i18n.name("out") / revision.find(self.root, rel)["rel"] / i18n.name("task")
        return {"text": path.read_text(encoding="utf-8")}

    def target(self, what: str) -> Path:
        out = self.root / i18n.name("out")
        targets = {"log": out / i18n.name("log_html"), "radiator": out / "radiador" / "index.html",
                   "workspace": self.root, "output": out}
        deliveries = sorted(out.glob(i18n.name("delivery") + "-*"))
        if deliveries:
            targets["delivery"] = [p for p in deliveries if p.is_dir()][-1]
        path = targets.get(what)
        if not path or not path.exists():
            raise ValueError(i18n.t("ui_nothing_to_open"))
        return path

    # writes
    def act(self, action: str, body: dict) -> dict:
        """One action; Unknown if it does not exist, Busy while a job runs unless it only reads."""
        if action not in self._actions:
            raise Unknown(action)
        body = _checked(action, PAGE_ACTIONS, body)
        run = self._actions[action]
        if action not in READS_ONLY and self.job.running():
            raise Busy()
        return run(body)

    def start_job(self, name: str, body: dict) -> dict:
        if name not in self._jobs:
            raise Unknown(name)
        self.job.start(name, self._jobs[name](body))
        return self.job.snapshot()

    def upload(self, batch: str, path: str, stream, size: int, sha: str) -> str:
        """One file of a pile: refused while a job runs or when too big, then stored (and hash-checked)."""
        if self.job.running():
            raise Busy()
        if size > intake.MAX_FILE_BYTES:
            raise intake.TooBig(i18n.t("intake_file_too_big", path=path or "?",
                                       mb=intake.MAX_FILE_BYTES // (1024 * 1024)))
        return self.ledger.store(batch, path, stream, size, sha)

    # internals
    def _planned_source(self) -> dict:
        """What a comparison would read now: Confluence live, the Word export, or nothing."""
        data = settings.load()
        if data["url"] and data["token"] and data["space"]:
            return {"kind": "live", "space": data["space"], "root": data["root_page"], "base": data["url"]}
        exports = kit._inputs(self.root / i18n.name("export"), ".docx")
        if exports:
            return {"kind": "export", "files": [e.name for e in exports],
                    "created": max((log.export_created(e) for e in exports), default="")}
        return {"kind": "none"}

    def _source(self) -> space.Source:
        """Confluence live when configured (its cached copy when it does not answer), else the export."""
        self.job.progress("fetch")
        try:
            client = settings.mind_client()
        except mind.MindError as exc:  # e.g. an http:// address: say it, and read the export
            return space.Source("export", None, warning=str(exc))
        return space.resolve(self.root, client, settings.load()["root_page"])

    def _compare(self, batch: str = ""):
        if batch:
            intake.batch_dir(self.root, batch)  # an unknown batch is refused before the job starts
        # Dropped files are compared with what was fetched last: fetching every repo first
        # takes minutes without VPN. "Look for changes" still fetches them.

        def work() -> dict:
            source = self._source()
            result = kit.run_workspace(self.root, None, None, settings.ai_client(), _history(), source=source,
                                       progress=self.job.progress, sync_repos=not batch)
            out = summary(result)
            out["source"] = result.get("source") or {}
            if batch:
                out["batch_name"] = batch
                out["batch"] = (intake.load_summary(self.root).get("batches") or {}).get(batch, {})
            return out
        return work

    def _rework(self, body: dict):
        model = _ai()  # the engine is checked first, as the legacy server did
        rel, instruction = need(body, "rel", "instruction")
        rel = page_rel(rel)
        return lambda: revision.rework(self.root, rel, instruction, model, log._user())["title"]

    def _start_batch(self, _body: dict) -> dict:
        batch = intake.new_batch(self.root)
        with self._started_lock:
            self._started.add(batch)
        return {"batch": batch, "folder": f"{i18n.name('local')}/{batch}"}

    def _cancel_batch(self, body: dict) -> dict:
        batch = str(body.get("batch", ""))
        with self._started_lock:
            if batch not in self._started:
                raise ValueError(i18n.t("intake_bad_batch"))
        try:
            shutil.rmtree(intake.batch_dir(self.root, batch))  # a failure keeps the batch ours: retry is possible
        except (FileNotFoundError, intake.IntakeError):
            pass  # the folder is already gone: nothing left to remove
        with self._started_lock:
            self._started.discard(batch)
        return {"ok": True}

    def _build_actions(self) -> dict:
        root, by = self.root, log._user

        def acted(action):
            """An action on one page; the answer is the page as it is now."""
            def call(b: dict) -> dict:
                rel = need(b, "rel")[0]
                action(rel, b)
                return self.detail(rel)
            return call

        return {
            "preview": lambda b: {"html": kit.markdown_to_html(str(b.get("markdown", "")))},
            "save": acted(lambda rel, b: revision.save_text(root, rel, need(b, "markdown")[0], by=by())),
            "resolve": acted(lambda rel, b: revision.resolve_notice(root, rel, *need(b, "notice", "decision"),
                                                                    by=by())),
            "approve": acted(lambda rel, b: revision.approve(root, rel, by=by())),
            "reopen": acted(lambda rel, b: revision.reopen(root, rel, by=by())),
            "discard": acted(lambda rel, b: revision.discard(root, rel, by=by(), reason=need(b, "reason")[0])),
            "mark-published": acted(lambda rel, b: revision.mark_published(
                root, rel, by=by(), mode="manual", url=web_url(need(b, "url")[0]), version=None)),
            "publish": acted(lambda rel, b: mind.publish(root, rel, _client(), by(), parent=b.get("parent") or None,
                                                         accept_warnings=bool(b.get("accept_warnings")))),
            "undo": acted(lambda rel, b: mind.undo(root, rel, _client(), by())),
            "promote": lambda b: (revision.promote(root, need(b, "rel")[0], by=by()), {"ok": True})[1],
            "preflight": lambda b: mind.preflight(root, need(b, "rel")[0], _client(), parent=b.get("parent") or None),
            "settings": lambda b: (settings.save(b), settings.summary())[1],
            "settings/forget": lambda b: (settings.forget_token(), settings.summary())[1],
            "settings/test": lambda b: {"user": _client().me()},
            "intake/plan": lambda b: intake.plan(root, [f for f in b.get("files") or [] if isinstance(f, dict)]),
            "intake/start": self._start_batch,
            "intake/cancel": self._cancel_batch,
            "intake/promote": lambda b: {"promoted": intake.promote(root, need(b, "rel")[0])},
        }
