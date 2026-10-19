"""api: the review routes (save, resolve, approve, reopen, discard, promote) for a host that mounts the router."""
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from amanuense import registro as log  # noqa: E402
from amanuense import revision  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import COMMIT, NEW, UPDATE, _ready  # noqa: E402

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"
CONFLICT = "CONFLICTO: el repo dice dev"
ROUTES = ["/save", "/resolve", "/approve", "/reopen", "/discard", "/promote"]


@pytest.fixture
def host(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from amanuense import api
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    folder = _ready(tmp_path, f"# Convenciones de nomenclatura\n\n> {CONFLICT}\n\nResto.\n")
    app = FastAPI()
    api.install(app, folder)
    client = TestClient(app, base_url=LOCAL)
    token = client.get(f"{BASE}/session").json()["token"]
    return app, folder, client, {HEADER: token}


@pytest.fixture
def blocking(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


def _result(folder, rel):
    return (folder / docs_kit.OUT_DIR / rel / "RESULTADO.md").read_text(encoding="utf-8")


def _set_aside(folder):
    """A task the triage left out, as `revision.set_aside` lists it."""
    out = folder / docs_kit.OUT_DIR
    task = out / "codigo" / "pagina-antigua-def456"
    task.mkdir(parents=True)
    (task / "ACTUAL.md").write_text("# Página antigua\n", encoding="utf-8")
    (task / log.TRIAGE_FILE).write_text(json.dumps({"categoria": "ruido", "motivo": "solo tests"}), encoding="utf-8")
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    entries.append({"id": "c2", "kind": "codigo", "repo": "r", "branch": "b", "by": "Ana", **COMMIT,
                    "task_pages": {"codigo/pagina-antigua-def456": "Página antigua"}})
    (out / log.LOG_JSON).write_text(json.dumps(entries), encoding="utf-8")
    return task, "codigo/pagina-antigua-def456"


def test_every_review_route_is_registered_and_needs_the_token(host):
    from amanuense import api
    _app, folder, client, _h = host
    assert set(ROUTES) <= set(api.MUTATING)
    before = _result(folder, UPDATE)
    for path in ROUTES:
        got = client.post(f"{BASE}{path}", json={"rel": UPDATE, "markdown": "x", "reason": "r",
                                                 "notice": CONFLICT, "decision": "d"})
        assert got.status_code == 403 and got.json() == {"error": "token"}, path
    assert _result(folder, UPDATE) == before
    assert client.get(f"{BASE}/page", params={"rel": UPDATE}).json()["proposal"]["status"] == "pendiente"


def test_save_shows_in_the_page_and_marks_it_edited(host):
    _a, folder, client, h = host
    assert client.get(f"{BASE}/page", params={"rel": UPDATE}).json()["edited"] is False
    got = client.post(f"{BASE}/save", json={"rel": UPDATE, "markdown": "# Convenciones de nomenclatura\n\nEditado."},
                      headers=h)
    assert got.status_code == 200 and got.json()["edited"] is True and "Editado." in got.json()["result"]
    page = client.get(f"{BASE}/page", params={"rel": UPDATE}).json()
    assert page["edited"] is True and "Editado." in page["result"]
    assert "Editado." in _result(folder, UPDATE)


def test_save_needs_the_text_and_a_page_inside_the_workshop(host):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/save", json={"rel": UPDATE}, headers=h).status_code == 400  # no markdown
    assert client.post(f"{BASE}/save", json={"markdown": "x"}, headers=h).status_code == 400  # no rel


def test_approve_waits_for_the_conflict_then_resolve_and_approve_walk(host):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/approve", json={"rel": UPDATE}, headers=h).status_code == 409
    got = client.post(f"{BASE}/resolve", json={"rel": UPDATE, "notice": CONFLICT, "decision": "Apariencia es básica."},
                      headers=h)
    assert got.status_code == 200 and got.json()["proposal"]["conflicts"] == 0
    got = client.post(f"{BASE}/approve", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 200 and got.json()["proposal"]["status"] == "aprobada"


def test_discard_needs_a_reason_and_reopen_brings_the_page_back(host):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/discard", json={"rel": NEW}, headers=h).status_code == 400
    assert client.post(f"{BASE}/discard", json={"rel": NEW, "reason": ""}, headers=h).status_code == 400
    got = client.post(f"{BASE}/discard", json={"rel": NEW, "reason": "duplicada"}, headers=h)
    assert got.status_code == 200 and got.json()["proposal"]["status"] == "descartada"
    got = client.post(f"{BASE}/reopen", json={"rel": NEW}, headers=h)
    assert got.status_code == 200 and got.json()["proposal"]["status"] == "pendiente"


def test_promote_sends_a_set_aside_task_back_to_be_written(host):
    _a, folder, client, h = host
    task, rel = _set_aside(folder)
    assert [x["rel"] for x in revision.set_aside(folder)] == [rel]
    assert client.post(f"{BASE}/promote", json={}, headers=h).status_code == 400  # no rel
    assert client.post(f"{BASE}/promote", json={"rel": rel}, headers=h).json() == {"ok": True}
    assert json.loads((task / log.TRIAGE_FILE).read_text(encoding="utf-8"))["categoria"] == "actualizar"
    assert revision.set_aside(folder) == []


def test_save_waits_while_a_job_runs_and_leaves_the_file_alone(host, blocking):
    app, folder, client, h = host
    before = _result(folder, UPDATE)
    app.state.amanuense.start_job("run", {})
    for path, body in (("/save", {"rel": UPDATE, "markdown": "# X\n\nPerdido."}), ("/approve", {"rel": NEW}),
                       ("/discard", {"rel": NEW, "reason": "r"})):
        assert client.post(f"{BASE}{path}", json=body, headers=h).status_code == 423, path
    assert _result(folder, UPDATE) == before
    blocking.set()
    for _ in range(200):
        if not client.get(f"{BASE}/job").json()["running"]:
            break
        threading.Event().wait(0.02)
    assert client.post(f"{BASE}/approve", json={"rel": NEW}, headers=h).status_code == 200
