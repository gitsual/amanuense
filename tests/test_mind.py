"""mind: publishing a reviewed page to Confluence Data Center without losing anything silently."""
import io
import json
import sys
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amanuense import mind  # noqa: E402
from amanuense import revision  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import NEW, UPDATE, _ready  # noqa: E402

BASE = "https://mind.example.org"
TOKEN = "secret-pat-123"


def _xml(storage: str):
    return ET.fromstring(f'<r xmlns:ac="urn:ac" xmlns:ri="urn:ri">{storage}</r>')


# ── Markdown → storage ──────────────────────────────────────────────────────────

def test_storage_is_well_formed_xhtml_without_the_title():
    md = ("# Alfa\n\nUna línea<br>otra & más.\n\n| a | b |\n|---|---|\n| x<br>y | z |\n\n"
          "```\nif a < b: print(']]>')\n```\n\n![logo](https://x.org/l.png)\n")
    storage = mind.markdown_to_storage(md, "Alfa")
    root = _xml(storage)
    assert root.find("h1") is None
    macro = root.find("{urn:ac}structured-macro")
    assert macro.get("{urn:ac}name") == "code"
    assert macro.find("{urn:ac}plain-text-body").text == "if a < b: print(']]>')"
    assert root.find(".//{urn:ac}image/{urn:ri}url").get("{urn:ri}value") == "https://x.org/l.png"


def test_links_cannot_carry_script_or_break_out_of_the_attribute():
    html = docs_kit.markdown_to_html('[a](javascript:alert(1)) [b](https://x.org/"onmouseover=x) [c](otra.md)\n')
    assert 'href="javascript' not in html and '"onmouseover' not in html
    assert '<a href="otra.md">c</a>' in html
    assert "<script>" not in docs_kit.markdown_to_html("<script>alert(1)</script>\n")


# ── A fake Confluence ───────────────────────────────────────────────────────────

class FakeMind:
    """Answers like Confluence DC's /rest/api/content and records every request."""

    def __init__(self, pages=None, fail=None):
        self.pages = pages or {}
        self.requests = []
        self.fail = fail or {}
        self.next_id = 900

    def page(self, pid, title, version=3, when="2026-10-10T08:00:00.000+02:00", storage="<p>Hoy.</p>",
             space="WK", ancestors=()):
        self.pages[pid] = {"id": pid, "type": "page", "title": title, "space": {"key": space},
                           "version": {"number": version, "when": when, "by": {"displayName": "Ana"}},
                           "body": {"storage": {"value": storage, "representation": "storage"}},
                           "ancestors": [{"id": a} for a in ancestors],
                           "_links": {"webui": f"/pages/viewpage.action?pageId={pid}"}}
        return self

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        code = self.fail.get(method)
        if code:
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b'{"message": "boom"}'))
        path = url.split("/rest/api", 1)[1]
        if method == "GET" and path.startswith("/content?"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)
            hits = [p for p in self.pages.values()
                    if p["title"] == q["title"][0] and p["space"]["key"] == q["spaceKey"][0]]
            return self._answer({"results": hits, "size": len(hits)})
        if method == "GET" and path.startswith("/content/"):
            return self._answer(self.pages[path.split("/")[2].split("?")[0]])
        if method == "GET" and path.startswith("/user/current"):
            return self._answer({"displayName": "Alex"})
        if method == "PUT":
            pid = path.split("/")[2]
            assert body["version"]["number"] == self.pages[pid]["version"]["number"] + 1
            self.page(pid, body["title"], body["version"]["number"], "2026-10-15T09:00:00.000+02:00",
                      body["body"]["storage"]["value"])
            return self._answer(self.pages[pid])
        if method == "POST":
            pid = str(self.next_id)
            self.next_id += 1
            self.page(pid, body["title"], 1, "2026-10-15T09:00:00.000+02:00", body["body"]["storage"]["value"],
                      body["space"]["key"], [a["id"] for a in body["ancestors"]])
            return self._answer(self.pages[pid])
        raise AssertionError(f"unexpected {method} {url}")

    @staticmethod
    def _answer(data):
        resp = io.BytesIO(json.dumps(data).encode())
        resp.__enter__ = lambda *a: resp
        resp.__exit__ = lambda *a: None
        return resp


