"""space: the Confluence pages a comparison runs against — live by REST (cached), else the Word export."""
import io
import json
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n, mind, space  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402

BASE = "https://wiki.example.org"
TOKEN = "pat-very-secret-42"


class FakeSpace:
    """Confluence's /rest/api/content listing, paginated like Data Center (start/limit/_links.next)."""

    def __init__(self, n=0, fail=None, storage=None):
        self.pages = [self._page(str(100 + i), f"Page {i:03d}", storage or f"<p>Body {i}.</p>") for i in range(n)]
        self.children: dict[str, list[dict]] = {}
        self.fail = fail
        self.requests = []

    @staticmethod
    def _page(pid, title, storage, version=4):
        return {"id": pid, "type": "page", "title": title,
                "version": {"number": version, "when": "2026-10-10T08:00:00.000Z", "by": {"displayName": "Dana Reyes"}},
                "body": {"storage": {"value": storage, "representation": "storage"}},
                "_links": {"webui": f"/pages/viewpage.action?pageId={pid}"}}

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise urllib.error.HTTPError(req.full_url, self.fail, "x", {}, io.BytesIO(b'{"message": "no"}'))
        url = urlsplit(req.full_url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path.split("/rest/api", 1)[1]
        if path == "/content" and "title" in q:
            hits = [p for p in self.pages if p["title"] == q["title"]]
            return self._answer({"results": hits, "size": len(hits)})
        if path == "/content":
            assert q["spaceKey"] == "TRAMS" and "body.storage" in q["expand"]
            return self._slice(self.pages, q, "/rest/api/content")
        if path.endswith("/descendant/page"):
            pid = path.split("/")[2]
            return self._slice(self.children.get(pid, []), q, path)
        raise AssertionError(f"unexpected {req.full_url}")

    def _slice(self, items, q, path):
        start, limit = int(q.get("start", 0)), int(q.get("limit", 25))
        chunk = items[start:start + limit]
        links = {"base": BASE}
        if start + limit < len(items):
            links["next"] = f"{path}?start={start + limit}&limit={limit}"
        return self._answer({"results": chunk, "start": start, "limit": limit, "size": len(chunk), "_links": links})

    @staticmethod
    def _answer(data):
        resp = io.BytesIO(json.dumps(data).encode())
        resp.__enter__ = lambda *a: resp
        resp.__exit__ = lambda *a: None
        return resp


def _client(fake):
    return mind.Mind(BASE, TOKEN, "TRAMS", opener=fake)


def test_the_whole_space_is_read_page_by_page():
    fake = FakeSpace(120)
    pages, truncated = _client(fake).space_pages(limit=50)
    assert len(pages) == 120 and not truncated
    starts = [parse_qs(urlsplit(r.full_url).query)["start"][0] for r in fake.requests]
    assert starts == ["0", "50", "100"]


def test_a_root_page_reads_itself_and_its_descendants():
    fake = FakeSpace(3)
    fake.children["100"] = [FakeSpace._page("900", "Child A", "<p>a</p>"), FakeSpace._page("901", "Child B", "<p>b</p>")]
    pages, _ = _client(fake).space_pages("Page 000", limit=1)
    assert [p["title"] for p in pages] == ["Page 000", "Child A", "Child B"]


def test_a_missing_root_page_says_so():
    with pytest.raises(mind.MindError, match="Nowhere"):
        _client(FakeSpace(1)).space_pages("Nowhere")


def test_reading_stops_at_the_cap_and_says_it_was_cut():
    pages, truncated = _client(FakeSpace(30)).space_pages(limit=10, cap=25)
    assert len(pages) == 25 and truncated


def test_a_snapshot_keeps_versions_and_markers_and_never_the_token(tmp_path):
    i18n.use("en")
    fake = FakeSpace(2, storage='<p>Hi.</p><ac:structured-macro ac:name="jira"/>')
    snap = space.read_space(_client(fake), now="2026-10-14T10:42:00+00:00")
    assert snap["fetched"] == "2026-10-14T10:42:00+00:00" and snap["space"] == "TRAMS"
    first = snap["pages"][0]
    assert first["title"] == "Page 000" and first["version"] == 4 and first["by"] == "Dana Reyes"
    assert first["markdown"].startswith("# Page 000\n") and "⟦Confluence macro: jira⟧" in first["markdown"]
    assert first["url"].endswith("pageId=100")
    space.save_live(tmp_path, snap)
    assert TOKEN not in json.dumps(snap) and TOKEN not in space.live_path(tmp_path).read_text(encoding="utf-8")
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in fake.requests)
    assert all(TOKEN not in r.full_url for r in fake.requests)


