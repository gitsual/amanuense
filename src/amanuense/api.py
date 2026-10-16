"""
api — the workshop as a FastAPI router, for a host that already serves a web app.

Optional: needs `pip install 'amanuense[fastapi]'`. The router only reads (the review
screens' state, a page, the job, a task, a Markdown preview); the host adds it with
`install(app, workspace)`. It has no route to stop the process or to open a local program.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

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

API_VERSION = 1  # bumped when a route is added or changes; the host checks it
MAX_BODY = 2_000_000


class _Route(APIRoute):
    """Answers a failed call with the same status and `{"error": …}` body as the standard-library server."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await handler(request)
            except (HTTPException, RequestValidationError):
                raise
            except Exception as exc:
                status, body = service.error_status(exc)
                return JSONResponse(body, status_code=status)
        return guarded


router = APIRouter(prefix="/api/amanuense", tags=["amanuense"], route_class=_Route)


def install(app: FastAPI, workspace: Path | str, *, vault: Path | None = None, on_vault_changed=None,
            lang: str | None = None) -> service.Workshop:
    """Serve the workshop at `workspace` from `app`. One workshop per app; nothing is written to it."""
    folder = Path(workspace)
    if not folder.is_dir():
        raise FileNotFoundError(f"workshop folder not found: {folder}")
    if getattr(app.state, "amanuense", None) is not None:
        raise RuntimeError("amanuense is already installed in this app")
    app.state.amanuense = service.Workshop(folder, lang, init=False, vault=vault, on_vault_changed=on_vault_changed)
    app.include_router(router)
    return app.state.amanuense


def _ws(request: Request) -> service.Workshop:
    return request.app.state.amanuense


def _rel(rel: str) -> str:
    """A page path as sent on the wire: relative and inside the workshop, whatever the separators."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).anchor or ".." in parts:
        raise ValueError("bad path")
    return rel


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
