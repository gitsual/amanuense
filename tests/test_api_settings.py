"""The settings routes: listing, saving, forgetting, testing, and the reduced-mode install."""
import json
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

MISSING = str(Path(Path.cwd().anchor) / "no" / "such" / "folder")  # absolute on POSIX and Windows

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"
SAME = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(cfg))
    for name in ("AMANUENSE_AI_URL", "AMANUENSE_CONFLUENCE_ROOT", "AMANUENSE_CONFLUENCE_URL", "AMANUENSE_WORKSPACE",
                 "AMANUENSE_AI_KEY", "AMANUENSE_CONFLUENCE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    from amanuense import settings
    monkeypatch.setattr(settings, "_BOOT", None)
    return cfg


def _client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, base_url=LOCAL)


@pytest.fixture
def full(tmp_path):
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    api.install(app, _ready(tmp_path))
    return app, _client(app)


@pytest.fixture
def reduced():
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    api.install_settings(app)
    return app, _client(app)


def _token(client):
    return client.get(f"{BASE}/session", headers=SAME).json()["token"]


def _post(client, path, body=None, token=None):
    headers = {HEADER: token} if token else {}
    return client.post(f"{BASE}{path}", json=body or {}, headers=headers)


def _row(listing, key):
    return next(f for f in listing["fields"] if f["key"] == key)


def _file(cfg):
    return cfg / "settings.json"


# ── GET ────────────────────────────────────────────────────────────────────────

def test_get_lists_the_fields_without_a_token(full, isolated):
    got = full[1].get(f"{BASE}/settings")
    body = got.json()
    assert got.status_code == 200
    assert body["config_file"] == str(_file(isolated)) and len(body["revision"]) == 64
    assert _row(body, "workspace")["source"] == "default"


# ── POST /settings ─────────────────────────────────────────────────────────────

def test_post_without_a_token_is_refused_and_writes_nothing(full, isolated):
    got = _post(full[1], "/settings", {"values": {"ai_model": "m"}})
    assert got.status_code == 403 and not _file(isolated).exists()


def test_post_with_a_token_saves_and_answers_the_listing_with_warnings(full, isolated):
    client = full[1]
    got = _post(client, "/settings", {"values": {"ai_model": "llama", "workspace": MISSING}}, _token(client))
    body = got.json()
    assert got.status_code == 200
    assert json.loads(_file(isolated).read_text(encoding="utf-8"))["ai_model"] == "llama"
    assert _row(body, "ai_model")["value"] == "llama" and _row(body, "ai_model")["source"] == "settings.json"
    assert "workspace" in body["warnings"] and body["revision"] == client.get(f"{BASE}/settings").json()["revision"]


def test_a_restart_row_reports_pending_restart_after_saving(full):
    from amanuense import settings
    client = full[1]
    settings.boot_snapshot()
    body = _post(client, "/settings", {"values": {"notebook_model": "qwen", "ai_model": "m"}}, _token(client)).json()
    assert _row(body, "notebook_model")["pending_restart"] is True and _row(body, "ai_model")["pending_restart"] is False


def test_invalid_values_answer_400_with_every_field_and_save_nothing(full, isolated, monkeypatch):
    monkeypatch.setenv("AMANUENSE_AI_URL", "http://env.example")
    monkeypatch.setenv("AMANUENSE_CONFLUENCE_ROOT", "123")
    client = full[1]
    got = _post(client, "/settings", {"values": {"ai_url": "http://x.example", "mind_root_page": "9", "user": "Ana",
                                                  "mind_url": "not a url"}}, _token(client))
    fields = got.json()["fields"]
    assert got.status_code == 400 and got.json()["error"]
    assert "AMANUENSE_CONFLUENCE_ROOT" in fields["mind_root_page"] and "AMANUENSE_AI_URL" in fields["ai_url"]
    assert "mind_url" in fields and not _file(isolated).exists()


def test_a_stale_revision_answers_409_with_the_current_one_and_a_retry_works(full):
    client = full[1]
    token = _token(client)
    first = client.get(f"{BASE}/settings").json()["revision"]
    _post(client, "/settings", {"values": {"ai_model": "a"}}, token)
    stale = _post(client, "/settings", {"values": {"ai_model": "b"}, "revision": first}, token)
    current = client.get(f"{BASE}/settings").json()["revision"]
    assert stale.status_code == 409 and stale.json()["revision"] == current and stale.json()["error"]
    assert _post(client, "/settings", {"values": {"ai_model": "b"}, "revision": current}, token).status_code == 200


def test_a_body_without_values_object_is_a_bad_request(full, isolated):
    client = full[1]
    token = _token(client)
    for body in ({"values": "x"}, {"values": ["a"]}, {"values": {}, "revision": 5}):
        assert _post(client, "/settings", body, token).status_code == 400
    assert not _file(isolated).exists()


