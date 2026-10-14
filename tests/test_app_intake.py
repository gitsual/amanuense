"""app: documentation dropped into the review app — upload, compare with Confluence, review."""
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "demo"))

import fakes  # noqa: E402
from amanuense import app, intake, settings  # noqa: E402

PAGES = [
    ("Fare Engine overview", "<p>Computes the fare of a journey from zones and passenger type.</p>"),
    ("Service Alerts overview", "<p>Alerts reach the boards within 2 minutes.</p>"
                                '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">SA-1</ac:parameter>'
                                "</ac:structured-macro>"),
    ("Departures Board deployment", "<p>The service listens on port 8080.</p>"),
]


def _world():
    def answer(prompt):
        title = prompt.splitlines()[0].split('"')[1]
        return f"# {title}\n\nUpdated from the uploaded material.\n\n## Change log\n\n- Updated.\n"
    return {"confluence": [(t, [(1, "2026-10-01T09:00:00Z", "Dana Reyes", "")], s) for t, s in PAGES],
            "results": {}, "fallback": answer, "editor": "Dana Reyes", "now": "2026-10-14T09:00:00Z",
            "registry": {}, "route": {}, "triage": {}}


def _env(monkeypatch, tmp_path, base=None):
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    for k in settings.ENV.values():
        monkeypatch.delenv(k, raising=False)
    if base:
        monkeypatch.setenv("AMANUENSE_CONFLUENCE_URL", base)
        monkeypatch.setenv("AMANUENSE_CONFLUENCE_TOKEN", fakes.TOKEN)
        monkeypatch.setenv("AMANUENSE_CONFLUENCE_SPACE", fakes.SPACE)
        monkeypatch.setenv("AMANUENSE_AI_URL", base + "/v1")
        monkeypatch.setenv("AMANUENSE_AI_MODEL", fakes.MODEL)


@pytest.fixture
def stage(tmp_path, monkeypatch):
    world = fakes.start(_world())
    _env(monkeypatch, tmp_path, world.base)
    server = app.serve(tmp_path / "ws", port=0, lang="en")
    yield tmp_path / "ws", server
    server.shutdown()
    server.server_close()
    world.shutdown()


@pytest.fixture
def bare(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    server = app.serve(tmp_path / "ws", port=0, lang="en")
    yield tmp_path / "ws", server
    server.shutdown()
    server.server_close()


def _call(server, method, path, body=None, raw=None, token=True, headers=None):
    port = server.server_address[1]
    h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    if token:
        h["X-Amanuense-Token"] = server.token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
        h.setdefault("Content-Type", "application/octet-stream")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _upload(server, batch, path, data: bytes, **headers):
    q = urllib.parse.urlencode({"batch": batch, "path": path})
    return _call(server, "POST", f"/api/intake/file?{q}", raw=data,
                 headers={"X-Content-SHA256": hashlib.sha256(data).hexdigest(), **headers})


def _wait(server, seconds=30):
    for _ in range(int(seconds / 0.05)):
        job = _call(server, "GET", "/api/job")[1]
        if not job["running"]:
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


# ── Protection of the upload ────────────────────────────────────────────────────

def test_uploading_needs_the_token_the_host_and_no_foreign_origin(bare):
    ws, server = bare
    batch = _call(server, "POST", "/api/intake/start", {})[1]["batch"]
    q = urllib.parse.urlencode({"batch": batch, "path": "a.md"})
    assert _call(server, "POST", f"/api/intake/file?{q}", raw=b"# A\n", token=False)[0] == 403
    assert _call(server, "POST", f"/api/intake/file?{q}", raw=b"# A\n", headers={"Origin": "https://evil.example"})[0] == 403
    assert _call(server, "POST", f"/api/intake/file?{q}", raw=b"# A\n", headers={"Host": "evil.example"})[0] == 403
    assert _call(server, "POST", f"/api/intake/file?{q}", raw=b"# A\n", headers={"Content-Type": "text/plain"})[0] == 415
    assert not any((ws / "2-my-docs" / batch).iterdir())


def test_uploads_are_sanitised_and_limited(bare, monkeypatch):
    ws, server = bare
    batch = _call(server, "POST", "/api/intake/start", {})[1]["batch"]
    assert batch.startswith("intake-")
    code, out = _upload(server, batch, "C:\\pile\\sub\\Notes.md", b"# Notes\n")
    assert code == 200 and out["stored"] == f"{batch}/pile/sub/Notes.md"
    assert (ws / "2-my-docs" / batch / "pile" / "sub" / "Notes.md").read_bytes() == b"# Notes\n"
    assert _upload(server, batch, "../../evil.md", b"x")[0] == 400
    assert _upload(server, batch, "tool.exe", b"MZ")[0] == 400
    assert _upload(server, "../..", "a.md", b"x")[0] == 400
    code, out = _upload(server, batch, "bad.md", b"x", **{"X-Content-SHA256": "0" * 64})
    assert code == 400 and "damaged" in out["error"]
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 10)
    code, out = _upload(server, batch, "big.md", b"x" * 50)
    assert code == 413 and out["error"]
    assert _call(server, "GET", "/api/state")[0] == 200  # the server still answers after refusing a body
    assert sorted(p.name for p in (ws / "2-my-docs" / batch).rglob("*") if p.is_file()) == ["Notes.md"]


