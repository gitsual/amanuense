"""api: the optional FastAPI router over the service (read-only routes)."""
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amanuense import taller as docs_kit  # noqa: E402
from test_revision import NEW, UPDATE, _ready  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE = "/api/amanuense"


def _python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(SRC))


# ── The extra and the optional import ──────────────────────────────────────────

def test_pyproject_declares_the_fastapi_extra_and_keeps_the_core_dependency_free():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["version"] == "0.4.4"
    assert meta["project"]["dependencies"] == []
    extras = meta["project"]["optional-dependencies"]
    assert extras["fastapi"] == ["fastapi>=0.115"]
    assert {"pytest>=8.0", "fastapi>=0.115", "httpx>=0.27"} <= set(extras["dev"])


def test_package_version_matches_pyproject():
    from amanuense import __version__
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == meta["project"]["version"]


def test_rel_normalises_backslashes_and_still_rejects_traversal():
    pytest.importorskip("fastapi")
    from amanuense import api
    assert api._rel("tareas\\01-x") == "tareas/01-x"
    for bad in ("../x", "a\\..\\b", "/abs"):
        with pytest.raises(ValueError):
            api._rel(bad)


def test_import_error_message_when_fastapi_missing():
    run = _python("import sys; sys.modules['fastapi'] = None\nimport amanuense.api")
    assert run.returncode != 0
    assert "ImportError" in run.stderr and "amanuense[fastapi]" in run.stderr


