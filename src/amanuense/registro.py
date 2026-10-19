"""
registro.py — Registro de cambios del taller: qué cambió y quién lo cambió.

Cada ejecución del taller añade al registro (salida/registro.json y registro.html):

  confluence  páginas que cambian entre el export anterior y el nuevo, con el autor,
              la fecha y el comentario de versión que da la API de Confluence
  codigo      commits de los repos de repos.txt (clones locales o URL que se clonan y se
              actualizan en cada ejecución, en las ramas indicadas), con las páginas que
              los citan; cada página que toca un commit nuevo recibe una tarea con su diff
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

from . import i18n, settings
from . import taller as kit
from .confluence import Page, _slug, normalize_title

DEFAULT_LOOKBACK_DAYS = 90
MAX_VERSIONS = 50
MAX_DIFF = 6000  # characters of diff per commit in a code task
MAX_TASK_DIFF = 40000  # characters of diff per code task; older commits go in by subject only

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

def confluence_auth(token: str, user: str = "") -> str:
    """Data Center: personal access token as Bearer. Cloud: e-mail + API token as Basic."""
    if user:
        return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
    return "Bearer " + token


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
        self.auth = confluence_auth(token, user)

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

@dataclass(frozen=True)
class RepoSpec:
    """One line of repos.txt: a local clone, or a URL cloned into the workshop; refs to follow."""
    path: Path
    url: str = ""
    refs: tuple[str, ...] = ()


_URL = re.compile(r"^(\w+://|[\w.-]+@[\w.-]+:)")
_REFS = re.compile(r"\s@\s*(.+)$")


def _remote_ref(repo: Path, ref: str, run) -> str:
    """The freshest copy of a branch: origin's after a fetch, else the name as given."""
    remote = f"refs/remotes/origin/{ref}"
    proc = run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", remote],
               capture_output=True, text=True)
    return remote if proc.returncode == 0 else ref


def _all_branches(repo: Path, run) -> list[str]:
    """Every local and remote branch by its full name, skipping aliases such as origin/HEAD."""
    proc = run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname)%09%(symref)",
                "refs/heads", "refs/remotes"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ["HEAD"]
    refs = []
    for line in proc.stdout.splitlines():
        name, _, alias = line.partition("\t")
        if name and not alias:
            refs.append(name)
    return refs or ["HEAD"]


def _branch(source: str) -> str:
    for prefix in ("refs/remotes/origin/", "refs/remotes/", "refs/heads/", "refs/tags/"):
        if source.startswith(prefix):
            return source[len(prefix):]
    return source