def test_the_plan_is_answered_before_anything_is_uploaded(bare):
    _, server = bare
    files = [{"path": "p/a.md", "size": 3, "sha256": "a" * 64}, {"path": "p/a copy.md", "size": 3, "sha256": "a" * 64},
             {"path": "p/x.pdf", "size": 3, "sha256": "b" * 64}]
    code, plan = _call(server, "POST", "/api/intake/plan", {"files": files})
    assert code == 200 and [i["reason"] for i in plan["items"]] == ["", "duplicate", "pdf"]
    state = _call(server, "GET", "/api/state")[1]
    assert state["limits"]["max_file"] == intake.MAX_FILE_BYTES and ".docx" in state["formats"]
    assert state["planned_source"]["kind"] == "none"


def test_a_cancelled_upload_leaves_nothing_behind(bare):
    ws, server = bare
    batch = _call(server, "POST", "/api/intake/start", {})[1]["batch"]
    _upload(server, batch, "a.md", b"# A\n")
    assert _call(server, "POST", "/api/intake/cancel", {"batch": batch})[0] == 200
    assert not (ws / "2-my-docs" / batch).exists()
    (ws / "2-my-docs" / "intake-20200101-000000").mkdir()
    assert _call(server, "POST", "/api/intake/cancel", {"batch": "intake-20200101-000000"})[0] == 400  # not ours


def test_uploads_wait_while_a_job_runs(bare, monkeypatch):
    from amanuense import taller as docs_kit
    ws, server = bare
    batch = _call(server, "POST", "/api/intake/start", {})[1]["batch"]
    gate = {"go": False}

    def slow(root, *a, **k):
        while not gate["go"]:
            time.sleep(0.01)
        return {"ready": [], "tasks": [], "log_errors": []}
    monkeypatch.setattr(docs_kit, "run_workspace", slow)
    assert _call(server, "POST", "/api/job", {"name": "run"})[0] == 200
    assert _upload(server, batch, "a.md", b"# A\n")[0] == 423
    gate["go"] = True
    _wait(server)


# ── End to end ──────────────────────────────────────────────────────────────────

def test_a_dropped_pile_ends_as_proposals_against_live_confluence(stage):
    ws, server = stage
    pile = {
        "pile/Fare Engine overview.md": b"# Fare Engine overview\n\nThe off-peak discount is 20%.\n",
        "pile/old/fare-engine-overview-final.md": b"# Fare Engine overview\n\nZones 1 to 4.\n",
        "pile/alerts.md": b"# Service Alerts overview\n\nAlerts reach the boards within 2 minutes.\n",
        "pile/alerts (2).md": b"# Service Alerts overview\n\nAlerts reach the boards within 2 minutes.\n",
        "pile/night-service.txt": b"# Night Service\n\nNight trams run from 00:30 to 05:00 on lines 1 and 4.\n",
        "pile/test-results.txt": b"3 failed",
        "pile/scan.pdf": b"%PDF-1.4",
    }
    files = [{"path": p, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for p, d in pile.items()]
    plan = _call(server, "POST", "/api/intake/plan", {"files": files})[1]
    use = [i["path"] for i in plan["items"] if i["status"] == "use"]
    assert sorted(use) == ["pile/Fare Engine overview.md", "pile/alerts.md", "pile/night-service.txt",
                           "pile/old/fare-engine-overview-final.md"]
    assert _call(server, "GET", "/api/state")[1]["planned_source"]["kind"] == "live"
    batch = _call(server, "POST", "/api/intake/start", {})[1]["batch"]
    for path in use:
        assert _upload(server, batch, path, pile[path])[0] == 200
    assert _call(server, "POST", "/api/job", {"name": "intake", "batch": batch})[0] == 200
    job = _wait(server)
    assert job["error"] == "" and job["result"]["source"]["kind"] == "live"
    assert job["result"]["batch"]["updates"] == 1 and job["result"]["batch"]["identical"] == 1
    assert job["result"]["batch"]["unmatched"] == 1
    state = _call(server, "GET", "/api/state")[1]
    assert [p["title"] for p in state["proposals"]] == ["Fare Engine overview"]
    assert state["source"]["kind"] == "live" and state["source"]["count"] == 3
    assert state["intake"]["unmatched"][0]["title"] == "Night Service"
    page = _call(server, "GET", f"/api/page?rel={urllib.parse.quote(state['proposals'][0]['rel'])}")[1]
    assert "Computes the fare" in page["before"] and "Updated from the uploaded material." in page["result"]
    # choosing the candidate makes it a new page on the next comparison
    rel = state["intake"]["unmatched"][0]["rel"]
    assert _call(server, "POST", "/api/intake/promote", {"rel": rel})[0] == 200
    _call(server, "POST", "/api/job", {"name": "intake", "batch": batch})
    assert _wait(server)["error"] == ""
    titles = {p["title"]: p for p in _call(server, "GET", "/api/state")[1]["proposals"]}
    assert set(titles) == {"Fare Engine overview", "Night Service"} and titles["Night Service"]["new"]
    # the cached snapshot carries the space, never the token
    cached = (ws / "output" / "confluence-live.json").read_text(encoding="utf-8")
    assert fakes.TOKEN not in cached and "⟦Confluence macro: jira (key=SA-1)⟧" in cached
