"""
mind — publishing a reviewed page to Confluence Data Center (MIND) through its REST API.

Nothing is lost silently. The Word export keeps neither Confluence's storage format nor
the page version, so the baseline is read from the API right before publishing, and the
checks block instead of warning:

- the page changed after the export        → blocked (someone else's edit would be lost)
- the page holds macros, images, comments… → blocked (the proposal cannot carry them)
- internal links or column layouts         → a warning the reviewer accepts explicitly

Before a PUT the current storage is saved to output/mind-copias/ so it can be put back;
after it, the page is read again and only then marked as published.
"""
from __future__ import annotations

import html
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from . import i18n
from . import registro as log
from . import revision
from . import taller as kit

BACKUP_DIR = "mind-copias"
SPACE_PAGE_SIZE = 50  # pages per request when reading a whole space
SPACE_MAX_PAGES = 5000  # a space bigger than this is cut, and the reviewer is told
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
KEPT = {"structured-macro:code", "plain-text-body", "parameter"}  # a code block goes back as a code macro
CONVERTED = {"link", "layout", "layout-section", "layout-cell", "emoticon"}
INSIDE = {"page", "url", "space", "content-entity", "user", "blog-post", "link-body", "plain-text-link-body"}  # part of a link


class MindError(Exception):
    """A message the reviewer can act on; it never carries the token."""