def git_commits(repo: Path, since: str, refs: tuple[str, ...] = (), run=subprocess.run) -> list[dict]:
    """Commits since a date: of HEAD, of the given branches, or of every branch with ("*",)."""
    if "*" in refs:
        revs = _all_branches(repo, run)
    else:
        revs = [_remote_ref(repo, r, run) for r in refs] or ["HEAD"]
    proc = run(["git", "-C", str(repo), "log", *revs, "--source", f"--since={since}", "--no-merges",
                "--name-only", "--format=%x1e%H%x1f%an%x1f%aI%x1f%S%x1f%s"], capture_output=True, text=True,
               encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(i18n.t("err_git", repo=repo, error=(proc.stderr or "").strip()[-300:]))
    commits = []
    for record in proc.stdout.split("\x1e")[1:]:
        head, _, files = record.partition("\n")
        sha, by, when, source, subject = head.split("\x1f", 4)
        commits.append({"repo": Path(repo).name, "hash": sha, "by": by, "when": when, "subject": subject,
                        "branch": _branch(source), "files": [f.strip() for f in files.splitlines() if f.strip()]})
    return commits


def git_diff(repo: Path, sha: str, run=subprocess.run) -> str:
    """The commit's patch, cut to MAX_DIFF characters."""
    proc = run(["git", "-C", str(repo), "show", "--format=", "--no-color", "--unified=3", sha],
               capture_output=True, text=True, encoding="utf-8", errors="replace")
    diff = (proc.stdout or "").strip() if proc.returncode == 0 else ""
    return diff if len(diff) <= MAX_DIFF else diff[:MAX_DIFF] + "\n" + i18n.t("cut")


def sync_repo(spec: RepoSpec, run=subprocess.run) -> str | None:
    """Clones a URL line the first time and fetches it after; a local clone is left alone."""
    if not spec.url:
        return None
    if (spec.path / ".git").is_dir():
        cmd, done = ["git", "-C", str(spec.path), "fetch", "--all", "--prune", "--quiet"], "fetch"
    else:
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        cmd, done = ["git", "clone", "--quiet", spec.url, str(spec.path)], "clone"
    # Never wait for a password: a scheduled run has nobody to type it.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    proc = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip()[-300:])
    return done


def affected_pages(commit: dict, pages: list[Page]) -> list[str]:
    """Pages that mention the repo or a touched file: their text may now be stale."""
    names = {commit["repo"].lower()}
    for f in commit["files"]:
        name = Path(f).name.lower()
        if len(Path(name).stem) >= 5:
            names |= {name, Path(name).stem}
    # A name that many pages cite (README, package, LICENSE...) says nothing about which page is stale.
    limit = max(3, len(pages) // 20)
    hits: dict[str, None] = {}
    for n in names:
        titles = _citing(n, pages)
        if len(titles) <= limit:
            hits.update(dict.fromkeys(titles))
    return list(dict.fromkeys(p.title for p in pages if p.title in hits))


_CITES: dict[tuple[int, str], tuple[list[Page], list[str]]] = {}


def _citing(name: str, pages: list[Page]) -> list[str]:
    """Pages whose text names it as a whole word; cached per page list, as every commit asks again."""
    key = (id(pages), name)
    if key not in _CITES:
        pattern = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
        # Keeping the list alive stops another list from reusing its id.
        _CITES[key] = (pages, [p.title for p in pages if pattern.search(p.markdown.lower())])
    return _CITES[key][1]


def read_repos(root: Path) -> list[RepoSpec]:
    """repos.txt: one repo per line, a path or a URL, optionally "@ branch, branch" or "@ *"."""
    path = root / i18n.name("repos")
    if not path.is_file():
        return []
    specs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        refs: tuple[str, ...] = ()
        m = _REFS.search(line)
        if m:
            refs = tuple(r.strip() for r in m.group(1).split(",") if r.strip())
            line = line[:m.start()].strip()
        if _URL.match(line):
            name = re.sub(r"\.git$", "", line.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
            specs.append(RepoSpec(root / i18n.name("repos_dir") / name, line, refs))
        else:
            specs.append(RepoSpec(Path(line).expanduser(), "", refs))
    return specs


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


def _code_tasks(out: Path, fresh: list, pages: list[Page], template, bible: str, run) -> list[str]:
    """One task per page that new commits touch, with those commits and their diffs."""
    by_page: dict[str, list] = {}
    for spec, entry in fresh:
        for title in entry["pages"]:
            by_page.setdefault(title, []).append((spec, entry))
    by_title = {p.title: p for p in pages}
    n = i18n.name
    made = []
    for title, hits in by_page.items():
        page = by_title[title]
        slug = f"{_slug(title)}-{_id('codigo', title, *(e['hash'] for _, e in hits))[:6]}"
        rel = f"{n('code_dir')}/{slug}"
        commits = _commit_digest(sorted(hits, key=lambda h: h[1]["when"], reverse=True), run)
        local = i18n.t("code_local", title=title, commits=commits)
        d = out / rel
        d.mkdir(parents=True, exist_ok=True)
        task = kit.Task(slug, "update", title, n("repos"), page)
        (d / n("local_copy")).write_text(local, encoding="utf-8")
        (d / n("current")).write_text(page.markdown, encoding="utf-8")
        (d / n("task")).write_text(kit._prompt(task, local, template, bible), encoding="utf-8")
        for _, e in hits:
            e["tasks"].append(rel)
            e.setdefault("task_pages", {})[rel] = title
        made.append(rel)
    return made


def code_task_pages(entry: dict) -> dict[str, str]:
    """{task folder: page} of a commit.

    Older logs only kept two lists that do not line up, so the page is read back from the
    folder name, which is the page's slug plus a short hash."""
    if entry.get("task_pages"):
        return entry["task_pages"]
    by_slug = {_slug(title): title for title in entry.get("pages", [])}
    found = {rel: by_slug.get(Path(rel).name.rsplit("-", 1)[0], "") for rel in entry.get("tasks", [])}
    return {rel: title for rel, title in found.items() if title}


TRIAGE_FILE = "TRIAJE.json"
CATEGORIES = ("actualizar", "encadenar", "ruido", "dudosa")
MAX_TRIAGE_CHARS = 16000  # commits
MAX_TRIAGE_PAGE = 30000
COMMIT_LINE = re.compile(r"^(#+|-) \S+ · \S+ · [0-9a-f]{7,} · ")


def triage_code_task(task_dir: Path, title: str, ai: Ai) -> dict:
    """Asks the AI whether the commits make the page wrong; the verdict is kept in TRIAJE.json."""
    n = i18n.name
    current = (task_dir / n("current")).read_text(encoding="utf-8")
    if len(current) <= MAX_TRIAGE_PAGE:
        page_text = current
    else:  # a long page: every heading, then as much of the text as fits
        headings = "\n".join(line for line in current.splitlines() if line.startswith("#"))
        page_text = headings + "\n\n" + current[:max(0, MAX_TRIAGE_PAGE - len(headings))]
    local = (task_dir / n("local_copy")).read_text(encoding="utf-8")
    # Every commit by subject first, so an old one never falls off; then the diffs that fit.
    lines = local.splitlines()
    subjects = "\n".join(  # a commit with its diff has the subject on the next line that has text
        line if line.startswith("-") else f"{line}: {next((x for x in lines[i + 1:] if x.strip()), '')}"
        for i, line in enumerate(lines) if COMMIT_LINE.match(line))
    commits = subjects + "\n\n" + local[:MAX_TRIAGE_CHARS]
    data = _json_object(ai(i18n.t("triage_prompt", title=title, page=page_text, commits=commits)))
    category = str(data.get("categoria") or data.get("category") or "").strip().lower()
    changes = data.get("cambios") or data.get("changes") or []
    return {"categoria": category if category in CATEGORIES else "dudosa",
            "motivo": str(data.get("motivo") or data.get("reason") or "").strip(),
            "cambios": [str(c) for c in changes] if isinstance(changes, list) else [str(changes)]}


def _solve_side(out: Path, entries: list[dict], by_title: dict, ai: Ai, template, bible: str,
                errors: list[str]) -> None:
    """Writes the AI's proposal for request tasks, then triages code tasks and solves the real ones."""
    n = i18n.name

    def attempt(rel: str, write) -> None:
        try:
            write()
        except Exception as exc:  # one failing task must not stop the rest
            errors.append(f"{rel}: {exc}")

    proposals: dict[str, str] = {}
    for e in entries:
        if e["kind"] != "peticion" or not e.get("task") or e["page"] not in by_title:
            continue
        d, page = out / e["task"], by_title[e["page"]]
        result = d / n("result")
        if not result.exists():
            prompt = (d / n("task")).read_text(encoding="utf-8")
            attempt(e["task"], lambda: result.write_text(kit.solve(prompt, page.markdown, ai), encoding="utf-8"))
        if result.exists():
            proposals[e["page"]] = result.read_text(encoding="utf-8")

    for e in entries:
        if e["kind"] != "codigo":
            continue
        for rel, title in code_task_pages(e).items():
            d = out / rel
            if title not in by_title or not d.is_dir() or (d / n("result")).exists():
                continue
            verdict_file = d / TRIAGE_FILE
            if not verdict_file.exists():
                def triage(d=d, title=title, verdict_file=verdict_file):
                    verdict = triage_code_task(d, title, ai)
                    if verdict["categoria"] == "actualizar" and title in proposals:
                        verdict["categoria"] = "encadenar"
                    verdict_file.write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
                attempt(rel, triage)
                if not verdict_file.exists():
                    continue
            verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
            if verdict["categoria"] not in ("actualizar", "encadenar"):
                continue
            base = proposals.get(title, by_title[title].markdown) if verdict["categoria"] == "encadenar" \
                else by_title[title].markdown
            local = i18n.t("code_triaged", title=title, reason=verdict["motivo"],
                           changes="\n".join(f"- {c}" for c in verdict["cambios"]))
            prompt = kit._prompt(kit.Task(d.name, "update", title, n("repos"), Page(title, base)),
                                 local, template, bible)
            (d / n("task")).write_text(prompt, encoding="utf-8")
            attempt(rel, lambda d=d, prompt=prompt, base=base:
                    (d / n("result")).write_text(kit.solve(prompt, base, ai), encoding="utf-8"))


def _commit_digest(hits: list, run) -> str:
    """Newest commits with their diff while they fit in MAX_TASK_DIFF; the older ones as a list."""
    parts, rest, budget = [], [], MAX_TASK_DIFF
    for spec, e in hits:
        diff = git_diff(spec.path, e["hash"], run) if budget > 0 else ""
        if diff and len(diff) <= budget:
            budget -= len(diff)
            parts.append(i18n.t("code_commit", repo=e["repo"], branch=e["branch"], sha=e["hash"][:10],
                                by=e["by"], subject=e["what"], diff=diff))
        else:
            budget = 0
            rest.append(i18n.t("code_commit_line", repo=e["repo"], branch=e["branch"], sha=e["hash"][:10],
                               by=e["by"], subject=e["what"]))
    if rest:
        parts.append(i18n.t("code_older", n=len(rest)) + "\n\n" + "\n".join(rest) + "\n")
    return "\n".join(parts)


# ── The log ───────────────────────────────────────────────────────────────────

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))  # survives a Notepad edit
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user() -> str:
    return settings.value("user")  # AMANUENSE_USER > settings.json > USERNAME/USER


_USERINFO = re.compile(r"(?<=://)[^/\s@]*@")


def scrub_url(text: str) -> str:
    """The text without `user:password@` / `user@` in its URLs: the log is served without a token."""
    return _USERINFO.sub("", str(text))


def update_log(root: Path, exports: list[Path], pages: list[Page], ready: dict[str, kit.Task],
               history: ConfluenceHistory | None = None, router: Ai | None = None,
               template=None, bible: str = "", run=subprocess.run, ai: Ai | None = None,
               created: str | None = None, source: str = "export", sync_repos: bool = True) -> dict:
    """Adds this run's changes to the log; returns {"entries", "request_tasks", "errors"}.

    `created` is the baseline of `pages` (a live read's fetch time; by default, the export's
    date). Pages are only diffed against a snapshot from the same `source`: a live read and a
    Word export format the same page differently. Without `sync_repos`, the repos are read as
    last fetched and the ones never cloned are skipped."""
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
    created = created or max((export_created(e) for e in exports), default="") or _now()
    snap = _load(out / n("snapshot"), None)
    current = {p.title: p.markdown for p in pages}
    same_source = bool(snap) and snap.get("source", "export") == source
    if pages and snap and same_source and snap["pages"] != current:
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
    fresher = source != "export" and bool(snap) and snap.get("created") != created
    if pages and (not snap or snap["pages"] != current or not same_source or fresher):
        (out / n("snapshot")).write_text(json.dumps({"created": created, "pages": current, "source": source},
                                                    ensure_ascii=False), encoding="utf-8")

    # Code: commits since the previous export (or a lookback window the first time).
    since = snap["created"] if snap else (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    fresh: list[dict] = []
    for spec in read_repos(root):
        if not sync_repos and not spec.path.is_dir():
            continue
        try:
            if sync_repos:
                sync_repo(spec, run)
        except Exception as exc:  # offline: keep reading what was fetched before
            errors.append(scrub_url(i18n.t("err_sync", repo=spec.url, error=exc)))
        try:
            commits = git_commits(spec.path, since, spec.refs, run)
        except Exception as exc:
            errors.append(scrub_url(f"git ({spec.path}): {exc}"))
            continue
        for c in commits:
            entry = {"id": _id("codigo", c["hash"]), "kind": "codigo", "when": c["when"], "by": c["by"],
                     "page": "", "repo": c["repo"], "branch": c["branch"], "what": c["subject"],
                     "hash": c["hash"], "files": c["files"], "pages": affected_pages(c, pages), "tasks": []}
            if entry["id"] not in known:
                fresh.append((spec, entry))
            add(entry)
    code_tasks = _code_tasks(out, fresh, pages, template, bible, run)

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

    if ai:
        _solve_side(out, entries, by_title, ai, template, bible, errors)

    # Workshop: proposals that are ready, from page tasks and request tasks.
    request_tasks = {e["task"]: e for e in entries if e["kind"] == "peticion" and e.get("task")}
    side_tasks = {rel: e["page"] for rel, e in request_tasks.items()}
    side_tasks.update({rel: title for e in entries if e["kind"] == "codigo"
                       for rel, title in code_task_pages(e).items()})
    for rel, title in side_tasks.items():
        task = kit.Task(Path(rel).name, "update", title, n("requests"), by_title.get(title))
        if (out / rel).is_dir() and kit._publish(out / rel, task) is not None:
            ready[rel] = task
    for rel, task in ready.items():
        result = (out / rel / n("result")).read_text(encoding="utf-8")
        add({"id": _id("taller", rel, result), "kind": "taller", "when": _now(), "by": _user(),
             "page": task.title, "what": i18n.t("proposal_ready"), "task": rel})

    (out / n("log_json")).write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / n("log_html")).write_text(render_log(entries, errors), encoding="utf-8")
    return {"entries": entries, "request_tasks": sorted(request_tasks), "code_tasks": code_tasks,
            "errors": errors}


def _label(prefix: str, value: str) -> str:
    key = f"{prefix}_{value}"
    return i18n.t(key) if key in i18n.TEXT else value


def _detail(e: dict) -> str:
    esc, n, t = html.escape, i18n.name, i18n.t
    if e["kind"] == "confluence":
        msg = f"<p>{t('quote', text=esc(e['message']))}</p>" if e.get("message") else ""
        return f"{esc(_label('change', e['change']))}{msg}<pre>{esc(e['what'])}</pre>"
    if e["kind"] == "codigo":
        tasks = dict(zip(e.get("pages", []), e.get("tasks", [])))
        links = [f'<a href="{esc(tasks[p])}/{n("task")}">{esc(p)}</a>' if p in tasks else esc(p)
                 for p in e.get("pages", [])]
        pages = f"<p><b>{t('review')}</b> {', '.join(links)}</p>" if links else ""
        where = f"{e['repo']} · {e['branch']}" if e.get("branch") else e["repo"]
        return f"{esc(where)}: {esc(e['what'])}<br><small>{esc(', '.join(e['files'][:6]))}</small>{pages}"
    if e["kind"] == "peticion":
        if not e.get("page"):
            return f"{t('quote', text=esc(e['request']))}<p>{t('no_page')}</p>"
        return (f"{t('quote', text=esc(e['request']))}<p><b>{t('what')}</b> {esc(e['cambio'])}<br><b>{t('why')}</b> "
                f"{esc(e['motivo'])}</p><a href=\"{esc(e['task'])}/{n('task')}\">{n('task')}</a>")
    return f'{esc(e["what"])} · <a href="{esc(e["task"])}/{n("changes")}">{n("changes")}</a>'


def render_log(entries: list[dict], errors: list[str] | None = None) -> str:
    t = i18n.t
    rows = []
    for e in sorted(entries, key=lambda e: e["when"], reverse=True):
        rows.append(f"<tr><td>{html.escape(e['when'][:16].replace('T', ' '))}</td>"
                    f"<td>{_label('kind', e['kind'])}</td><td>{html.escape(e['by'])}</td>"
                    f"<td>{html.escape(e.get('page') or '')}</td><td>{_detail(e)}</td></tr>")
    warn = (f"<p><b>{t('log_warnings')}</b></p><ul>" + "".join(f"<li>{html.escape(scrub_url(x))}</li>" for x in errors)
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
