"""
registro.py — Registro de cambios del taller: qué cambió y quién lo cambió.

Cada ejecución del taller añade al registro (salida/registro.json y registro.html):

  confluence  páginas que cambian entre el export anterior y el nuevo, con el autor,
              la fecha y el comentario de versión que da la API de Confluence
  codigo      commits de los clones locales de repos.txt, con las páginas que los citan
  peticion    cada línea de peticiones.md («- Nombre: qué hay que cambiar»); la IA dice
              qué página tocar, qué cambiar y por qué, y se prepara su tarea
  taller      propuestas (RESULTADO.md) listas, con quién ejecutó el taller

Sólo biblioteca estándar. Sin token de Confluence el registro sigue funcionando,
pero sin autores. Las entradas no se repiten al volver a ejecutar.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import i18n
from . import taller as kit
from .confluence import Page, _slug, normalize_title

DEFAULT_LOOKBACK_DAYS = 90
MAX_VERSIONS = 50

# Workshop names and texts, kept as module attributes; they follow the current language.
_NAMES = {"LOG_JSON": "log_json", "LOG_HTML": "log_html", "SNAPSHOT": "snapshot", "REPOS_FILE": "repos",
          "REQUESTS_FILE": "requests", "REQUESTS_DIR": "requests_dir"}
_TEXTS = {"REQUESTS_TEXT": "requests_text", "REPOS_TEXT": "repos_text"}


def __getattr__(attr: str) -> str:
    if attr in _NAMES:
        return i18n.name(_NAMES[attr])
    if attr in _TEXTS:
        return i18n.t(_TEXTS[attr])
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


Ai = Callable[[str], str]


def _ts(value: str) -> datetime:
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


# ── Confluence: who changed a page ─────────────────────────────────────────────

class ConfluenceHistory:
    """Version history through the REST API.

    Data Center / Server: personal access token as Bearer on <base>/rest/api.
    Cloud (*.atlassian.net): e-mail + API token as Basic on <base>/wiki/rest/api."""

    def __init__(self, base: str, token: str, space: str = "", user: str = "",
                 opener=urllib.request.urlopen, timeout: float = 30):
        base = base.rstrip("/")
        if ".atlassian.net" in base and not base.endswith("/wiki"):
            base += "/wiki"
        self.api, self.space, self.opener, self.timeout = base + "/rest/api", space, opener, timeout
        if user:
            self.auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
        else:
            self.auth = "Bearer " + token

    def _get(self, path: str, **query) -> dict:
        url = f"{self.api}{path}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(url, headers={"Authorization": self.auth, "Accept": "application/json"})
        with self.opener(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _version(v: dict) -> dict:
        by = v.get("by") or {}
        return {"number": v.get("number"), "by": by.get("displayName") or by.get("username") or "?",
                "when": v.get("when", ""), "message": v.get("message") or ""}

    def changes(self, title: str, since: str) -> list[dict]:
        """Versions of the page saved after `since`, newest first."""
        query = {"title": title, "expand": "version"}
        if self.space:
            query["spaceKey"] = self.space
        results = self._get("/content", **query).get("results") or []
        if not results:
            return []
        page = results[0]
        latest = self._version(page["version"])
        out, limit = [], _ts(since)
        for number in range(latest["number"], max(0, latest["number"] - MAX_VERSIONS), -1):
            if number == latest["number"]:
                v = latest
            else:
                data = self._get(f"/content/{page['id']}", status="historical", version=number, expand="version")
                v = self._version(data["version"])
            if not v["when"] or _ts(v["when"]) <= limit:
                break
            out.append(v)
        return out


# ── Exports: what changed ──────────────────────────────────────────────────────

@dataclass
class PageChange:
    title: str
    kind: str  # "cambiada" | "nueva" | "eliminada"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def summary(self, limit: int = 8) -> str:
        lines = [f"+ {l}" for l in self.added] + [f"- {l}" for l in self.removed]
        more = len(lines) - limit
        return "\n".join(lines[:limit] + ([i18n.t("more_lines", n=more)] if more > 0 else []))


def _body(page: Page) -> list[str]:
    return [l.strip() for l in page.markdown.splitlines()[1:] if l.strip()]


def diff_pages(old: list[Page], new: list[Page]) -> list[PageChange]:
    before, after = {p.title: p for p in old}, {p.title: p for p in new}
    changes = []
    for title, page in after.items():
        if title not in before:
            changes.append(PageChange(title, "nueva", _body(page)))
            continue
        a, b = _body(before[title]), _body(page)
        if a == b:
            continue
        diff = list(difflib.ndiff(a, b))
        changes.append(PageChange(title, "cambiada", [l[2:] for l in diff if l.startswith("+ ")],
                                  [l[2:] for l in diff if l.startswith("- ")]))
    changes += [PageChange(t, "eliminada", removed=_body(p)) for t, p in before.items() if t not in after]
    return changes


def export_created(path: Path) -> str:
    """Creation date the Word exporter stamps in docProps/core.xml ("" when missing)."""
    try:
        with zipfile.ZipFile(path) as z:
            core = ET.fromstring(z.read("docProps/core.xml"))
    except (KeyError, zipfile.BadZipFile):
        return ""
    el = core.find("{http://purl.org/dc/terms/}created")
    return (el.text or "").strip() if el is not None else ""


# ── Code: commits from local clones ────────────────────────────────────────────

def git_commits(repo: Path, since: str, run=subprocess.run) -> list[dict]:
    proc = run(["git", "-C", str(repo), "log", f"--since={since}", "--no-merges", "--name-only",
                "--format=%x1e%H%x1f%an%x1f%aI%x1f%s"], capture_output=True, text=True,
               encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(i18n.t("err_git", repo=repo, error=(proc.stderr or "").strip()[-300:]))
    commits = []
    for record in proc.stdout.split("\x1e")[1:]:
        head, _, files = record.partition("\n")
        sha, by, when, subject = head.split("\x1f", 3)
        commits.append({"repo": Path(repo).name, "hash": sha, "by": by, "when": when, "subject": subject,
                        "files": [f.strip() for f in files.splitlines() if f.strip()]})
    return commits


def affected_pages(commit: dict, pages: list[Page]) -> list[str]:
    """Pages that mention the repo or a touched file: their text may now be stale."""
    names = {commit["repo"].lower()}
    for f in commit["files"]:
        name = Path(f).name.lower()
        if len(Path(name).stem) >= 5:
            names |= {name, Path(name).stem}
    hits = []
    for page in pages:
        text = page.markdown.lower()
        if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text) for n in names):
            hits.append(page.title)
    return hits


def read_repos(root: Path) -> list[Path]:
    path = root / i18n.name("repos")
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Path(l.strip()).expanduser() for l in lines if l.strip() and not l.lstrip().startswith("#")]


# ── Change requests routed by the AI ───────────────────────────────────────────

REQUEST_LINE = re.compile(r"^\s*[-*]\s*([^:\n]{1,60}):\s*(.+?)\s*$")


def read_requests(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = REQUEST_LINE.match(line)
        if m:
            by, req = m.group(1).strip(), m.group(2).strip()
            out.append({"id": _id("peticion", by, req), "by": by, "text": req})
    return out


def _json_object(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _match_title(answer: str, pages: list[Page]) -> str:
    """The page the AI named: exact, ignoring case and accents, or the longest title it starts with."""
    wanted = normalize_title(answer.strip(" «»\"'"))
    if not wanted:
        return ""
    for p in pages:
        if normalize_title(p.title) == wanted:
            return p.title
    starts = [p.title for p in pages if re.match(re.escape(normalize_title(p.title)) + r"\b", wanted)]
    return max(starts, key=len) if starts else ""


def route_request(request: dict, pages: list[Page], ai: Ai) -> dict:
    """Asks the AI which page the request belongs to, what to change and why."""
    listing = "\n".join(f"- «{p.title}» — {' '.join(_body(p))[:200]}" for p in pages)
    prompt = i18n.t("route_prompt", by=request["by"], text=request["text"], listing=listing)
    data = _json_object(ai(prompt))

    def field(*keys: str) -> str:
        return next((str(data[k]).strip() for k in keys if data.get(k)), "")

    # The log stores the Spanish keys; the AI may answer with either language's.
    return {"pagina": _match_title(field("page", "pagina", "página"), pages),
            "cambio": field("change", "cambio"), "motivo": field("reason", "motivo")}


def _request_task(out: Path, entry: dict, page: Page, template, bible: str) -> str:
    slug = f"{_slug(page.title)}-{entry['id'][:6]}"
    n = i18n.name
    rel = f"{n('requests_dir')}/{slug}"
    d = out / rel
    d.mkdir(parents=True, exist_ok=True)
    local = i18n.t("request_local", title=page.title, change=entry["cambio"] or entry["request"],
                   by=entry["by"], request=entry["request"], reason=entry["motivo"])
    task = kit.Task(slug, "update", page.title, n("requests"), page)
    (d / n("local_copy")).write_text(local, encoding="utf-8")
    (d / n("current")).write_text(page.markdown, encoding="utf-8")
    (d / n("task")).write_text(kit._prompt(task, local, template, bible), encoding="utf-8")
    return rel


# ── The log ───────────────────────────────────────────────────────────────────

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user() -> str:
    return os.environ.get("AMANUENSE_USER") or os.environ.get("USERNAME") or os.environ.get("USER") or "?"


def update_log(root: Path, exports: list[Path], pages: list[Page], ready: dict[str, kit.Task],
               history: ConfluenceHistory | None = None, router: Ai | None = None,
               template=None, bible: str = "", run=subprocess.run) -> dict:
    """Adds this run's changes to the log; returns {"entries", "request_tasks", "errors"}."""
    n = i18n.name
    out = root / n("out")
    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = _load(out / n("log_json"), [])
    known = {e["id"] for e in entries}
    errors: list[str] = []

    def add(entry: dict) -> None:
        if entry["id"] not in known:
            known.add(entry["id"])
            entries.append(entry)

    # Confluence: compare with the export seen last time.
    created = max((export_created(e) for e in exports), default="") or _now()
    snap = _load(out / n("snapshot"), None)
    current = {p.title: p.markdown for p in pages}
    if pages and snap and snap["pages"] != current:
        old = [Page(t, m) for t, m in snap["pages"].items()]
        for change in diff_pages(old, pages):
            versions: list[dict] = []
            if history and change.kind != "eliminada":
                try:
                    versions = history.changes(change.title, since=snap["created"])
                except Exception as exc:  # no network or no permission: keep the "what"
                    errors.append(f"Confluence ({change.title}): {exc}")
            authors = list(dict.fromkeys(v["by"] for v in versions))
            add({"id": _id("confluence", change.title, snap["created"], created), "kind": "confluence",
                 "when": versions[0]["when"] if versions else created, "page": change.title,
                 "by": ", ".join(authors) if authors else "?", "change": change.kind,
                 "what": change.summary(), "message": "; ".join(v["message"] for v in versions if v["message"])})
    if pages and (not snap or snap["pages"] != current):
        (out / n("snapshot")).write_text(json.dumps({"created": created, "pages": current}, ensure_ascii=False),
                                    encoding="utf-8")

    # Code: commits since the previous export (or a lookback window the first time).
    since = snap["created"] if snap else (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    for repo in read_repos(root):
        try:
            commits = git_commits(repo, since, run)
        except Exception as exc:
            errors.append(f"git ({repo}): {exc}")
            continue
        for c in commits:
            add({"id": _id("codigo", c["hash"]), "kind": "codigo", "when": c["when"], "by": c["by"],
                 "page": "", "repo": c["repo"], "what": c["subject"], "files": c["files"],
                 "pages": affected_pages(c, pages)})

    # Requests: route each new one, prepare its task.
    by_title = {p.title: p for p in pages}
    req_file = root / n("requests")
    for req in read_requests(req_file.read_text(encoding="utf-8") if req_file.is_file() else ""):
        previous = next((e for e in entries if e["id"] == req["id"]), None)
        if not router or (previous and previous.get("page")):
            continue  # routed already; one the AI could not place is retried
        try:
            route = route_request(req, pages, router)
        except Exception as exc:
            errors.append(i18n.t("err_request", by=req["by"], error=exc))
            continue
        entry = {"id": req["id"], "kind": "peticion", "when": _now(), "by": req["by"], "request": req["text"],
                 "page": route["pagina"], "cambio": route["cambio"], "motivo": route["motivo"], "task": ""}
        if entry["page"]:
            entry["task"] = _request_task(out, entry, by_title[entry["page"]], template, bible)
        if previous:
            entries.remove(previous)
            known.discard(previous["id"])
        add(entry)

    # Workshop: proposals that are ready, from page tasks and request tasks.
    request_tasks = {e["task"]: e for e in entries if e["kind"] == "peticion" and e.get("task")}
    for rel, entry in request_tasks.items():
        page = by_title.get(entry["page"])
        task = kit.Task(Path(rel).name, "update", entry["page"], n("requests"), page)
        if (out / rel).is_dir() and kit._publish(out / rel, task) is not None:
            ready[rel] = task
    for rel, task in ready.items():
        result = (out / rel / n("result")).read_text(encoding="utf-8")
        add({"id": _id("taller", rel, result), "kind": "taller", "when": _now(), "by": _user(),
             "page": task.title, "what": i18n.t("proposal_ready"), "task": rel})

    (out / n("log_json")).write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / n("log_html")).write_text(render_log(entries, errors), encoding="utf-8")
    return {"entries": entries, "request_tasks": sorted(request_tasks), "errors": errors}


