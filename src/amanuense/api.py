"""
api — the workshop as a FastAPI router, for a host that already serves a web app.

Optional: needs `pip install 'amanuense[fastapi]'`. The router reads (the review screens'
state, a page, the job, a task, a Markdown preview), reviews (save, resolve, approve, reopen,
discard, promote), takes documentation in (the intake routes and `POST /job`) and hands out the per-process session
token that every mutating route requires; the host adds it with `install(app, workspace)`.
It has no route to stop the process or to open a local program.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import threading
from pathlib import Path
from urllib.parse import urlsplit

try:
    from fastapi import APIRouter, Depends, FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from fastapi.routing import APIRoute
    from starlette.exceptions import HTTPException
    from starlette.concurrency import run_in_threadpool
except ImportError as exc:
    raise ImportError("amanuense.api needs FastAPI: pip install 'amanuense[fastapi]'") from exc

from . import i18n
from . import intake
from . import service
from . import settings

API_VERSION = 3  # bumped when a route is added or changes; the host checks it
MAX_BODY = 2_000_000
MAX_PLAN_BODY = 16_000_000  # the list of a big pile (path, size and hash of each file)
_CHUNKS = 8  # request chunks held between the network and the disk
_PULL_TIMEOUT = 5.0  # seconds the worker waits for a chunk before checking whether the feeder is gone
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})  # Host names the token routes answer to
MUTATING: dict[str, bool] = {}  # mutating route path (below the prefix) -> waits for a running job


class _Denied(Exception):
    """A call refused before it reaches the workshop; answered 403 with `{"error": reason}`."""


class _Route(APIRoute):
    """Answers a failed call with the same status and `{"error": …}` body as the standard-library server."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await handler(request)
            except (HTTPException, RequestValidationError):
                raise
            except _Denied as denied:
                return JSONResponse({"error": str(denied)}, status_code=403)
            except Exception as exc:
                status, body = service.error_status(exc)
                return JSONResponse(body, status_code=status)
        return guarded


router = APIRouter(prefix="/api/amanuense", tags=["amanuense"], route_class=_Route)


def install(app: FastAPI, workspace: Path | str, *, vault: Path | None = None, on_vault_changed=None,
            lang: str | None = None, settings_notes=None, env=None) -> service.Workshop:
    """Serve the workshop at `workspace` from `app`. One workshop per app; nothing is written to it.

    `env` is the environment the settings routes read: a mapping, or a function returning one
    (called on every request). Default `os.environ`.
    """
    folder = Path(workspace)
    if not folder.is_dir():
        raise FileNotFoundError(f"workshop folder not found: {folder}")
    _claim(app)
    app.state.amanuense_notes = settings_notes
    app.state.amanuense_env = env
    _security(app)
    app.state.amanuense = service.Workshop(folder, lang, init=False, vault=vault, on_vault_changed=on_vault_changed)
    app.include_router(router)
    return app.state.amanuense


def install_settings(app: FastAPI, *, settings_notes=None, env=None) -> None:
    """Reduced install: only `/session` and the settings routes, with no workshop (to fix a bad workspace).

    `env` is the same environment view as in `install`.
    """
    _claim(app)
    app.state.amanuense_reduced = True
    app.state.amanuense_notes = settings_notes
    app.state.amanuense_env = env
    _security(app)
    reduced = APIRouter(route_class=_Route)  # the routes already carry the full path
    reduced.routes.extend(r for r in router.routes if r.path in _REDUCED)
    app.include_router(reduced)


def _claim(app: FastAPI) -> None:
    if getattr(app.state, "amanuense", None) is not None or getattr(app.state, "amanuense_reduced", False):
        raise RuntimeError("amanuense is already installed in this app")


def _security(app: FastAPI) -> str:
    """The session token of this process, on `app.state` so it exists with or without a workshop."""
    if getattr(app.state, "amanuense_token", None) is None:
        app.state.amanuense_token = service.new_token()
    return app.state.amanuense_token


def _host_ok(request: Request) -> bool:
    host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
    return host in LOOPBACK


def _require_token(request: Request) -> None:
    """Dependency of every mutating route: a loopback Host and the header issued by `/session`."""
    expected = getattr(request.app.state, "amanuense_token", None)
    if not _host_ok(request) or not expected or not service.check_token(expected, request.headers.get(service.TOKEN_HEADER)):
        raise _Denied("token")


def _idle(request: Request) -> None:
    """Dependency of the routes that edit the workshop: not while a job is running (423)."""
    ws = getattr(request.app.state, "amanuense", None)
    if ws is not None and ws.job.running():
        raise service.Busy()


def mutating(path: str, *, busy: bool = True, **options):
    """Register a POST route on the router behind the token (and, if `busy`, the job gate)."""
    MUTATING[path] = busy
    deps = [Depends(_require_token)] + ([Depends(_idle)] if busy else [])
    return router.post(path, dependencies=deps, **options)