@pytest.mark.parametrize("code", [401, 403, 404, 409, 413, 429, 500, 503])
def test_http_errors_are_readable_and_never_carry_the_token(code):
    with pytest.raises(mind.MindError) as err:
        _client(FakeSpace(1, fail=code)).space_pages()
    assert TOKEN not in str(err.value) and str(err.value)


# ── Choosing the source ─────────────────────────────────────────────────────────

def _workshop(tmp_path):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "es")
    return ws


def test_live_is_used_and_cached_when_confluence_answers(tmp_path):
    ws = _workshop(tmp_path)
    src = space.resolve(ws, _client(FakeSpace(3)), now="2026-10-14T10:42:00+00:00")
    assert src.kind == "live" and len(src.pages) == 3 and src.created == "2026-10-14T10:42:00+00:00"
    assert src.pages[0].markdown.startswith("# Page 000")
    assert space.load_live(ws)["fetched"] == "2026-10-14T10:42:00+00:00"


def test_without_network_the_cached_snapshot_is_reused_with_its_time(tmp_path):
    ws = _workshop(tmp_path)
    space.resolve(ws, _client(FakeSpace(3)), now="2026-10-14T10:42:00+00:00")
    src = space.resolve(ws, _client(FakeSpace(3, fail=503)))
    assert src.kind == "cache" and len(src.pages) == 3 and src.created == "2026-10-14T10:42:00+00:00"
    assert "10:42" in src.warning and TOKEN not in src.warning


def test_without_network_or_cache_the_word_export_is_the_fallback(tmp_path):
    ws = _workshop(tmp_path)
    src = space.resolve(ws, _client(FakeSpace(0, fail=401)))
    assert src.kind == "export" and src.pages is None and src.warning


def test_without_settings_the_word_export_is_used_silently(tmp_path):
    src = space.resolve(_workshop(tmp_path), None)
    assert src.kind == "export" and src.pages is None and not src.warning


def test_a_live_comparison_marks_the_baseline_with_the_fetch_time(tmp_path):
    ws = _workshop(tmp_path)
    fake = FakeSpace(0)
    fake.pages = [FakeSpace._page("100", "Fare Engine overview", "<p>Computes the fare.</p>")]
    (ws / "2-mi-documentacion" / "fares.md").write_text(
        "# Fare Engine overview\n\nInstrucciones de actualización: add the off-peak discount.\n", encoding="utf-8")
    src = space.resolve(ws, _client(fake), now="2026-10-14T10:42:00+00:00")
    result = docs_kit.run_workspace(ws, source=src)
    assert len(result["tasks"]) == 1 and result["source"]["kind"] == "live"
    out = ws / "salida"
    task = out / "tareas" / result["tasks"][0]
    assert "Computes the fare." in (task / "ACTUAL.md").read_text(encoding="utf-8")
    snap = json.loads((out / "registro-export.json").read_text(encoding="utf-8"))
    assert snap["created"] == "2026-10-14T10:42:00+00:00" and snap["source"] == "live"
    assert json.loads((out / space.SOURCE_FILE).read_text(encoding="utf-8"))["kind"] == "live"