def _label(prefix: str, value: str) -> str:
    key = f"{prefix}_{value}"
    return i18n.t(key) if key in i18n.TEXT else value


def _detail(e: dict) -> str:
    esc, n, t = html.escape, i18n.name, i18n.t
    if e["kind"] == "confluence":
        msg = f"<p>«{esc(e['message'])}»</p>" if e.get("message") else ""
        return f"{esc(_label('change', e['change']))}{msg}<pre>{esc(e['what'])}</pre>"
    if e["kind"] == "codigo":
        pages = (f"<p><b>{t('review')}</b> {esc(', '.join(e['pages']))}</p>" if e.get("pages") else "")
        return f"{esc(e['repo'])}: {esc(e['what'])}<br><small>{esc(', '.join(e['files'][:6]))}</small>{pages}"
    if e["kind"] == "peticion":
        if not e.get("page"):
            return f"«{esc(e['request'])}»<p>{t('no_page')}</p>"
        return (f"«{esc(e['request'])}»<p><b>{t('what')}</b> {esc(e['cambio'])}<br><b>{t('why')}</b> "
                f"{esc(e['motivo'])}</p><a href=\"{esc(e['task'])}/{n('task')}\">{n('task')}</a>")
    return f'{esc(e["what"])} · <a href="{esc(e["task"])}/{n("changes")}">{n("changes")}</a>'


