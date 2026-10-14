"""app: the local review server — only this browser tab can drive it."""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amanuense import app  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import NEW, UPDATE, _ready  # noqa: E402


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    for k in ("AMANUENSE_CONFLUENCE_URL", "AMANUENSE_CONFLUENCE_TOKEN", "AMANUENSE_AI_CLI", "AMANUENSE_AI_URL"):
        monkeypatch.delenv(k, raising=False)
    ws = _ready(tmp_path, "# Convenciones de nomenclatura\n\n> CONFLICTO: el repo dice dev\n\nResto.\n")
    server = app.serve(ws, port=0)
    yield ws, server
    server.shutdown()
    server.server_close()


def _call(server, method, path, body=None, token=True, headers=None):
    host, port = server.server_address[:2]
    h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    if token:
        h["X-Amanuense-Token"] = server.token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read()) if r.headers.get_content_type() == "application/json" else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_the_page_is_served_with_a_strict_policy(served):
    _, server = served
    host, port = server.server_address[:2]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
        csp = r.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert b"<script src=\"app.js\"" in r.read()


def test_api_needs_the_session_token_the_right_host_and_no_foreign_origin(served):
    _, server = served
    assert _call(server, "GET", "/api/state", token=False)[0] == 403
    assert _call(server, "GET", "/api/state", headers={"Host": "evil.example:80"})[0] == 403
    assert _call(server, "POST", "/api/approve", {"rel": UPDATE}, headers={"Origin": "https://evil.example"})[0] == 403
    assert _call(server, "GET", "/api/state")[0] == 200


def test_state_lists_pages_and_never_the_token(served, tmp_path):
    from amanuense import settings
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": "pat-secret-1"})
    _, server = served
    code, state = _call(server, "GET", "/api/state")
    assert code == 200 and state["user"] == "Alex" and state["lang"] == "es"
    assert {p["title"] for p in state["proposals"]} == {"Convenciones de nomenclatura", "Capacidad de mapas"}
    assert state["settings"]["has_token"] and "pat-secret-1" not in json.dumps(state)
    assert state["texts"]["ui_run"] == "Buscar cambios"


def test_page_detail_has_the_diff_and_both_texts(served):
    _, server = served
    code, page = _call(server, "GET", f"/api/page?rel={UPDATE}")
    assert code == 200 and "Resto." in page["result"] and page["before"]
    kinds = {row["op"] for row in page["diff"]}
    assert "insert" in kinds or "replace" in kinds
    assert "<blockquote>" in page["preview"]


def test_review_walk_conflict_edit_approve_publish_by_hand(served):
    ws, server = served
    assert _call(server, "POST", "/api/approve", {"rel": UPDATE})[0] == 409  # the conflict is open
    code, page = _call(server, "POST", "/api/resolve", {"rel": UPDATE, "notice": "CONFLICTO: el repo dice dev",
                                                         "decision": "Apariencia es básica."})
    assert code == 200 and page["proposal"]["conflicts"] == 0
    assert _call(server, "POST", "/api/approve", {"rel": UPDATE})[1]["proposal"]["status"] == "aprobada"
    code, page = _call(server, "POST", "/api/mark-published", {"rel": UPDATE, "url": "https://mind/x"})
    assert page["proposal"]["status"] == "publicada" and page["proposal"]["published"]["by"] == "Alex"


def test_preview_escapes_html(served):
    _, server = served
    code, out = _call(server, "POST", "/api/preview", {"markdown": "<script>alert(1)</script>"})
    assert code == 200 and "<script>" not in out["html"]


def test_big_requests_are_refused(served):
    _, server = served
    code, _ = _call(server, "POST", "/api/preview", {"markdown": "x" * (app.MAX_BODY + 10)})
    assert code == 413


def test_jobs_run_in_the_background_and_block_edits_meanwhile(served, monkeypatch):
    ws, server = served
    gate = {"go": False}

    def slow(root, *a, **k):
        while not gate["go"]:
            time.sleep(0.01)
        return {"ready": [], "tasks": [], "log_errors": []}

    monkeypatch.setattr(docs_kit, "run_workspace", slow)
    assert _call(server, "POST", "/api/job", {"name": "run"})[0] == 200
    assert _call(server, "POST", "/api/approve", {"rel": NEW})[0] == 423
    gate["go"] = True
    for _ in range(200):
        if not _call(server, "GET", "/api/job")[1]["running"]:
            break
        time.sleep(0.02)
    assert _call(server, "GET", "/api/job")[1]["error"] == ""
    assert _call(server, "POST", "/api/approve", {"rel": NEW})[0] == 200


def test_publish_without_a_token_says_how_to_configure_it(served):
    _, server = served
    code, out = _call(server, "POST", "/api/preflight", {"rel": UPDATE})
    assert code == 400 and out["error"]


def test_shutdown_stops_the_server(served):
    _, server = served
    assert _call(server, "POST", "/api/shutdown", {})[0] == 200


def test_every_text_the_page_uses_exists_in_both_languages():
    import re
    from amanuense import i18n
    js = (app.WEB / "app.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'"((?:ui|status|origin)_[a-z_0-9]+)"', js))
    dynamic = {f"{p}_{s}" for p, values in {"status": ("pendiente", "aprobada", "publicada", "descartada"),
                                            "ui_filter": ("todo", "pendiente", "conflicto", "aprobada", "publicada",
                                                          "descartada"),
                                            "ui_cat": ("ruido", "dudosa", "actualizar", "encadenar"),
                                            "ui_job": ("run", "radiator", "deliver", "rework")}.items()
               for s in values}
    missing = sorted(k for k in keys | dynamic if set(i18n.TEXT.get(k, {})) != {"en", "es"})
    assert missing == []
