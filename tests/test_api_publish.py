"""api: the MIND publish routes (preflight, publish, undo, mark-published) with a fake Confluence."""
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from amanuense import mind, revision, settings, space  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_mind import BASE as MIND_URL  # noqa: E402
from test_mind import TOKEN, FakeMind  # noqa: E402
from test_revision import UPDATE, _ready  # noqa: E402

BASE = "/api/amanuense"
HEADER = "X-Amanuense-Token"
LOCAL = "http://127.0.0.1:8000"
EXPORTED = "2026-10-12T00:00:00Z"
TITLE = "Convenciones de nomenclatura"
ROUTES = ["/preflight", "/publish", "/undo", "/mark-published"]
LINKS_ONLY = ('<ac:layout><ac:layout-section><ac:link><ri:page ri:content-title="X"/></ac:link>'
              '</ac:layout-section></ac:layout>')


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
    fake = FakeMind().page("101", TITLE, storage="<p>Antes.</p>")
    monkeypatch.setattr(settings, "mind_client", lambda: mind.Mind(MIND_URL, TOKEN, "WK", opener=fake))
    monkeypatch.setattr(mind, "export_date", lambda root: EXPORTED)
    folder = _ready(tmp_path)
    app = FastAPI()
    api.install(app, folder)
    client = TestClient(app, base_url=LOCAL)
    token = client.get(f"{BASE}/session").json()["token"]
    return app, folder, client, {HEADER: token}, fake


