"""
space — the Confluence pages a comparison runs against, and where they came from.

Live first: with an address, space and token in Settings, the space (or a root page and its
descendants) is read through the REST API, its storage turned into Markdown with every
Confluence-only element marked, and the snapshot is cached in the workshop with its fetch
time. The cache makes a comparison reproducible and lets a run without network reuse it,
labelled with that time. Without settings, or when Confluence cannot be read and there is
no cache, the Word export in the workshop is used as before.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import i18n
from . import registro as log
from .confluence import Page
from .mind import Mind, MindError, inventory
from .xhtml import storage_to_markdown

SOURCE_FILE = "source.json"  # which source the last comparison used (output/, language-neutral)


@dataclass
class Source:
    kind: str  # "live" | "cache" | "export" | "none"
    pages: list[Page] | None  # None: read the Word export
    created: str = ""  # the baseline: fetch time, or the export's creation date
    info: dict = field(default_factory=dict)
    warning: str = ""

    def summary(self) -> dict:
        return {"kind": self.kind, "created": self.created, "count": len(self.pages or []),
                "warning": self.warning, **self.info}


def live_path(root: Path) -> Path:
    return root / i18n.name("out") / i18n.name("live")


def read_space(client: Mind, root_page: str = "", now: str | None = None) -> dict:
    """The space as Markdown pages, with version, author and address; never the token."""
    found, cut = client.space_pages(root_page)
    pages = []
    for p in found:
        storage = ((p.get("body") or {}).get("storage") or {}).get("value", "")
        version = p.get("version") or {}
        by = version.get("by") or {}
        lost, _ = inventory(storage)
        pages.append({"id": p.get("id", ""), "title": p.get("title", ""), "version": version.get("number"),
                      "when": version.get("when", ""), "by": by.get("displayName") or by.get("username") or "",
                      "url": client.url(p) if p.get("id") else "", "elements": lost,
                      "markdown": storage_to_markdown(storage, p.get("title", ""))})
    return {"fetched": now or log._now(), "base": client.base, "space": client.space, "root": root_page,
            "truncated": cut, "pages": pages}


def save_live(root: Path, snap: dict) -> Path:
    path = live_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_live(root: Path) -> dict | None:
    return log._load(live_path(root), None)


def _from_snapshot(kind: str, snap: dict, warning: str = "") -> Source:
    pages = [Page(p["title"], p["markdown"]) for p in snap.get("pages", []) if p.get("title")]
    if snap.get("truncated"):
        cut = i18n.t("space_cut", n=len(pages))
        warning = f"{warning} {cut}".strip()
    info = {"space": snap.get("space", ""), "root": snap.get("root", ""), "base": snap.get("base", ""),
            "fetched": snap.get("fetched", "")}
    return Source(kind, pages, snap.get("fetched", ""), info, warning)


def resolve(root: Path, client: Mind | None, root_page: str = "", now: str | None = None) -> Source:
    """Live when Confluence is configured and answers; its cached copy when it does not; else the export."""
    if client is None:
        return Source("export", None)
    try:
        snap = read_space(client, root_page, now)
    except MindError as exc:
        cached = load_live(root)
        if cached and cached.get("space") == client.space and cached.get("root", "") == root_page:
            when = cached.get("fetched", "")[:16].replace("T", " ")
            return _from_snapshot("cache", cached, i18n.t("space_offline_cache", error=exc, when=when))
        return Source("export", None, warning=i18n.t("space_offline_export", error=exc))
    save_live(root, snap)
    return _from_snapshot("live", snap)


def write_summary(root: Path, source: Source) -> dict:
    out = root / i18n.name("out")
    out.mkdir(parents=True, exist_ok=True)
    data = {**source.summary(), "used": log._now()}
    (out / SOURCE_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def last_summary(root: Path) -> dict:
    return log._load(root / i18n.name("out") / SOURCE_FILE, {})
