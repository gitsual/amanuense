"""The per-process session token, the Host/Origin filter and busy gating of mutating routes."""
import logging
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from amanuense import taller as docs_kit  # noqa: E402
from test_revision import _ready  # noqa: E402

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"


@pytest.fixture
def stubs(monkeypatch):
    """Two stub mutating routes registered through the registry: one busy-gated, one not. Counts side effects."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from amanuense import api
    calls = {"gated": 0, "free": 0}
    router = api.router
    before = list(router.routes)
    registry = dict(api.MUTATING)

    @api.mutating("/stub/gated")
    def gated() -> dict:
        calls["gated"] += 1
        return {"ok": True}

    @api.mutating("/stub/free", busy=False)
    def free() -> dict:
        calls["free"] += 1
        return {"ok": True}

    yield calls
    router.routes[:] = before
    api.MUTATING.clear()
    api.MUTATING.update(registry)


@pytest.fixture
def host(tmp_path, monkeypatch, stubs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from amanuense import api
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    folder = _ready(tmp_path, "# Convenciones\n\nTexto.\n")
    app = FastAPI()
    api.install(app, folder)
    return app, TestClient(app, base_url=LOCAL)


@pytest.fixture
def client(host):
    return host[1]


@pytest.fixture
def token(client):
    return client.get(f"{BASE}/session", headers={"Sec-Fetch-Site": "same-origin"}).json()["token"]


@pytest.fixture
def blocking(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


def _mutating():
    from amanuense import api
    return sorted(api.MUTATING)


# ── /session ───────────────────────────────────────────────────────────────────

def test_session_refuses_a_cross_site_request_without_issuing_a_token(client):
    got = client.get(f"{BASE}/session", headers={"Sec-Fetch-Site": "cross-site"})
    assert got.status_code == 403 and "token" not in got.json()


def test_session_answers_a_same_origin_request_with_a_token_that_is_not_cached(client):
    got = client.get(f"{BASE}/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    assert len(got.json()["token"]) >= 32  # token_urlsafe(24) is 32 characters


def test_session_accepts_a_request_without_fetch_metadata(client):
    assert client.get(f"{BASE}/session").status_code == 200


def test_session_refuses_a_foreign_origin_and_a_foreign_host(client):
    assert client.get(f"{BASE}/session", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get(f"{BASE}/session", headers={"Origin": LOCAL}).status_code == 200
    assert client.get(f"{BASE}/session", headers={"Host": "evil.example"}).status_code == 403


def test_session_returns_the_same_token_for_the_whole_process(client):
    assert client.get(f"{BASE}/session").json()["token"] == client.get(f"{BASE}/session").json()["token"]


def test_the_token_lives_on_the_app_so_it_exists_without_a_workshop():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    api._security(app)
    assert app.state.amanuense_token and getattr(app.state, "amanuense", None) is None
    first = app.state.amanuense_token
    api._security(app)  # idempotent: a second call keeps the token
    assert app.state.amanuense_token == first


# ── Mutating routes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/stub/gated", "/stub/free"])
def test_a_mutating_route_without_the_header_is_403_and_has_no_effect(client, stubs, path):
    got = client.post(f"{BASE}{path}", json={})
    assert got.status_code == 403 and got.json() == {"error": "token"}
    assert stubs == {"gated": 0, "free": 0}


@pytest.mark.parametrize("path", ["/stub/gated", "/stub/free"])
def test_a_mutating_route_with_the_wrong_token_is_403(client, stubs, token, path):
    assert client.post(f"{BASE}{path}", json={}, headers={HEADER: token + "x"}).status_code == 403
    assert client.post(f"{BASE}{path}", json={}, headers={HEADER: ""}).status_code == 403
    assert stubs == {"gated": 0, "free": 0}


@pytest.mark.parametrize("path", ["/stub/gated", "/stub/free"])
def test_a_mutating_route_with_the_valid_token_passes(client, token, path):
    assert client.post(f"{BASE}{path}", json={}, headers={HEADER: token}).json() == {"ok": True}


def test_a_mutating_route_refuses_a_foreign_host_even_with_the_token(host, token):
    app, _client = host
    from fastapi.testclient import TestClient
    evil = TestClient(app, base_url="http://evil.example")
    assert evil.post(f"{BASE}/stub/free", json={}, headers={HEADER: token}).status_code == 403


def test_every_registered_mutating_route_is_protected(client, stubs):
    assert {"/stub/gated", "/stub/free"} <= set(_mutating())
    for path in _mutating():
        assert client.post(f"{BASE}{path}", json={}).status_code == 403, path


def test_a_running_job_blocks_gated_mutations_with_423_but_not_the_free_ones(host, token, stubs, blocking):
    app, client = host
    app.state.amanuense.start_job("run", {})
    headers = {HEADER: token}
    got = client.post(f"{BASE}/stub/gated", json={}, headers=headers)
    assert got.status_code == 423 and got.json()["error"] and stubs["gated"] == 0
    assert client.post(f"{BASE}/stub/free", json={}, headers=headers).status_code == 200
    assert client.post(f"{BASE}/preview", json={"markdown": "x"}).status_code == 200
    assert client.get(f"{BASE}/job").status_code == 200
    assert client.get(f"{BASE}/session").status_code == 200


def test_the_token_check_comes_before_the_busy_check(host, stubs, blocking):
    app, client = host
    app.state.amanuense.start_job("run", {})
    assert client.post(f"{BASE}/stub/gated", json={}).status_code == 403


def test_the_registry_records_which_routes_wait_for_jobs(stubs):
    from amanuense import api
    assert api.MUTATING["/stub/gated"] is True and api.MUTATING["/stub/free"] is False
    assert "/preview" not in api.MUTATING and "/session" not in api.MUTATING


def test_the_token_never_reaches_the_logs(client, token, caplog):
    with caplog.at_level(logging.DEBUG):
        client.get(f"{BASE}/session")
        client.post(f"{BASE}/stub/free", json={}, headers={HEADER: token})
        client.post(f"{BASE}/stub/free", json={}, headers={HEADER: "wrong-" + token})
    assert token not in caplog.text
