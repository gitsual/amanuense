"""api: background jobs, artifacts and vault generation for a host that mounts the router."""
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from amanuense import i18n, revision, service  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import _ready  # noqa: E402

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"
SANDBOX = "sandbox; default-src 'none'; style-src 'unsafe-inline'"


def _build(tmp_path, monkeypatch, **options):
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
    api.install(app, folder, **options)
    client = TestClient(app, base_url=LOCAL)
    token = client.get(f"{BASE}/session").json()["token"]
    return app, folder, client, {HEADER: token}


@pytest.fixture
def host(tmp_path, monkeypatch):
    return _build(tmp_path, monkeypatch)


@pytest.fixture
def blocking(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


def _finished(client, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        snap = client.get(f"{BASE}/job").json()
        if not snap["running"]:
            return snap
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


# ── The version and the registry ───────────────────────────────────────────────

def test_the_api_version_is_three_and_the_new_routes_are_in_the_registry():
    pytest.importorskip("fastapi")
    from amanuense import api
    assert api.API_VERSION == 3
    assert "/vault" in api.MUTATING and "/job" in api.MUTATING
    paths = {route.path for route in api.router.routes}
    assert f"{BASE}/artifact/{{what}}" in paths and f"{BASE}/vault" in paths


def test_vault_needs_the_token_and_waits_for_a_running_job(host, blocking):
    app, _f, client, h = host
    assert client.post(f"{BASE}/vault", json={"confirm": True}).status_code == 403
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers={HEADER: "wrong"}).status_code == 403
    app.state.amanuense.start_job("run", {})
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 423


# ── POST /job ──────────────────────────────────────────────────────────────────

def test_run_starts_a_comparison_and_its_result_shows_in_the_job(host, monkeypatch):
    _a, _f, client, h = host
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: {"ready": ["a", "b"], "tasks": [], "log_errors": ["careful"]})
    started = client.post(f"{BASE}/job", json={"name": "run"}, headers=h)
    assert started.status_code == 200 and started.json()["name"] == "run"
    done = _finished(client)
    assert done["error"] == "" and done["result"]["ready"] == 2 and done["result"]["warnings"] == ["careful"]


def test_a_failing_job_shows_its_error_in_the_job(host, monkeypatch):
    _a, _f, client, h = host

    def boom(*_a, **_k):
        raise RuntimeError("the export is unreadable")
    monkeypatch.setattr(docs_kit, "run_workspace", boom)
    assert client.post(f"{BASE}/job", json={"name": "run"}, headers=h).status_code == 200
    done = _finished(client)
    assert done["result"] is None and "unreadable" in done["error"]


def test_intake_job_compares_a_batch_and_refuses_an_unknown_one(host, monkeypatch):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/job", json={"name": "intake"}, headers=h).status_code == 400  # no batch
    assert client.post(f"{BASE}/job", json={"name": "intake", "batch": "nope"}, headers=h).status_code == 400
    batch = client.post(f"{BASE}/intake/start", json={}, headers=h).json()["batch"]
    seen = {}

    def fake(root, *a, **k):
        seen["sync"] = k.get("sync_repos")
        return {"ready": [], "tasks": [], "log_errors": []}
    monkeypatch.setattr(docs_kit, "run_workspace", fake)
    assert client.post(f"{BASE}/job", json={"name": "intake", "batch": batch}, headers=h).status_code == 200
    done = _finished(client)
    assert done["result"]["batch_name"] == batch and seen["sync"] is False


def test_radiator_and_deliver_run_the_kit_and_report_where(host, monkeypatch):
    _a, folder, client, h = host
    calls = []
    monkeypatch.setattr(docs_kit, "radiator_workspace", lambda root, *a, **k: calls.append(("radiator", root)) or root / "r.html")
    monkeypatch.setattr(docs_kit, "deliver_workspace",
                        lambda root, make_zip=False, **k: calls.append(("deliver", make_zip)) or root / "d")
    assert client.post(f"{BASE}/job", json={"name": "radiator"}, headers=h).status_code == 200
    assert _finished(client)["result"] == str(folder.resolve() / "r.html")
    assert client.post(f"{BASE}/job", json={"name": "deliver"}, headers=h).status_code == 200
    assert _finished(client)["result"] == str(folder.resolve() / "d")
    assert calls == [("radiator", folder.resolve()), ("deliver", True)]