@pytest.fixture
def blocking(monkeypatch):
    """A comparison that stays running: the fake Mind would answer the fetch at once, so the job waits there."""
    gate = threading.Event()
    monkeypatch.setattr(space, "resolve", lambda *a, **k: gate.wait(5) and space.Source("export", None))
    monkeypatch.setattr(docs_kit, "run_workspace", lambda *a, **k: {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


def _status(client, rel=UPDATE):
    return client.get(f"{BASE}/page", params={"rel": rel}).json()["proposal"]["status"]


def _approve(client, h, rel=UPDATE):
    assert client.post(f"{BASE}/approve", json={"rel": rel}, headers=h).status_code == 200


def _puts(fake):
    return [r for r in fake.requests if r.get_method() == "PUT"]


def test_the_four_routes_are_registered_and_need_the_token(host):
    from amanuense import api
    _app, folder, client, h, fake = host
    _approve(client, h)
    assert set(ROUTES) <= set(api.MUTATING)
    for path in ROUTES:
        got = client.post(f"{BASE}{path}", json={"rel": UPDATE, "url": "https://mind/x"})
        assert got.status_code == 403 and got.json() == {"error": "token"}, path
    assert _status(client) == "aprobada"
    assert fake.requests == []  # nothing reached Confluence


def test_preflight_answers_page_parent_blockers_and_warnings(host):
    _app, _folder, client, h, fake = host
    _approve(client, h)
    got = client.post(f"{BASE}/preflight", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 200
    check = got.json()
    assert {"page", "parent", "blockers", "warnings"} <= set(check)
    assert check["blockers"] == [] and check["warnings"] == [] and check["parent"] is None
    assert check["page"]["id"] == "101" and check["page"]["version"] == 3
    assert _puts(fake) == []  # a preflight only reads


def test_preflight_reports_a_blocker_for_a_page_nobody_approved(host):
    _app, _folder, client, h, _fake = host
    check = client.post(f"{BASE}/preflight", json={"rel": UPDATE}, headers=h).json()
    assert len(check["blockers"]) == 1 and check["page"]["id"] == "101"


def test_publish_with_blockers_is_a_400_and_changes_nothing(host):
    _app, _folder, client, h, fake = host
    got = client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h)  # still pending: not approved
    assert got.status_code == 400 and got.json()["error"]
    assert _status(client) == "pendiente"
    assert _puts(fake) == []


def test_warnings_need_accept_warnings_true(host):
    _app, _folder, client, h, fake = host
    fake.page("101", TITLE, storage=LINKS_ONLY)
    _approve(client, h)
    refused = client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h)
    assert refused.status_code == 400 and refused.json()["error"]
    assert _status(client) == "aprobada" and _puts(fake) == []
    done = client.post(f"{BASE}/publish", json={"rel": UPDATE, "accept_warnings": True}, headers=h)
    assert done.status_code == 200
    assert done.json()["proposal"]["status"] == "publicada" and len(_puts(fake)) == 1


def test_publish_writes_the_page_and_answers_with_the_published_record(host):
    _app, folder, client, h, fake = host
    _approve(client, h)
    got = client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 200
    published = got.json()["proposal"]["published"]
    assert published["mode"] == "api" and published["version"] == 4 and published["by"] == "Alex"
    assert "Las ramas usan PROJ-." in fake.pages["101"]["body"]["storage"]["value"]
    assert (folder / docs_kit.OUT_DIR / mind.BACKUP_DIR / "101-v3.xml").exists()


def test_a_network_failure_is_a_400_with_the_status_unchanged_and_no_record(host):
    _app, folder, client, h, fake = host
    _approve(client, h)
    fake.fail = {"PUT": 500}
    got = client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 400 and got.json()["error"]
    assert TOKEN not in got.text
    proposal = client.get(f"{BASE}/page", params={"rel": UPDATE}).json()["proposal"]
    assert proposal["status"] == "aprobada" and not proposal.get("published")
    assert revision.find(folder, UPDATE).get("published") in (None, {})


def test_an_unreachable_mind_on_preflight_is_a_400_too(host):
    _app, _folder, client, h, fake = host
    _approve(client, h)
    fake.fail = {"GET": 503}
    got = client.post(f"{BASE}/preflight", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 400 and got.json()["error"]


def test_undo_without_a_publish_record_is_a_409(host):
    _app, _folder, client, h, fake = host
    _approve(client, h)
    got = client.post(f"{BASE}/undo", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 409 and got.json()["error"]
    assert _status(client) == "aprobada" and _puts(fake) == []


def test_undo_puts_the_backup_back_after_a_publish(host):
    _app, _folder, client, h, fake = host
    _approve(client, h)
    assert client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h).status_code == 200
    got = client.post(f"{BASE}/undo", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 200 and got.json()["proposal"]["status"] == "aprobada"
    assert fake.pages["101"]["body"]["storage"]["value"] == "<p>Antes.</p>"
    assert fake.pages["101"]["version"]["number"] == 5


def test_mark_published_records_the_url_a_person_published_by_hand(host):
    _app, _folder, client, h, fake = host
    _approve(client, h)
    got = client.post(f"{BASE}/mark-published", json={"rel": UPDATE, "url": "https://mind/x"}, headers=h)
    assert got.status_code == 200
    proposal = got.json()["proposal"]
    assert proposal["status"] == "publicada"
    assert proposal["published"]["url"] == "https://mind/x" and proposal["published"]["mode"] == "manual"
    assert proposal["published"]["by"] == "Alex"
    assert fake.requests == []  # by hand: Confluence is never called


def test_mark_published_without_a_url_is_a_400(host):
    _app, _folder, client, h, _fake = host
    _approve(client, h)
    got = client.post(f"{BASE}/mark-published", json={"rel": UPDATE}, headers=h)
    assert got.status_code == 400
    assert _status(client) == "aprobada"


def test_publishing_waits_while_a_job_runs_but_a_preflight_still_reads(host, blocking):
    app, _folder, client, h, fake = host
    _approve(client, h)
    app.state.amanuense.start_job("run", {})
    for path in ("/publish", "/undo", "/mark-published"):
        got = client.post(f"{BASE}{path}", json={"rel": UPDATE, "url": "https://mind/x"}, headers=h)
        assert got.status_code == 423, path
    assert _status(client) == "aprobada" and _puts(fake) == []
    assert client.post(f"{BASE}/preflight", json={"rel": UPDATE}, headers=h).status_code == 200
    blocking.set()
    for _ in range(200):
        if not client.get(f"{BASE}/job").json()["running"]:
            break
        threading.Event().wait(0.02)
    assert client.post(f"{BASE}/publish", json={"rel": UPDATE}, headers=h).status_code == 200
