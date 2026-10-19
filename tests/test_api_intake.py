"""api: the intake flow (plan, start, file, cancel, promote, job) for a host that mounts the router."""
import hashlib
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from amanuense import i18n, intake  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import _ready  # noqa: E402

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"


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
    folder = _ready(tmp_path, "# Convenciones\n\nTexto.\n")
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


def _start(client, headers):
    return client.post(f"{BASE}/intake/start", json={}, headers=headers).json()["batch"]


def _put(client, headers, batch, path, data, **extra):
    h = {**headers, "Content-Type": "application/octet-stream",
         "X-Content-SHA256": hashlib.sha256(data if isinstance(data, bytes) else b"").hexdigest(), **extra}
    return client.post(f"{BASE}/intake/file", params={"batch": batch, "path": path}, content=data, headers=h)


def _dir(folder, batch):
    return folder / i18n.name("local") / batch


def _files(folder, batch):
    return sorted(p.name for p in (_dir(folder, batch)).rglob("*") if p.is_file())


ROUTES = ["/intake/plan", "/intake/start", "/intake/file", "/intake/cancel", "/intake/promote", "/job"]


def test_every_intake_route_is_registered_and_needs_the_token(host):
    from amanuense import api
    _app, _folder, client, _h = host
    assert set(ROUTES) <= set(api.MUTATING)
    for path in ROUTES:
        got = client.post(f"{BASE}{path}", json={})
        assert got.status_code == 403 and got.json() == {"error": "token"}, path


def test_the_plan_classifies_files_and_works_during_a_job(host, blocking):
    app, _f, client, h = host
    files = [{"path": "p/a.md", "size": 3, "sha256": "a" * 64}, {"path": "p/a copy.md", "size": 3, "sha256": "a" * 64},
             {"path": "p/x.pdf", "size": 3, "sha256": "b" * 64}]
    got = client.post(f"{BASE}/intake/plan", json={"files": files}, headers=h)
    assert got.status_code == 200 and [i["reason"] for i in got.json()["items"]] == ["", "duplicate", "pdf"]
    app.state.amanuense.start_job("run", {})
    assert client.post(f"{BASE}/intake/plan", json={"files": files}, headers=h).status_code == 200


def test_the_plan_accepts_a_body_beyond_the_ordinary_limit_but_not_beyond_its_own(host):
    _a, _f, client, h = host
    ok = {"files": [{"path": f"p/{i}.md", "size": 1, "sha256": "a" * 64} for i in range(1)], "pad": "x" * 3_000_000}
    assert client.post(f"{BASE}/intake/plan", json=ok, headers=h).status_code == 200
    big = {"pad": "x" * 16_100_000}
    assert client.post(f"{BASE}/intake/plan", json=big, headers=h).status_code == 413
    assert client.post(f"{BASE}/intake/start", json=ok, headers=h).status_code == 413  # ordinary routes keep 2 MB


def test_start_upload_and_cancel_a_batch(host):
    _a, folder, client, h = host
    batch = _start(client, h)
    assert batch.startswith("intake-")
    got = _put(client, h, batch, "C:\\pile\\sub\\Notes.md", b"# Notes\n")
    assert got.status_code == 200 and got.json() == {"stored": f"{batch}/pile/sub/Notes.md"}
    assert (_dir(folder, batch) / "pile" / "sub" / "Notes.md").read_bytes() == b"# Notes\n"
    assert client.post(f"{BASE}/intake/cancel", json={"batch": batch}, headers=h).json() == {"ok": True}
    assert not _dir(folder, batch).exists()


def test_uploads_are_refused_like_the_standalone_app(host, monkeypatch):
    _a, folder, client, h = host
    batch = _start(client, h)
    assert _put(client, h, batch, "../../evil.md", b"x").status_code == 400
    assert _put(client, h, batch, "tool.exe", b"MZ").status_code == 400
    assert _put(client, h, "../..", "a.md", b"x").status_code == 400
    got = _put(client, h, batch, "bad.md", b"x", **{"X-Content-SHA256": "0" * 64})
    assert got.status_code == 400 and got.json()["error"]
    assert _put(client, h, batch, "a.md", b"x", **{"Content-Type": "text/plain"}).status_code == 415
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 10)
    got = _put(client, h, batch, "big.md", b"x" * 50)
    assert got.status_code == 413 and got.json()["error"]
    assert client.get(f"{BASE}/state").status_code == 200
    assert _files(folder, batch) == []


def test_a_file_larger_than_one_chunk_arrives_whole(host):
    _a, folder, client, h = host
    batch = _start(client, h)
    data = (b"# Big\n" + b"0123456789abcdef" * 1024) * 300  # about 4.9 MB
    got = _put(client, h, batch, "big.md", data)
    assert got.status_code == 200
    assert (_dir(folder, batch) / "big.md").read_bytes() == data


def test_the_body_is_streamed_to_the_workshop_not_read_whole(host, monkeypatch):
    app, _f, client, h = host
    seen = {}

    def upload(batch, path, stream, size, sha):
        seen["first"] = len(stream.read(10))
        seen["max_chunk"] = 0
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            seen["max_chunk"] = max(seen["max_chunk"], len(chunk))
        return "ok"
    monkeypatch.setattr(app.state.amanuense, "upload", upload)
    data = b"x" * 3_000_000
    assert _put(client, h, "b", "a.md", data).json() == {"stored": "ok"}
    assert seen["first"] == 10 and seen["max_chunk"] <= 65536


def test_a_truncated_body_is_an_error_and_leaves_nothing(host):
    import io
    app, folder, client, h = host
    batch = _start(client, h)
    with pytest.raises(intake.IntakeError):
        app.state.amanuense.upload(batch, "a.md", io.BytesIO(b"abc"), 100, "")
    assert _files(folder, batch) == []


def test_uploading_and_starting_wait_for_a_running_job(host, blocking):
    app, folder, client, h = host
    batch = _start(client, h)
    app.state.amanuense.start_job("run", {})
    assert _put(client, h, batch, "a.md", b"# A\n").status_code == 423
    assert client.post(f"{BASE}/intake/start", json={}, headers=h).status_code == 423
    assert client.post(f"{BASE}/intake/cancel", json={"batch": batch}, headers=h).status_code == 423
    assert _files(folder, batch) == []


def test_cancel_refuses_a_batch_this_process_did_not_start(host):
    _a, folder, client, h = host
    _dir(folder, "intake-20200101-000000").mkdir(parents=True)
    got = client.post(f"{BASE}/intake/cancel", json={"batch": "intake-20200101-000000"}, headers=h)
    assert got.status_code == 400 and _dir(folder, "intake-20200101-000000").exists()


def test_promote_needs_a_rel(host):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/intake/promote", json={}, headers=h).status_code == 400


def test_the_job_route_only_runs_known_jobs_and_reports_busy(host, blocking):
    app, _f, client, h = host
    assert client.post(f"{BASE}/job", json={"name": "rm -rf"}, headers=h).status_code == 404
    assert client.post(f"{BASE}/job", json={}, headers=h).status_code == 404
    assert client.post(f"{BASE}/job", json={"name": "intake"}, headers=h).status_code == 400  # no batch
    started = client.post(f"{BASE}/job", json={"name": "run"}, headers=h)
    assert started.status_code == 200 and started.json()["running"] is True and started.json()["name"] == "run"
    assert client.post(f"{BASE}/job", json={"name": "run"}, headers=h).status_code == 423
    assert client.get(f"{BASE}/job").json()["running"] is True