def _ws(request: Request) -> service.Workshop:
    return request.app.state.amanuense


def _rel(rel: str) -> str:
    """A page path as sent on the wire: relative and inside the workshop, whatever the separators."""
    return service.safe_rel(rel)


def _limit(max_bytes: int):
    """A dependency: the JSON object in the body, read as it arrives and refused past `max_bytes`."""
    async def read(request: Request) -> dict:
        if int(request.headers.get("content-length") or 0) > max_bytes:
            raise intake.TooBig(i18n.t("ui_too_big"))
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > max_bytes:
                raise intake.TooBig(i18n.t("ui_too_big"))
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise ValueError("bad request")
        return body
    return read


@router.get("/session")
def session(request: Request) -> JSONResponse:
    """The token for this page's calls; refused to cross-site pages and to foreign Host or Origin."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if (not _host_ok(request) or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
            or (origin is not None and origin != f"http://{host}")):
        raise _Denied("session")
    return JSONResponse({"token": request.app.state.amanuense_token, "header": service.TOKEN_HEADER},
                        headers={"Cache-Control": "no-store"})


@router.get("/state")
def state(ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.state(texts=False)


@router.get("/page")
def page(rel: str = "", ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.detail(_rel(rel))


@router.get("/job")
def job(ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.job.snapshot()


@router.get("/task")
def task(rel: str = "", ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.task(_rel(rel))


@router.post("/preview")
async def preview(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return await run_in_threadpool(ws.act, "preview", body)


# ── Review: edit, resolve, approve, reopen, discard, promote; each answers with the page as it is now ──

@mutating("/save")
def review_save(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("save", body)


@mutating("/resolve")
def review_resolve(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("resolve", body)


@mutating("/approve")
def review_approve(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("approve", body)


@mutating("/reopen")
def review_reopen(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("reopen", body)


@mutating("/discard")
def review_discard(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("discard", body)


@mutating("/promote")
def review_promote(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    """A set-aside task goes back to be written; answers `{"ok": true}` (it has no page yet)."""
    return ws.act("promote", body)


# ── MIND publish: preflight reads, publish and undo write Confluence, mark-published records a manual one ──

@mutating("/preflight", busy=False)
def publish_preflight(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    """`{page, parent, blockers, warnings}`; it only reads, so it may run while a job does (as in the legacy app)."""
    return ws.act("preflight", body)


@mutating("/publish")
def publish_page(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    """Blockers are a 400; warnings need `accept_warnings: true`. Answers with the page as it is now."""
    return ws.act("publish", body)


@mutating("/undo")
def publish_undo(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("undo", body)


@mutating("/mark-published")
def publish_mark(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    """A person published it by hand: record the URL."""
    return ws.act("mark-published", body)


# ── Documentation intake: plan, start, file × N, job "intake", poll /job ───────

@mutating("/intake/plan", busy=False)
async def intake_plan(body: dict = Depends(_limit(MAX_PLAN_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return await run_in_threadpool(ws.act, "intake/plan", body)


@mutating("/intake/start")
def intake_start(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("intake/start", body)


@mutating("/intake/cancel")
def intake_cancel(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("intake/cancel", body)


@mutating("/intake/promote")
def intake_promote(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)) -> dict:
    return ws.act("intake/promote", body)


class _Pipe:
    """A blocking `read(n)` over chunks handed in by the event loop.

    The end is `None`; an exception handed in is raised to the reader. `size` is the declared length:
    the read that would deliver its last byte first waits for the end of the body, so a body longer
    than declared (or a client that went away) fails before the worker commits anything.
    """

    def __init__(self, size: int = 0):
        self.chunks: queue.Queue = queue.Queue(maxsize=_CHUNKS)
        self.size = size
        self.sent = 0
        self.rest = b""
        self.ended = False
        self.closed = threading.Event()  # set by the feeder when it is done, whatever it queued

    def close(self) -> None:
        self.closed.set()

    def _get(self):
        while True:
            try:
                return self.chunks.get(timeout=_PULL_TIMEOUT)
            except queue.Empty:
                if self.closed.is_set():  # the feeder is gone and nothing more is queued
                    try:
                        return self.chunks.get_nowait()
                    except queue.Empty:
                        return intake.IntakeError(i18n.t("intake_incomplete", path="?"))

    def _pull(self) -> None:
        item = self._get()
        if item is None:
            self.ended = True
        elif isinstance(item, BaseException):
            self.ended = True
            raise item
        else:
            self.rest += item

    def read(self, n: int) -> bytes:
        while len(self.rest) < n and not self.ended:
            self._pull()
        if self.sent + min(n, len(self.rest)) >= self.size:
            while not self.ended:  # the declared bytes are all here: the body must end now
                self._pull()
        out, self.rest = self.rest[:n], self.rest[n:]
        self.sent += len(out)
        return out


async def _feed(request: Request, pipe: _Pipe, worker: asyncio.Future, limit: int) -> None:
    """Hands the body to the worker chunk by chunk (never whole), counting what really arrives.

    Past `limit` bytes the worker gets a `TooBig`; if the stream breaks it gets the error. Either way
    the worker ends (and cleans up) instead of waiting. Stops early if the worker already finished.
    """
    async def put(item) -> bool:
        while not worker.done():
            try:
                pipe.chunks.put_nowait(item)
                return True
            except queue.Full:
                await asyncio.sleep(0.002)
        return False
    final, received = None, 0
    try:
        try:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    final = intake.TooBig(i18n.t("intake_body_longer"))
                    break
                if not await put(chunk):
                    break
        except BaseException as exc:
            final = intake.IntakeError(i18n.t("intake_incomplete", path="?"))
            await put(final)
            raise exc
        await put(final)
    finally:
        pipe.close()  # if `put(final)` never landed (cancelled), the worker still learns it must stop


def _declared_length(request: Request) -> int | None:
    """The Content-Length as a non-negative integer, or None when it is missing or malformed."""
    raw = request.headers.get("content-length", "").strip()
    return int(raw) if raw.isascii() and raw.isdigit() else None


async def _drain(request: Request, limit: int = 8 * MAX_BODY) -> None:
    """Reads a refused body away (up to a limit) so the client sees the answer, not a reset."""
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > limit:
            break


@mutating("/intake/file")
async def intake_file(request: Request, batch: str = "", path: str = "", ws: service.Workshop = Depends(_ws)):
    """One file of a pile, as it is: the raw body is streamed to disk as it arrives.

    `Content-Length` is required (411 when missing, chunked, or not a non-negative integer) and is
    checked against the bytes that really arrive: more is 413, fewer is 400, and nothing is kept.
    """
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/octet-stream":
        await _drain(request)
        return JSONResponse({"error": "application/octet-stream expected"}, status_code=415)
    size = _declared_length(request)
    if size is None:
        return JSONResponse({"error": "a valid Content-Length is required"}, status_code=411)
    sha = request.headers.get("x-content-sha256", "")
    if size == 0:  # nothing is read by the worker, so the body is checked first
        async for chunk in request.stream():
            if chunk:
                raise intake.TooBig(i18n.t("intake_body_longer"))
        return {"stored": await run_in_threadpool(ws.upload, batch, path, io.BytesIO(b""), 0, sha)}
    pipe = _Pipe(size)
    worker = asyncio.ensure_future(run_in_threadpool(ws.upload, batch, path, pipe, size, sha))
    failure = None
    try:
        await _feed(request, pipe, worker, min(size, intake.MAX_FILE_BYTES))
    except BaseException as exc:  # the client went away: the worker still ends and cleans up first
        failure = exc
    try:
        stored = await worker
    except BaseException:
        if failure is None:
            raise
    if failure is not None:
        raise failure
    return {"stored": stored}


@mutating("/job", busy=False)
def job_start(body: dict = Depends(_limit(MAX_BODY)), ws: service.Workshop = Depends(_ws)):
    """Starts a background job from the fixed list; a second one while it runs is 423. Poll `GET /job`."""
    name = str(body.get("name", ""))
    if name not in service.JOBS:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return ws.start_job(name, body)


# ── Settings: the same routes with a workshop and in the reduced install ────────

_REDUCED = frozenset(f"/api/amanuense{p}" for p in ("/session", "/settings", "/settings/test", "/settings/forget"))


def _env(request: Request):
    """The environment the settings read: the host's view (mapping or function) or `os.environ`."""
    view = getattr(request.app.state, "amanuense_env", None)
    return os.environ if view is None else view() if callable(view) else view


def _listing(request: Request) -> dict:
    notes = getattr(request.app.state, "amanuense_notes", None)
    return {"config_file": str(settings.config_dir() / settings.FILE), "revision": settings.revision(),
            "fields": settings.fields(_env(request), notes=notes() if notes else {})}


@router.get("/settings")
def settings_get(request: Request) -> dict:
    return _listing(request)


@mutating("/settings")
def settings_post(request: Request, body: dict = Depends(_limit(MAX_BODY))) -> dict:
    values, revision = body.get("values"), body.get("revision")
    if not isinstance(values, dict) or not (revision is None or isinstance(revision, str)):
        raise ValueError("bad request")
    warnings = settings.update(values, revision=revision, env=_env(request))["warnings"]
    return {**_listing(request), "warnings": warnings}


@mutating("/settings/forget")
def settings_forget(request: Request, body: dict = Depends(_limit(MAX_BODY))) -> dict:
    names = body.get("fields")
    if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
        raise ValueError("bad request")
    settings.forget(names)  # absent means every secret; an empty list means none
    return _listing(request)


@mutating("/settings/test", busy=False)
def settings_test() -> dict:
    return {"user": service._client().me()}