def _origin(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme, parts.netloc.lower()


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follows redirects inside MIND only: the token is never sent to another host."""

    def __init__(self, base: str):
        self.base = base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != _origin(self.base):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Mind:
    def __init__(self, base: str, token: str, space: str, user: str = "", opener=None, timeout: float = 30):
        base = base.rstrip("/")
        scheme, host = _origin(base)
        if scheme != "https" and host.split(":")[0] not in LOCAL_HOSTS and not host.startswith("[::1]"):
            raise MindError(i18n.t("mind_https_only"))
        if ".atlassian.net" in base and not base.endswith("/wiki"):
            base += "/wiki"
        self.base, self.space, self.timeout = base, space, timeout
        self.auth = log.confluence_auth(token, user)
        self.opener = opener or urllib.request.build_opener(_SameOriginRedirect(base)).open

    def _call(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
        url = f"{self.base}/rest/api{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": self.auth, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise MindError(self._explain(exc)) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            raise MindError(i18n.t("mind_unreachable", base=self.base, reason=reason)) from None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise MindError(i18n.t("mind_not_json")) from None

    @staticmethod
    def _explain(exc: urllib.error.HTTPError) -> str:
        code = exc.code
        if 300 <= code < 400:
            return i18n.t("mind_redirected")
        if code == 400:
            try:
                detail = str(json.loads(exc.read()).get("message", ""))[:300]
            except (ValueError, AttributeError):
                detail = ""
            return i18n.t("mind_400", detail=detail)
        key = {401: "mind_401", 403: "mind_403", 404: "mind_404", 409: "mind_409", 413: "mind_413",
               429: "mind_429"}.get(code, "mind_5xx")
        return i18n.t(key, code=code)

    def me(self) -> str:
        data = self._call("GET", "/user/current")
        return data.get("displayName") or data.get("username") or "?"

    def find(self, title: str) -> dict | None:
        data = self._call("GET", "/content", {"title": title, "spaceKey": self.space, "type": "page",
                                               "expand": "version,body.storage,space"})
        hits = [p for p in data.get("results") or [] if p.get("title") == title]
        return hits[0] if hits else None

    def get(self, page_id: str) -> dict:
        return self._call("GET", f"/content/{page_id}", {"expand": "version,body.storage,space"})

    def space_pages(self, root: str = "", limit: int = SPACE_PAGE_SIZE, cap: int = SPACE_MAX_PAGES) -> tuple[list[dict], bool]:
        """Every page of the space (or `root`, a title or an id, and its descendants) with its
        storage and version, read page by page; (pages, whether the cap cut the list)."""
        expand = "version,body.storage"
        found: list[dict] = []
        if root:
            top = self.get(root) if root.isdigit() else self.find(root)
            if not top:
                raise MindError(i18n.t("mind_root_missing", title=root, space=self.space))
            found.append(top)
            path, query = f"/content/{top['id']}/descendant/page", {"expand": expand}
        else:
            path, query = "/content", {"spaceKey": self.space, "type": "page", "expand": expand}
        start = 0
        while True:
            data = self._call("GET", path, {**query, "start": start, "limit": limit})
            results = data.get("results") or []
            found += results
            more = "next" in (data.get("_links") or {}) or len(results) >= limit
            if not results or not more:
                return found[:cap], len(found) > cap
            if len(found) >= cap:
                return found[:cap], True
            start += len(results)

    def update(self, page: dict, storage: str, message: str) -> dict:
        number = page["version"]["number"] + 1
        return self._call("PUT", f"/content/{page['id']}", body={
            "id": page["id"], "type": "page", "title": page["title"], "space": {"key": self.space},
            "version": {"number": number, "message": message},
            "body": {"storage": {"value": storage, "representation": "storage"}}})

    def create(self, title: str, parent_id: str, storage: str) -> dict:
        return self._call("POST", "/content", body={
            "type": "page", "title": title, "space": {"key": self.space}, "ancestors": [{"id": parent_id}],
            "body": {"storage": {"value": storage, "representation": "storage"}}})

    def url(self, page: dict) -> str:
        links = page.get("_links") or {}
        return (links.get("base") or self.base) + links.get("webui", f"/pages/viewpage.action?pageId={page['id']}")


# ── Markdown → Confluence storage ──────────────────────────────────────────────

def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def strip_title(markdown: str, title: str) -> str:
    """The page body: Confluence shows the title itself, so a leading `# Title` would repeat it."""
    lines = markdown.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is not None and re.match(r"^#\s+" + re.escape(title.strip()) + r"\s*$", lines[first].strip()):
        lines = lines[:first] + lines[first + 1:]
    return "\n".join(lines) + "\n"


def markdown_to_storage(markdown: str, title: str) -> str:
    """XHTML Confluence accepts as `storage`: the page body without its own title."""
    body = kit.markdown_to_html(strip_title(markdown, title))
    body = re.sub(r"<pre><code>(.*?)</code></pre>",
                  lambda m: ('<ac:structured-macro ac:name="code"><ac:plain-text-body>'
                             f"{_cdata(html.unescape(m.group(1)))}</ac:plain-text-body></ac:structured-macro>"),
                  body, flags=re.S)
    body = re.sub(r'<img alt="([^"]*)" src="([^"]*)">',
                  r'<ac:image ac:alt="\1"><ri:url ri:value="\2"/></ac:image>', body)
    return body.replace("<br>", "<br/>")


# ── What the page holds that the proposal cannot carry ─────────────────────────

def inventory(storage: str) -> tuple[list[str], list[str]]:
    """(lost, converted): human labels of the Confluence-only elements in the page."""
    lost: Counter = Counter()
    converted: Counter = Counter()
    for prefix, name, attrs in re.findall(r"<(ac|ri):([\w-]+)([^>]*)>", storage):
        if prefix == "ac" and name == "structured-macro":
            macro = re.search(r'ac:name="([^"]+)"', attrs)
            key = f"structured-macro:{macro.group(1) if macro else '?'}"
            if key not in KEPT:
                lost[i18n.t("mind_el_macro", name=key.split(":", 1)[1])] += 1
        elif name == "attachment":
            file = re.search(r'ri:filename="([^"]+)"', attrs)
            lost[i18n.t("mind_el_attachment", name=file.group(1) if file else "?")] += 1
        elif name == "image":
            lost[i18n.t("mind_el_image")] += 1
        elif name in KEPT or name in INSIDE:
            continue
        elif name in CONVERTED:
            if name not in ("layout-section", "layout-cell"):  # one layout, however many columns
                converted[i18n.t("mind_el_" + {"layout": "layout", "emoticon": "emoticon"}.get(name, "link"))] += 1
        else:
            lost[f"{prefix}:{name}"] += 1

    def label(c: Counter) -> list[str]:
        return [f"{k} ×{v}" if v > 1 else k for k, v in sorted(c.items())]
    return label(lost), label(converted)


# ── Preflight, publish, undo ───────────────────────────────────────────────────

def export_date(root: Path) -> str:
    """When the export that ACTUAL.md comes from was made."""
    snap = log._load(root / i18n.name("out") / i18n.name("snapshot"), {})
    return snap.get("created", "")


def _who(page: dict) -> tuple[str, str]:
    v = page.get("version") or {}
    by = v.get("by") or {}
    return by.get("displayName") or by.get("username") or "?", v.get("when", "")


def preflight(root: Path, rel: str, client: Mind, exported: str | None = None, parent: str | None = None) -> dict:
    page = revision.find(root, rel)
    exported = exported if exported is not None else export_date(root)
    blockers: list[str] = []
    warnings: list[str] = []
    found = {"title": page["title"], "new": page["new"], "page": None, "parent": None}
    if page["status"] != "aprobada":
        blockers.append(i18n.t("review_publish_unapproved"))
    remote = client.find(page["title"])
    if page["new"]:
        if remote:
            blockers.append(i18n.t("mind_title_taken", title=page["title"], url=client.url(remote)))
        if not parent:
            blockers.append(i18n.t("mind_pick_parent"))
        else:
            up = client.find(parent)
            if not up:
                blockers.append(i18n.t("mind_parent_missing", title=parent, space=client.space))
            else:
                found["parent"] = {"id": up["id"], "title": up["title"], "url": client.url(up)}
    elif not remote:
        blockers.append(i18n.t("mind_page_missing", title=page["title"], space=client.space))
    else:
        by, when = _who(remote)
        found["page"] = {"id": remote["id"], "version": remote["version"]["number"], "by": by, "when": when,
                         "url": client.url(remote)}
        if not exported:
            blockers.append(i18n.t("mind_no_export_date"))
        elif when and log._ts(when) > log._ts(exported):
            blockers.append(i18n.t("mind_changed_after_export", by=by, when=when[:16].replace("T", " "),
                                   exported=exported[:16].replace("T", " ")))
        lost, converted = inventory(remote["body"]["storage"]["value"])
        if lost:
            blockers.append(i18n.t("mind_would_lose", items=", ".join(lost)))
        if converted:
            warnings.append(i18n.t("mind_would_convert", items=", ".join(converted)))
    return {**found, "blockers": blockers, "warnings": warnings}


def _result(root: Path, rel: str) -> str:
    return (root / i18n.name("out") / rel / i18n.name("result")).read_text(encoding="utf-8")


def publish(root: Path, rel: str, client: Mind, by: str, exported: str | None = None, parent: str | None = None,
            accept_warnings: bool = False) -> dict:
    check = preflight(root, rel, client, exported, parent)
    if check["blockers"]:
        raise MindError(" · ".join(check["blockers"]))
    if check["warnings"] and not accept_warnings:
        raise MindError(i18n.t("mind_accept_warnings", items=" · ".join(check["warnings"])))
    title = check["title"]
    storage = markdown_to_storage(_result(root, rel), title)
    message = i18n.t("mind_version_message", by=by)
    if check["new"]:
        made = client.create(title, check["parent"]["id"], storage)
        got = client.get(made["id"])
        if got.get("title") != title:
            raise MindError(i18n.t("mind_not_verified"))
        return revision.mark_published(root, rel, by, "api", client.url(got), got["version"]["number"],
                                       page_id=got["id"])
    remote = client.find(title)
    backups = root / i18n.name("out") / BACKUP_DIR
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f'{remote["id"]}-v{remote["version"]["number"]}.xml'
    kept = backup.exists()
    backup.write_text(remote["body"]["storage"]["value"], encoding="utf-8")
    try:
        client.update(remote, storage, message)
    except Exception:
        if not kept:
            backup.unlink(missing_ok=True)  # the update failed: nothing was written, so no copy is left behind
        raise
    got = client.get(remote["id"])
    if got["version"]["number"] != remote["version"]["number"] + 1 or got.get("title") != title:
        raise MindError(i18n.t("mind_not_verified"))
    return revision.mark_published(root, rel, by, "api", client.url(got), got["version"]["number"],
                                   page_id=got["id"], backup=backup.name)


def undo(root: Path, rel: str, client: Mind, by: str) -> dict:
    """Puts the saved copy back as a new version; a page created here is left for a person to delete."""
    page = revision.find(root, rel)
    published = page.get("published") or {}
    if page["status"] != "publicada" or published.get("mode") != "api":
        raise revision.ReviewError(i18n.t("mind_nothing_to_undo"))  # a state conflict (409), not a Confluence failure
    if not published.get("backup"):
        raise MindError(i18n.t("mind_undo_new_page", url=published.get("url", "")))
    saved = (root / i18n.name("out") / BACKUP_DIR / published["backup"]).read_text(encoding="utf-8")
    remote = client.get(published["page_id"])
    client.update(remote, saved, i18n.t("mind_undo_message", by=by))
    got = client.get(published["page_id"])
    if got["version"]["number"] != remote["version"]["number"] + 1:
        raise MindError(i18n.t("mind_not_verified"))
    return revision._set(root, rel, "aprobada", by, i18n.t("mind_undone", url=published.get("url", "")))