def test_post_is_refused_while_a_job_runs_but_get_is_not(full, isolated, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    app, client = full
    try:
        app.state.amanuense.job.start("run", lambda: docs_kit.run_workspace(None))
        token = _token(client)
        assert _post(client, "/settings", {"values": {"ai_model": "m"}}, token).status_code == 423
        assert _post(client, "/settings/forget", {}, token).status_code == 423
        assert client.get(f"{BASE}/settings").status_code == 200
        assert not _file(isolated).exists()
    finally:
        gate.set()


# ── forget ─────────────────────────────────────────────────────────────────────

def _store_secrets(client, token):
    _post(client, "/settings", {"values": {"ai_key": "sk-secret-1", "mind_token": "pat-secret-2"}}, token)


def test_forget_with_fields_removes_only_those(full):
    client = full[1]
    token = _token(client)
    _store_secrets(client, token)
    body = _post(client, "/settings/forget", {"fields": ["ai_key"]}, token).json()
    assert _row(body, "ai_key")["set"] is False and _row(body, "mind_token")["set"] is True


def test_forget_with_an_empty_body_removes_every_secret(full):
    client = full[1]
    token = _token(client)
    _store_secrets(client, token)
    body = _post(client, "/settings/forget", {}, token).json()
    assert _row(body, "ai_key")["set"] is False and _row(body, "mind_token")["set"] is False


def test_forget_an_empty_list_removes_nothing_and_a_non_secret_is_a_400(full):
    client = full[1]
    token = _token(client)
    _store_secrets(client, token)
    body = _post(client, "/settings/forget", {"fields": []}, token).json()
    assert _row(body, "ai_key")["set"] is True and _row(body, "mind_token")["set"] is True
    bad = _post(client, "/settings/forget", {"fields": ["ai_model"]}, token)
    assert bad.status_code == 400 and "ai_model" in bad.json()["fields"]
    assert _post(client, "/settings/forget", {"fields": "ai_key"}, token).status_code == 400


def test_forget_without_a_token_is_refused_and_keeps_the_file(full, isolated):
    client = full[1]
    _store_secrets(client, _token(client))
    before = _file(isolated).read_bytes()
    assert _post(client, "/settings/forget", {}).status_code == 403
    assert _file(isolated).read_bytes() == before


# ── test ───────────────────────────────────────────────────────────────────────

def test_settings_test_answers_the_mind_user_and_runs_while_a_job_runs(full, monkeypatch):
    from amanuense import settings

    class FakeMind:
        def me(self):
            return "ana"
    monkeypatch.setattr(settings, "mind_client", lambda: FakeMind())
    app, client = full
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace", lambda *a, **k: gate.wait(5))
    try:
        app.state.amanuense.job.start("run", lambda: docs_kit.run_workspace(None))
        got = _post(client, "/settings/test", {}, _token(client))
        assert got.status_code == 200 and got.json() == {"user": "ana"}
    finally:
        gate.set()


def test_settings_test_without_mind_configured_is_a_400_and_without_a_token_a_403(full):
    client = full[1]
    assert _post(client, "/settings/test", {}, _token(client)).status_code == 400
    assert _post(client, "/settings/test", {}).status_code == 403


# ── secrets never leak ─────────────────────────────────────────────────────────

def test_no_secret_appears_in_a_response_or_a_log(full, caplog):
    client = full[1]
    token = _token(client)
    caplog.set_level(logging.DEBUG)
    seen = [_post(client, "/settings", {"values": {"ai_key": "sk-secret-1", "mind_token": "pat-secret-2"}}, token),
            client.get(f"{BASE}/settings"),
            _post(client, "/settings", {"values": {"ai_key": "sk-secret-1", "mind_url": "bad"}}, token)]
    text = " ".join(r.text for r in seen) + caplog.text
    assert "sk-secret-1" not in text and "pat-secret-2" not in text


# ── notes hook and registry ────────────────────────────────────────────────────

def test_the_notes_hook_output_appears_in_the_rows(tmp_path):
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    api.install(app, _ready(tmp_path), settings_notes=lambda: {"vault_path": ["config.yaml wins"]})
    assert _row(_client(app).get(f"{BASE}/settings").json(), "vault_path")["notes"] == ["config.yaml wins"]


def test_the_settings_posts_are_in_the_mutating_registry_with_their_gates():
    from amanuense import api
    assert api.MUTATING["/settings"] is True and api.MUTATING["/settings/forget"] is True
    assert api.MUTATING["/settings/test"] is False


# ── reduced mode ───────────────────────────────────────────────────────────────

def test_reduced_install_registers_only_session_and_the_settings_routes(reduced):
    app, client = reduced
    # The OpenAPI schema, not app.routes: FastAPI 0.150 nests included routers in app.routes.
    paths = {(path, method.upper()) for path, ops in app.openapi()["paths"].items() if path.startswith(BASE)
             for method in ops}
    assert paths == {(f"{BASE}/session", "GET"), (f"{BASE}/settings", "GET"), (f"{BASE}/settings", "POST"),
                     (f"{BASE}/settings/test", "POST"), (f"{BASE}/settings/forget", "POST")}
    assert getattr(app.state, "amanuense", None) is None
    for path in ("/state", "/page", "/job"):
        assert client.get(f"{BASE}{path}").status_code == 404
    assert client.post(f"{BASE}/preview", json={}).status_code == 404


def test_reduced_mode_saves_with_the_session_token_and_lets_the_workspace_be_fixed(reduced, isolated, tmp_path):
    client = reduced[1]
    assert client.get(f"{BASE}/settings").status_code == 200
    assert _post(client, "/settings", {"values": {"workspace": str(tmp_path)}}).status_code == 403
    got = _post(client, "/settings", {"values": {"workspace": str(tmp_path)}}, _token(client))
    assert got.status_code == 200 and json.loads(_file(isolated).read_text(encoding="utf-8"))["workspace"] == str(tmp_path)


def test_reduced_mode_rejects_a_foreign_host(reduced):
    from fastapi.testclient import TestClient
    evil = TestClient(reduced[0], base_url="http://evil.example")
    assert evil.get(f"{BASE}/session", headers=SAME).status_code == 403
    assert evil.post(f"{BASE}/settings", json={}, headers={HEADER: _token(reduced[1])}).status_code == 403


def test_reduced_mode_notes_hook_works(isolated):
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    api.install_settings(app, settings_notes=lambda: {"ollama_api_base": ["n"]})
    assert _row(_client(app).get(f"{BASE}/settings").json(), "ollama_api_base")["notes"] == ["n"]


def test_install_and_install_settings_exclude_each_other_and_neither_repeats(tmp_path):
    from fastapi import FastAPI
    from amanuense import api
    folder = _ready(tmp_path)
    for first, second in ((lambda a: api.install(a, folder), api.install_settings),
                          (api.install_settings, lambda a: api.install(a, folder)),
                          (api.install_settings, api.install_settings)):
        app = FastAPI()
        first(app)
        with pytest.raises(RuntimeError):
            second(app)


# ── The environment view the host gives the settings routes ─────────────────────

def _view_app(tmp_path, env, reduced=False):
    from fastapi import FastAPI
    from amanuense import api
    app = FastAPI()
    if reduced:
        api.install_settings(app, env=env)
    else:
        api.install(app, _ready(tmp_path), env=env)
    return app, _client(app)


def test_default_environment_is_os_environ(full, monkeypatch):
    monkeypatch.setenv("AMANUENSE_AI_URL", "http://real.example")
    _app, client = full
    row = _row(client.get(f"{BASE}/settings").json(), "ai_url")
    assert (row["source"], row["editable"]) == ("environment", False)


@pytest.mark.parametrize("reduced", [False, True])
def test_mapping_view_replaces_os_environ(tmp_path, monkeypatch, reduced):
    monkeypatch.setenv("AMANUENSE_AI_URL", "http://real.example")
    _app, client = _view_app(tmp_path, {}, reduced)
    row = _row(client.get(f"{BASE}/settings").json(), "ai_url")
    assert (row["source"], row["editable"]) == ("default", True)
    token = _token(client)
    done = _post(client, "/settings", {"values": {"ai_url": "http://saved.example"}}, token)
    assert done.status_code == 200  # os.environ would have refused: set by environment variable


def test_view_names_lock_the_field_and_save_is_refused(tmp_path):
    _app, client = _view_app(tmp_path, {"AMANUENSE_AI_URL": "http://view.example"})
    row = _row(client.get(f"{BASE}/settings").json(), "ai_url")
    assert (row["source"], row["value"], row["editable"]) == ("environment", "http://view.example", False)
    refused = _post(client, "/settings", {"values": {"ai_url": "http://x.example"}}, _token(client))
    assert refused.status_code == 400 and "ai_url" in refused.json()["fields"]


def test_callable_view_is_read_on_every_request(tmp_path):
    env = {}
    _app, client = _view_app(tmp_path, lambda: env)
    assert _row(client.get(f"{BASE}/settings").json(), "ai_url")["editable"] is True
    env["AMANUENSE_AI_URL"] = "http://late.example"
    assert _row(client.get(f"{BASE}/settings").json(), "ai_url")["source"] == "environment"


def test_pending_restart_compares_against_the_view(tmp_path):
    from amanuense import settings
    env = {}
    _app, client = _view_app(tmp_path, env)
    settings.boot_snapshot(env)
    _post(client, "/settings", {"values": {"lang": "es"}}, _token(client))
    assert _row(client.get(f"{BASE}/settings").json(), "lang")["pending_restart"] is True