def test_rework_needs_rel_and_instruction_and_runs_the_engine(host, monkeypatch):
    _a, folder, client, h = host
    monkeypatch.setattr(service, "_ai", lambda: object())
    assert client.post(f"{BASE}/job", json={"name": "rework"}, headers=h).status_code == 400
    assert client.post(f"{BASE}/job", json={"name": "rework", "rel": "x"}, headers=h).status_code == 400
    assert client.post(f"{BASE}/job", json={"name": "rework", "instruction": "shorter"}, headers=h).status_code == 400
    assert client.post(f"{BASE}/job", json={"name": "rework", "rel": "../x", "instruction": "y"},
                       headers=h).status_code == 400
    assert client.get(f"{BASE}/job").json()["running"] is False  # none of them started a job
    seen = []
    monkeypatch.setattr(revision, "rework", lambda root, rel, text, model, by: seen.append((rel, text)) or {"title": "T"})
    rel = revision.proposals(folder)[0]["rel"]
    assert client.post(f"{BASE}/job", json={"name": "rework", "rel": rel, "instruction": "shorter"},
                       headers=h).status_code == 200
    assert _finished(client)["result"] == "T" and seen == [(rel, "shorter")]


def test_an_unknown_job_is_a_400_and_a_second_one_while_running_is_a_423(host, blocking):
    _a, _f, client, h = host
    for body in ({"name": "rm -rf"}, {}, {"name": 3}):
        assert client.post(f"{BASE}/job", json=body, headers=h).status_code == 400
    assert client.post(f"{BASE}/job", json={"name": "vault"}, headers=h).status_code == 400  # not in the public list
    assert client.post(f"{BASE}/job", json={"name": "run"}, headers=h).status_code == 200
    assert client.post(f"{BASE}/job", json={"name": "run"}, headers=h).status_code == 423


def test_a_read_route_answers_quickly_while_a_job_blocks(host, blocking):
    app, _f, client, h = host
    app.state.amanuense.start_job("run", {})
    for path in ("/job", "/settings", "/session"):
        began = time.monotonic()
        assert client.get(f"{BASE}{path}").status_code == 200
        assert time.monotonic() - began < 1.0


# ── GET /artifact/{what} ───────────────────────────────────────────────────────

def _make(folder, what):
    out = folder / i18n.name("out")
    if what == "log":
        path = out / i18n.name("log_html")
    elif what == "radiator":
        path = out / "radiador" / "index.html"
    else:
        path = out / f'{i18n.name("delivery")}-2026-10-19.zip'
        (out / path.stem).mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"<h1>hi</h1>" if what != "delivery" else b"PK\x03\x04zip")
    return path


@pytest.mark.parametrize("what", ["radiator", "log"])
def test_html_artifacts_are_served_sandboxed(host, what):
    _a, folder, client, _h = host
    _make(folder, what)
    got = client.get(f"{BASE}/artifact/{what}")
    assert got.status_code == 200 and got.content == b"<h1>hi</h1>"
    assert got.headers["content-type"].startswith("text/html")
    assert got.headers["content-security-policy"] == SANDBOX
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"] == "no-store"
    assert "attachment" not in got.headers.get("content-disposition", "")


def test_the_delivery_is_a_zip_attachment(host):
    _a, folder, client, _h = host
    path = _make(folder, "delivery")
    got = client.get(f"{BASE}/artifact/delivery")
    assert got.status_code == 200 and got.content == b"PK\x03\x04zip"
    assert got.headers["content-type"] == "application/zip"
    assert got.headers["content-disposition"].startswith("attachment") and path.name in got.headers["content-disposition"]
    assert got.headers["x-content-type-options"] == "nosniff" and got.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("what", ["radiator", "log", "delivery"])
def test_a_missing_artifact_is_a_404(host, what):
    _a, folder, client, _h = host
    (folder / i18n.name("out") / i18n.name("log_html")).unlink(missing_ok=True)  # the comparison wrote one
    assert client.get(f"{BASE}/artifact/{what}").status_code == 404