def render_log(entries: list[dict], errors: list[str] | None = None) -> str:
    t = i18n.t
    rows = []
    for e in sorted(entries, key=lambda e: e["when"], reverse=True):
        rows.append(f"<tr><td>{html.escape(e['when'][:16].replace('T', ' '))}</td>"
                    f"<td>{_label('kind', e['kind'])}</td><td>{html.escape(e['by'])}</td>"
                    f"<td>{html.escape(e.get('page') or '')}</td><td>{_detail(e)}</td></tr>")
    warn = (f"<p><b>{t('log_warnings')}</b></p><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in errors)
            + "</ul>" if errors else "")
    heads = "".join(f"<th>{t(k)}</th>" for k in ("col_date", "col_source", "col_who", "col_page", "col_what"))
    body = (f"<h1>{t('log_title')}</h1><p>{t('log_intro', requests=i18n.name('requests'))}</p>{warn}"
            f"<table><thead><tr>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table>")
    return kit._html_page(t("log_title"), body)


def history_from_env(env=os.environ) -> ConfluenceHistory | None:
    url, token = env.get("AMANUENSE_CONFLUENCE_URL", ""), env.get("AMANUENSE_CONFLUENCE_TOKEN", "")
    if not (url and token):
        return None
    return ConfluenceHistory(url, token, env.get("AMANUENSE_CONFLUENCE_SPACE", ""),
                             env.get("AMANUENSE_CONFLUENCE_USER", ""))