def test_the_router_has_no_way_to_stop_the_server_or_open_a_browser():
    pytest.importorskip("fastapi")
    from amanuense import api
    paths = {route.path for route in api.router.routes}
    assert paths == {f"{BASE}/state", f"{BASE}/page", f"{BASE}/job", f"{BASE}/task", f"{BASE}/preview",
                     f"{BASE}/session", f"{BASE}/settings", f"{BASE}/settings/test", f"{BASE}/settings/forget",
                     f"{BASE}/intake/plan", f"{BASE}/intake/start", f"{BASE}/intake/file", f"{BASE}/intake/cancel",
                     f"{BASE}/intake/promote", f"{BASE}/job", f"{BASE}/save", f"{BASE}/resolve",
                     f"{BASE}/approve", f"{BASE}/reopen", f"{BASE}/discard", f"{BASE}/promote",
                     f"{BASE}/preflight", f"{BASE}/publish", f"{BASE}/undo", f"{BASE}/mark-published",
                     f"{BASE}/vault", f"{BASE}/artifact/{{what}}"}
    source = (SRC / "amanuense" / "api.py").read_text(encoding="utf-8")
    assert "webbrowser" not in source and "shutdown" not in source and "/open" not in source


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    for k in ("AMANUENSE_CONFLUENCE_URL", "AMANUENSE_CONFLUENCE_TOKEN", "AMANUENSE_AI_CLI", "AMANUENSE_AI_URL"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture
def host(env):
    """(app, workshop folder, TestClient) with the router installed on a synthetic workshop."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from amanuense import api
    folder = _ready(env, "# Convenciones de nomenclatura\n\n> CONFLICTO: dev\n\nResto.\n")
    app = FastAPI()
    api.install(app, folder)
    return app, folder, TestClient(app)


@pytest.fixture
def client(host):
    return host[2]


@pytest.fixture
def blocking(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


# ── install ────────────────────────────────────────────────────────────────────

def test_install_exposes_the_workshop_and_the_api_version(host):
    from amanuense import api, service
    app, folder, _client = host
    assert api.API_VERSION == 3
    assert isinstance(app.state.amanuense, service.Workshop) and app.state.amanuense.root == folder.resolve()


def test_install_does_not_touch_the_workshop_folder(env):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from amanuense import api
    folder = _ready(env)
    before = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))
    api.install(FastAPI(), folder)
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == before
    assert before  # the synthetic workshop is not empty: the comparison means something


def test_install_on_a_missing_folder_registers_nothing(env):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    routes = len(app.routes)
    with pytest.raises(FileNotFoundError):
        api.install(app, env / "nowhere")
    assert len(app.routes) == routes and not hasattr(app.state, "amanuense")
    afile = env / "afile"
    afile.write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError):  # a file is not a workshop either
        api.install(app, afile)


def test_a_second_install_is_refused_and_keeps_the_first(host):
    from amanuense import api
    app, folder, client = host
    first = app.state.amanuense
    with pytest.raises(RuntimeError):
        api.install(app, folder)
    assert app.state.amanuense is first and client.get(f"{BASE}/state").status_code == 200


# ── Reads ──────────────────────────────────────────────────────────────────────

def test_state_lists_the_pages_without_texts_or_token(client):
    got = client.get(f"{BASE}/state")
    assert got.status_code == 200
    body = got.json()
    assert sorted(p["rel"] for p in body["proposals"]) == sorted([UPDATE, NEW])
    assert "texts" not in body and not any("token" in key for key in body)
    assert body["settings"]["has_token"] is False and "token" not in body["settings"]  # the PAT never travels


def test_page_has_the_opcodes_and_the_preview(client):
    body = client.get(f"{BASE}/page", params={"rel": UPDATE}).json()
    assert isinstance(body["diff"], list) and body["diff"] and {"op", "a", "b"} <= set(body["diff"][0])
    assert isinstance(body["preview"], str) and "Convenciones" in body["preview"]
    other = client.get(f"{BASE}/page", params={"rel": NEW}).json()
    assert other["proposal"]["rel"] == NEW and "Capacidad de mapas" in other["preview"]


def test_an_unknown_page_is_an_error_with_a_message(client):
    got = client.get(f"{BASE}/page", params={"rel": "tareas/99-nothing"})
    assert got.status_code == 409 and got.json()["error"]
    assert client.get(f"{BASE}/page").status_code == 409  # no rel at all: same answer, not a 422


def test_task_returns_the_text_of_the_task(client):
    got = client.get(f"{BASE}/task", params={"rel": UPDATE})
    assert got.status_code == 200 and got.json()["text"].strip()


@pytest.mark.parametrize("rel", ["../outside", "tareas/../../outside", "/etc/passwd", "..\\outside", "C:\\Windows"])
@pytest.mark.parametrize("route", ["page", "task"])
def test_paths_that_leave_the_workshop_are_refused(client, route, rel):
    got = client.get(f"{BASE}/{route}", params={"rel": rel})
    assert got.status_code == 400 and got.json()["error"]


def test_job_reports_progress_while_one_runs(host, blocking):
    app, _folder, client = host
    idle = client.get(f"{BASE}/job").json()
    assert idle["running"] is False
    app.state.amanuense.start_job("run", {})
    running = client.get(f"{BASE}/job").json()
    assert running["running"] is True and running["name"] == "run" and "progress" in running
    assert client.get(f"{BASE}/state").status_code == 200  # reads work while the job runs


# ── Preview ────────────────────────────────────────────────────────────────────

def test_preview_renders_markdown_and_escapes_scripts(client):
    ok = client.post(f"{BASE}/preview", json={"markdown": "# Hello\n\nA *word*."})
    assert ok.status_code == 200 and "<h1" in ok.json()["html"]
    evil = client.post(f"{BASE}/preview", json={"markdown": "<script>alert(1)</script>"})
    assert evil.status_code == 200 and "<script" not in evil.json()["html"].lower()


def test_preview_does_not_need_a_token_and_works_during_a_job(host, blocking):
    app, _folder, client = host
    app.state.amanuense.start_job("run", {})
    assert client.post(f"{BASE}/preview", json={"markdown": "text"}).status_code == 200


def test_oversize_bodies_get_413_whatever_the_header_says(client):
    big = b'{"markdown": "' + b"x" * 2_000_001 + b'"}'
    got = client.post(f"{BASE}/preview", content=big, headers={"Content-Type": "application/json"})
    assert got.status_code == 413 and got.json()["error"]
    small = b'{"markdown": "' + b"x" * 1_000 + b'"}'
    assert client.post(f"{BASE}/preview", content=small,
                       headers={"Content-Type": "application/json"}).status_code == 200


def test_a_chunked_body_without_a_length_is_counted_as_it_arrives(client):
    def chunks():
        yield b'{"markdown": "'
        for _ in range(21):
            yield b"x" * 100_000
        yield b'"}'
    got = client.post(f"{BASE}/preview", content=chunks(), headers={"Content-Type": "application/json"})
    assert got.status_code == 413 and got.json()["error"]


def test_a_body_that_is_not_a_json_object_is_a_bad_request(client):
    assert client.post(f"{BASE}/preview", content=b"nope",
                       headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post(f"{BASE}/preview", json=["a"]).status_code == 400