def test_the_delivery_folder_without_its_zip_is_a_404(host):
    _a, folder, client, _h = host
    (folder / i18n.name("out") / f'{i18n.name("delivery")}-2026-10-19').mkdir(parents=True)
    assert client.get(f"{BASE}/artifact/delivery").status_code == 404


@pytest.mark.parametrize("what", ["workspace", "output", "..", "%2e%2e%2fstate", "log/..", "/etc/passwd"])
def test_only_the_three_artifacts_exist_and_a_path_escape_is_refused(host, what):
    _a, folder, client, _h = host
    _make(folder, "log")
    got = client.get(f"{BASE}/artifact/{what}")
    assert got.status_code in (400, 404) and "hi" not in got.text


def test_an_artifact_that_is_a_link_out_of_the_workshop_is_refused(host, tmp_path):
    _a, folder, client, _h = host
    secret = tmp_path / "secret.html"
    secret.write_text("TOP SECRET", encoding="utf-8")
    link = folder / i18n.name("out") / i18n.name("log_html")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are not available")
    got = client.get(f"{BASE}/artifact/log")
    assert got.status_code in (400, 404) and "SECRET" not in got.text


def test_an_artifact_needs_no_token_but_a_foreign_host_is_refused(host):
    _a, folder, client, _h = host
    _make(folder, "log")
    assert client.get(f"{BASE}/artifact/log").status_code == 200
    assert client.get(f"{BASE}/artifact/log", headers={"host": "evil.example"}).status_code == 403


def test_target_still_answers_the_legacy_places(host):
    app, folder, _c, _h = host
    ws = app.state.amanuense
    assert ws.target("workspace") == ws.root
    _make(folder, "log")
    assert ws.target("log").name == i18n.name("log_html")
    with pytest.raises(ValueError):
        ws.target("delivery")


# ── POST /vault ────────────────────────────────────────────────────────────────

class Spy:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self):
        self.calls.append(1)
        if self.fail:
            raise self.fail


@pytest.fixture
def vaulted(tmp_path, monkeypatch):
    spy = Spy()
    vault = tmp_path / "deep" / "vault"
    made = []

    def fake(workshop, target, force=False):
        made.append({"workshop": Path(workshop), "vault": Path(target), "force": force, "existed": Path(target).is_dir()})
        return {"notes": 3, "media": 1, "copied": 2, "vault": Path(target), "export": Path(workshop) / "e.docx"}
    from amanuense import obsidian
    monkeypatch.setattr(obsidian, "workshop_to_vault", fake)
    app, folder, client, h = _build(tmp_path, monkeypatch, vault=vault, on_vault_changed=spy)
    return app, folder, client, h, vault, spy, made


@pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": "yes"}, {"confirm": 1}, {"confirm": None}])
def test_the_vault_is_not_touched_without_an_explicit_confirmation(vaulted, body):
    _a, _f, client, h, vault, spy, made = vaulted
    assert client.post(f"{BASE}/vault", json=body, headers=h).status_code == 400
    assert not vault.exists() and not made and not spy.calls
    assert client.get(f"{BASE}/job").json()["name"] == ""


def test_a_missing_vault_folder_is_created_and_the_callback_runs_once(vaulted):
    _a, folder, client, h, vault, spy, made = vaulted
    assert not vault.exists()
    started = client.post(f"{BASE}/vault", json={"confirm": True}, headers=h)
    assert started.status_code == 200 and started.json()["name"] == "vault"
    done = _finished(client)
    assert done["error"] == "" and vault.is_dir()
    assert made == [{"workshop": folder.resolve(), "vault": vault, "force": True, "existed": True}]
    assert done["result"]["notes"] == 3 and done["result"]["vault"] == str(vault)
    assert "reindex_error" not in done["result"] and spy.calls == [1]


def test_the_default_vault_inside_the_workshop_is_generated(vaulted):
    """<workshop>/vault, the settings default and the brick layout, must not be refused as an overlap."""
    app, folder, client, h, _vault, spy, made = vaulted
    app.state.amanuense.vault = folder / "vault"
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 200
    done = _finished(client)
    assert done["error"] == "" and made[0]["vault"] == folder / "vault" and spy.calls == [1]


