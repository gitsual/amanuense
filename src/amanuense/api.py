"""
api — the workshop as a FastAPI router, for a host that already serves a web app.

Optional: needs `pip install 'amanuense[fastapi]'`. The router reads (the review screens'
state, a page, the job, a task, a Markdown preview) and hands out the per-process session
token that every mutating route requires; the host adds it with `install(app, workspace)`.
It has no route to stop the process or to open a local program.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
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

API_VERSION = 1  # bumped when a route is added or changes; the host checks it
MAX_BODY = 2_000_000
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
            lang: str | None = None, settings_notes=None) -> service.Workshop:
    """Serve the workshop at `workspace` from `app`. One workshop per app; nothing is written to it."""
    folder = Path(workspace)
    if not folder.is_dir():
        raise FileNotFoundError(f"workshop folder not found: {folder}")
    _claim(app)
    app.state.amanuense_notes = settings_notes
    _security(app)
    app.state.amanuense = service.Workshop(folder, lang, init=False, vault=vault, on_vault_changed=on_vault_changed)
    app.include_router(router)
    return app.state.amanuense


def install_settings(app: FastAPI, *, settings_notes=None) -> None:
    """Reduced install: only `/session` and the settings routes, with no workshop (to fix a bad workspace)."""
    _claim(app)
    app.state.amanuense_reduced = True
    app.state.amanuense_notes = settings_notes
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
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).anchor or ".." in parts:
        raise ValueError("bad path")
    return "/".join(parts)


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


# ── Settings: the same routes with a workshop and in the reduced install ────────

_REDUCED = frozenset(f"/api/amanuense{p}" for p in ("/session", "/settings", "/settings/test", "/settings/forget"))


def _listing(request: Request) -> dict:
    notes = getattr(request.app.state, "amanuense_notes", None)
    return {"config_file": str(settings.config_dir() / settings.FILE), "revision": settings.revision(),
            "fields": settings.fields(notes=notes() if notes else {})}


@router.get("/settings")
def settings_get(request: Request) -> dict:
    return _listing(request)


@mutating("/settings")
def settings_post(request: Request, body: dict = Depends(_limit(MAX_BODY))) -> dict:
    values, revision = body.get("values"), body.get("revision")
    if not isinstance(values, dict) or not (revision is None or isinstance(revision, str)):
        raise ValueError("bad request")
    warnings = settings.update(values, revision=revision)["warnings"]
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