def _client(fake):
    return mind.Mind(BASE, TOKEN, "WK", opener=fake)


def _approved(tmp_path, proposal=None):
    ws = _ready(tmp_path, proposal) if proposal else _ready(tmp_path)
    revision.approve(ws, UPDATE, by="Alex")
    return ws


# ── Preflight ───────────────────────────────────────────────────────────────────

def test_preflight_is_clear_for_a_plain_page_exported_after_its_last_change(tmp_path):
    ws = _approved(tmp_path)
    fake = FakeMind().page("101", "Convenciones de nomenclatura")
    check = mind.preflight(ws, UPDATE, _client(fake), exported="2026-10-12T00:00:00Z")
    assert check["blockers"] == [] and check["page"]["id"] == "101" and check["page"]["version"] == 3
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in fake.requests)


def test_a_page_changed_after_the_export_is_blocked(tmp_path):
    ws = _approved(tmp_path)
    fake = FakeMind().page("101", "Convenciones de nomenclatura", when="2026-10-13T08:00:00.000+02:00")
    check = mind.preflight(ws, UPDATE, _client(fake), exported="2026-10-12T00:00:00Z")
    assert len(check["blockers"]) == 1 and "Ana" in check["blockers"][0]


def test_elements_the_proposal_would_lose_block_the_api(tmp_path):
    ws = _approved(tmp_path)
    storage = ('<p>x</p><ac:structured-macro ac:name="jira"/><ac:image><ri:attachment ri:filename="a.png"/>'
               '</ac:image><ac:structured-macro ac:name="code"/>')
    fake = FakeMind().page("101", "Convenciones de nomenclatura", storage=storage)
    check = mind.preflight(ws, UPDATE, _client(fake), exported="2026-10-12T00:00:00Z")
    assert check["blockers"] and "jira" in check["blockers"][0] and "a.png" in check["blockers"][0]
    assert "code" not in check["blockers"][0]  # a code block is written back as a code macro


def test_links_and_layouts_only_warn(tmp_path):
    ws = _approved(tmp_path)
    storage = '<ac:layout><ac:layout-section><ac:link><ri:page ri:content-title="X"/></ac:link></ac:layout-section></ac:layout>'
    fake = FakeMind().page("101", "Convenciones de nomenclatura", storage=storage)
    check = mind.preflight(ws, UPDATE, _client(fake), exported="2026-10-12T00:00:00Z")
    assert check["blockers"] == [] and len(check["warnings"]) == 1


def test_one_link_counts_once():
    lost, converted = mind.inventory('<p><ac:link><ri:page ri:content-title="X"/></ac:link></p>')
    assert lost == [] and converted == ["enlaces internos"]


def test_a_page_missing_in_confluence_is_blocked(tmp_path):
    ws = _approved(tmp_path)
    check = mind.preflight(ws, UPDATE, _client(FakeMind()), exported="2026-10-12T00:00:00Z")
    assert check["blockers"] and "Convenciones de nomenclatura" in check["blockers"][0]


# ── Publish ─────────────────────────────────────────────────────────────────────

def test_publish_backs_up_puts_the_whole_page_and_verifies(tmp_path):
    ws = _approved(tmp_path)
    fake = FakeMind().page("101", "Convenciones de nomenclatura", storage="<p>Antes.</p>")
    page = mind.publish(ws, UPDATE, _client(fake), by="Alex", exported="2026-10-12T00:00:00Z")

    put = next(r for r in fake.requests if r.get_method() == "PUT")
    body = json.loads(put.data)
    assert put.full_url == f"{BASE}/rest/api/content/101"
    assert body["id"] == "101" and body["type"] == "page" and body["space"] == {"key": "WK"}
    assert body["title"] == "Convenciones de nomenclatura" and body["version"]["number"] == 4
    assert "Las ramas usan PROJ-." in body["body"]["storage"]["value"]
    assert body["body"]["storage"]["representation"] == "storage"
    backup = ws / docs_kit.OUT_DIR / mind.BACKUP_DIR / "101-v3.xml"
    assert backup.read_text(encoding="utf-8") == "<p>Antes.</p>"
    assert fake.requests[-1].get_method() == "GET"  # read back before saying it is done
    assert page["status"] == "publicada" and page["published"]["version"] == 4
    assert page["published"]["url"] == f"{BASE}/pages/viewpage.action?pageId=101"