def test_a_failed_generation_does_not_call_the_callback(vaulted, monkeypatch):
    _a, _f, client, h, vault, spy, _made = vaulted
    from amanuense import obsidian

    def boom(*_a, **_k):
        raise FileNotFoundError("no export")
    monkeypatch.setattr(obsidian, "workshop_to_vault", boom)
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 200
    done = _finished(client)
    assert "no export" in done["error"] and done["result"] is None and spy.calls == []


def test_a_callback_that_raises_still_succeeds_and_says_so(tmp_path, monkeypatch):
    spy = Spy(fail=RuntimeError("index is locked"))
    from amanuense import obsidian
    monkeypatch.setattr(obsidian, "workshop_to_vault", lambda w, v, force=False: {"notes": 1, "vault": Path(v)})
    _a, _f, client, h = _build(tmp_path, monkeypatch, vault=tmp_path / "v", on_vault_changed=spy)
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 200
    done = _finished(client)
    assert done["error"] == "" and done["result"]["notes"] == 1
    assert "index is locked" in done["result"]["reindex_error"] and spy.calls == [1]


def test_without_a_callback_the_vault_is_still_generated(tmp_path, monkeypatch):
    from amanuense import obsidian
    monkeypatch.setattr(obsidian, "workshop_to_vault", lambda w, v, force=False: {"notes": 1, "vault": Path(v)})
    _a, _f, client, h = _build(tmp_path, monkeypatch, vault=tmp_path / "v")
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 200
    assert _finished(client)["result"]["notes"] == 1


def test_no_vault_configured_is_a_400(host):
    _a, _f, client, h = host
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 400
    assert client.get(f"{BASE}/job").json()["name"] == ""



@pytest.mark.parametrize("where", ["equal", "inside", "contains"])
def test_a_vault_overlapping_the_workshop_is_a_400_before_any_job_and_deletes_nothing(tmp_path, monkeypatch, where):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from amanuense import obsidian
    ran = []
    monkeypatch.setattr(obsidian, "workshop_to_vault", lambda *a, **k: ran.append(a))
    folder = _ready(tmp_path, "# Convenciones\n\nTexto.\n")
    from amanuense import i18n
    vault = {"equal": folder, "inside": folder / i18n.name("local") / "vault", "contains": tmp_path}[where]
    spy = Spy()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from amanuense import api
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    app = FastAPI()
    api.install(app, folder, vault=vault, on_vault_changed=spy)
    client = TestClient(app, base_url=LOCAL)
    h = {HEADER: client.get(f"{BASE}/session").json()["token"]}
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 400
    assert client.get(f"{BASE}/job").json()["name"] == ""
    assert not ran and not spy.calls and sorted(p for p in tmp_path.rglob("*") if p.is_file()) == before
    assert not (folder / i18n.name("local") / "vault").exists()


def test_the_real_generator_failing_keeps_the_vault_and_reports_the_error(tmp_path, monkeypatch):
    from amanuense import obsidian
    _a, folder, client, h = _build(tmp_path, monkeypatch, vault=tmp_path / "v")
    export = folder / i18n.name("export")
    export.mkdir(parents=True, exist_ok=True)
    (export / "Broken.docx").write_bytes(b"not a zip")
    old = tmp_path / "v" / "MIND"
    old.mkdir(parents=True)
    (old / "old.md").write_bytes(b"# old\n")
    assert client.post(f"{BASE}/vault", json={"confirm": True}, headers=h).status_code == 200
    done = _finished(client)
    assert done["error"] and done["result"] is None
    assert (old / "old.md").read_bytes() == b"# old\n"
    assert sorted(p.name for p in (tmp_path / "v").iterdir()) == ["MIND"]


def test_a_delivery_zip_that_is_a_link_out_of_the_workshop_is_a_404(host, tmp_path):
    _a, folder, client, _h = host
    secret = tmp_path / "secret.zip"
    secret.write_bytes(b"PK\x03\x04TOP SECRET")
    out = folder / i18n.name("out")
    out.mkdir(parents=True, exist_ok=True)
    link = out / f'{i18n.name("delivery")}-2026-10-19.zip'
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are not available")
    got = client.get(f"{BASE}/artifact/delivery")
    assert got.status_code == 404 and b"SECRET" not in got.content