def test_publish_refuses_when_preflight_blocks(tmp_path):
    ws = _approved(tmp_path)
    fake = FakeMind().page("101", "Convenciones de nomenclatura", storage='<ac:structured-macro ac:name="jira"/>')
    with pytest.raises(mind.MindError):
        mind.publish(ws, UPDATE, _client(fake), by="Alex", exported="2026-10-12T00:00:00Z")
    assert not any(r.get_method() == "PUT" for r in fake.requests)


def test_undo_puts_the_backup_back_as_a_new_version(tmp_path):
    ws = _approved(tmp_path)
    fake = FakeMind().page("101", "Convenciones de nomenclatura", storage="<p>Antes.</p>")
    mind.publish(ws, UPDATE, _client(fake), by="Alex", exported="2026-10-12T00:00:00Z")
    page = mind.undo(ws, UPDATE, _client(fake), by="Alex")
    assert fake.pages["101"]["body"]["storage"]["value"] == "<p>Antes.</p>"
    assert fake.pages["101"]["version"]["number"] == 5
    assert page["status"] == "aprobada"


def test_a_new_page_goes_under_its_parent_and_never_twice(tmp_path):
    ws = _ready(tmp_path)
    revision.approve(ws, NEW, by="Alex")
    fake = FakeMind().page("50", "Capacidades")
    page = mind.publish(ws, NEW, _client(fake), by="Alex", exported="2026-10-12T00:00:00Z", parent="Capacidades")
    post = json.loads(next(r for r in fake.requests if r.get_method() == "POST").data)
    assert post["ancestors"] == [{"id": "50"}] and post["space"] == {"key": "WK"}
    assert page["status"] == "publicada"

    revision.reopen(ws, NEW, by="Alex")
    revision.approve(ws, NEW, by="Alex")
    check = mind.preflight(ws, NEW, _client(fake), exported="2026-10-12T00:00:00Z", parent="Capacidades")
    assert check["blockers"]  # the title exists now


def test_a_new_page_needs_an_existing_parent(tmp_path):
    ws = _ready(tmp_path)
    revision.approve(ws, NEW, by="Alex")
    check = mind.preflight(ws, NEW, _client(FakeMind()), exported="2026-10-12T00:00:00Z", parent="No existe")
    assert check["blockers"]


# ── Errors and the token ────────────────────────────────────────────────────────

@pytest.mark.parametrize("code, words", [(401, "token"), (403, "permiso"), (404, "no existe"),
                                         (409, "Otra persona"), (400, "rechaz"), (429, "espere"),
                                         (503, "MIND")])
def test_http_errors_become_readable_and_never_show_the_token(tmp_path, code, words):
    fake = FakeMind(fail={"GET": code})
    with pytest.raises(mind.MindError) as exc:
        _client(fake).find("X")
    assert words in str(exc.value) and TOKEN not in str(exc.value)


def test_only_https_and_no_token_after_a_redirect_elsewhere():
    with pytest.raises(mind.MindError):
        mind.Mind("http://mind.example.org", TOKEN, "WK")
    mind.Mind("http://127.0.0.1:8090", TOKEN, "WK")  # a local fake for trying it out
    handler = mind._SameOriginRedirect(BASE)
    import urllib.request
    req = urllib.request.Request(f"{BASE}/rest/api/content", headers={"Authorization": "Bearer x"})
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x") is None
