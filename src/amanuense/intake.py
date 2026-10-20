"""
intake — a messy pile of documents dropped into the review app, screened and compared.

A pile can hold ten files or thousands: copies of the same document, test results, logs,
lockfiles, images, PDFs. Before anything is compared (and before anything is uploaded),
each file is classified with the same rules on both sides of the wire:

    use         a readable document (.md, .markdown, .txt, .docx, .html, .htm)
    skip        bad_path · too_big · batch_full · noise · unsupported · pdf · empty
                · duplicate (same bytes as another file of the pile) · known (same bytes as
                a document already in the workshop)

Uploads land in the workshop's own documents folder, in a batch folder of their own
(intake-YYYYMMDD-HHMMSS/), keeping their relative folders: nothing of the user's is
overwritten. When compared, a file of a batch needs no «update instructions»: matching a
page by title (or by identical content) is enough. Several files for one page become one
task; a file identical to its page becomes nothing; files that match no page are ranked
as candidates for new pages and wait for a person to choose them, so a pile of 2,000
files never turns into 2,000 proposals.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import i18n
from . import registro as log
from .confluence import LOCAL_EXTENSIONS, LocalDoc, Page, Row, _content, normalize_title

MAX_FILE_BYTES = 25 * 1024 * 1024  # one document
MAX_BATCH_BYTES = 1024 * 1024 * 1024  # one upload
MAX_BATCH_FILES = 10_000  # documents used from one upload
MAX_PATH_PARTS = 32
MAX_PART_CHARS = 200
MAX_SOURCES = 8  # files of a pile merged into one page's task
CANDIDATES_SHOWN = 50  # unmatched files the app lists; the report lists all

BATCH_PREFIX = "intake-"
BATCH = re.compile(r"^intake-\d{8}-\d{6}(-\d{1,4})?$")
PROMOTED_FILE = "intake-promoted.json"
SUMMARY_FILE = "intake.json"
SKIP_REASONS = ("bad_path", "too_big", "batch_full", "noise", "unsupported", "pdf", "empty", "duplicate", "known")
READABLE = sorted(LOCAL_EXTENSIONS)

# gitignore-like: «name/» is any folder of that name, a pattern with «/» matches the path,
# any other matches the file name; «!» brings a file back; the last match wins.
DEFAULT_NOISE = [
    ".git/", ".svn/", ".hg/", "node_modules/", "__pycache__/", ".venv/", "venv/", ".tox/", ".idea/", ".vscode/",
    "dist/", "build/", "target/", "bin/", "obj/", "coverage/", "htmlcov/", ".pytest_cache/",
    "test-results/", "test-reports/", "logs/", "log/", "generated/",
    "*.log", "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
    "composer.lock", "Gemfile.lock", "go.sum", "*.min.js", "*.map",
    "*test-results*", "*test-report*", "*test-output*", "junit*.xml", "*.trx", "*coverage*.xml",
    "*.generated.*", "*.tmp", "*.bak", "*.swp", "~$*", ".DS_Store", "Thumbs.db", "desktop.ini",
]
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
GENERIC_TITLE = re.compile(r"^(readme|notes?|untitled|draft|copy( of)?|new document|document ?\d*|index|temp|test|"
                           r"sin titulo|nota|notas|borrador|copia( de)?|documento ?\d*)\b", re.IGNORECASE)


class IntakeError(ValueError):
    """An upload that cannot be stored; the message is for the person uploading."""


class PathError(IntakeError):
    """A file path that could escape its batch folder."""


class TooBig(IntakeError):
    """A file or a batch over its limit."""


# ── Paths ──────────────────────────────────────────────────────────────────────

def safe_relpath(raw: str) -> str:
    """A browser's file path as a safe relative path: separators normalised, drive letters and
    leading slashes dropped, «.» removed; «..», control characters and absurd depths refused;
    characters Windows cannot store replaced and its reserved names escaped."""
    if not isinstance(raw, str) or not raw.strip():
        raise PathError(i18n.t("intake_bad_path", path=str(raw)[:80]))
    if any(ord(c) < 32 for c in raw):
        raise PathError(i18n.t("intake_bad_path", path=raw.encode("unicode_escape").decode()[:80]))
    text = unicodedata.normalize("NFC", raw.replace("\\", "/"))
    text = re.sub(r"^[A-Za-z]:", "", text)
    parts = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathError(i18n.t("intake_bad_path", path=raw[:80]))
        part = re.sub(r'[<>:"|?*]', "_", part).rstrip(" .")
        if not part:
            continue
        if part.split(".")[0].upper() in RESERVED:
            part = "_" + part
        parts.append(part[:MAX_PART_CHARS])
    if not parts or len(parts) > MAX_PATH_PARTS:
        raise PathError(i18n.t("intake_bad_path", path=raw[:80]))
    return "/".join(parts)


def is_intake(rel: str) -> bool:
    """Whether a document of the workshop came in an upload batch."""
    return bool(rel) and rel.split("/", 1)[0].startswith(BATCH_PREFIX)


# ── Noise ──────────────────────────────────────────────────────────────────────

def ignore_file(root: Path) -> Path:
    return root / i18n.name("intake_ignore")


def ensure_ignore_file(root: Path) -> Path:
    path = ignore_file(root)
    if not path.exists():
        path.write_text(i18n.t("intake_ignore_text"), encoding="utf-8")
    return path


def noise_patterns(root: Path | None) -> list[str]:
    extra = []
    if root is not None and ignore_file(root).is_file():
        for line in ignore_file(root).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                extra.append(line)
    return DEFAULT_NOISE + extra


def _matches(pattern: str, rel: str) -> bool:
    p, path = pattern.replace("\\", "/").lower(), rel.lower()
    parts = path.split("/")
    if p.endswith("/"):
        return any(fnmatch.fnmatchcase(part, p.rstrip("/")) for part in parts[:-1])
    if "/" in p:
        p = p.lstrip("/")
        return fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, "*/" + p)
    return fnmatch.fnmatchcase(parts[-1], p)


def noise(rel: str, patterns: list[str]) -> str | None:
    """The pattern that marks the file as noise, or None."""
    hit = None
    for pattern in patterns:
        if pattern.startswith("!"):
            if _matches(pattern[1:], rel):
                hit = None
        elif _matches(pattern, rel):
            hit = pattern
    return hit


def kind_of(rel: str) -> str:
    suffix = PurePosixPath(rel).suffix.lower()
    return suffix.lstrip(".") or "—"


def _type_reason(rel: str) -> str:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in LOCAL_EXTENSIONS:
        return ""
    return "pdf" if suffix == ".pdf" else "unsupported"


COPY_NAME = re.compile(r"(\bcopy\b|\bcopia\b|\(\d+\)$|[ _-]\d+$|\bbackup\b|\bold\b|\bv\d+$|~$)", re.IGNORECASE)


def _keeper(rel: str) -> tuple:
    """Order in which identical files are kept: the one that does not look like a copy wins."""
    stem = PurePosixPath(rel).stem
    return (bool(COPY_NAME.search(stem)), rel.count("/"), len(stem), rel)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def known_hashes(local_root: Path) -> dict[str, str]:
    """sha256 → path of every readable document already in the workshop's own folder."""
    found: dict[str, str] = {}
    if local_root.is_dir():
        for p in sorted(local_root.rglob("*")):
            if p.is_file() and p.suffix.lower() in LOCAL_EXTENSIONS:
                found.setdefault(_sha_file(p), p.relative_to(local_root).as_posix())
    return found


# ── The plan shown before uploading ─────────────────────────────────────────────

def plan(root: Path, files: list[dict]) -> dict:
    """What would be used and what skipped, and why; `files` are {path, size, sha256}."""
    ensure_ignore_file(root)
    patterns = noise_patterns(root)
    known = known_hashes(root / i18n.name("local"))
    seen: dict[str, str] = {}
    used_bytes = used_files = 0
    items = []
    for f in files:
        raw = str(f.get("path", ""))
        item = {"path": raw, "size": int(f.get("size") or 0), "kind": kind_of(raw), "status": "skip", "reason": "",
                "detail": "", "sha": str(f.get("sha256") or "").lower()}
        try:
            item["path"] = safe_relpath(raw)
        except PathError:
            item["reason"] = "bad_path"
        items.append(item)
    for item in sorted((i for i in items if not i["reason"]), key=lambda i: _keeper(i["path"])):
        rel, size, sha = item["path"], item["size"], item["sha"]
        hit = noise(rel, patterns)
        reason = "noise" if hit else _type_reason(rel)
        if hit:
            item["detail"] = hit
        elif not reason and size > MAX_FILE_BYTES:
            reason = "too_big"
        elif not reason and size == 0:
            reason = "empty"
        elif not reason and sha and sha in seen:
            reason, item["detail"] = "duplicate", seen[sha]
        elif not reason and sha and sha in known:
            reason, item["detail"] = "known", known[sha]
        elif not reason and (used_bytes + size > MAX_BATCH_BYTES or used_files + 1 > MAX_BATCH_FILES):
            reason = "batch_full"
        if reason:
            item["reason"] = reason
            continue
        if sha:
            seen[sha] = rel
        item["status"] = "use"
        used_bytes += size
        used_files += 1
    for item in items:
        del item["sha"]
    skipped = [i for i in items if i["status"] == "skip"]
    return {"items": items, "totals": {
        "files": len(items), "use": used_files, "skip": len(skipped), "use_bytes": used_bytes,
        "bytes": sum(i["size"] for i in items),
        "reasons": {r: sum(i["reason"] == r for i in skipped) for r in SKIP_REASONS if any(i["reason"] == r for i in skipped)}}}


# ── Storing an upload ───────────────────────────────────────────────────────────

def new_batch(root: Path, now: str | None = None) -> str:
    """Creates intake-YYYYMMDD-HHMMSS/ (with a suffix if taken) in the documents folder."""
    when = datetime.fromisoformat(now) if now else datetime.now(timezone.utc).astimezone()
    base = BATCH_PREFIX + when.strftime("%Y%m%d-%H%M%S")
    local = root / i18n.name("local")
    local.mkdir(parents=True, exist_ok=True)
    name, n = base, 2
    while True:
        try:
            (local / name).mkdir()
            return name
        except FileExistsError:
            name, n = f"{base}-{n}", n + 1


def batch_dir(root: Path, batch: str) -> Path:
    if not isinstance(batch, str) or not BATCH.match(batch):
        raise IntakeError(i18n.t("intake_bad_batch"))
    folder = root / i18n.name("local") / batch
    if not folder.is_dir():
        raise IntakeError(i18n.t("intake_bad_batch"))
    return folder


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        other = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not other.exists():
            return other
        n += 1


class Ledger:
    """Writes uploads into their batch, keeping each batch under its byte limit across threads."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.used: dict[str, int] = {}

    def _used(self, batch: str, folder: Path) -> int:
        if batch not in self.used:  # a batch started before a restart: count what it holds
            self.used[batch] = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        return self.used[batch]

    def store(self, batch: str, raw_path: str, stream, length: int, sha: str = "") -> str:
        """Copies `length` bytes of `stream` to the batch; returns the path inside the documents folder."""
        folder = batch_dir(self.root, batch)
        rel = safe_relpath(raw_path)
        if _type_reason(rel):
            raise IntakeError(i18n.t("intake_unsupported", path=rel))
        if length > MAX_FILE_BYTES:
            raise TooBig(i18n.t("intake_file_too_big", path=rel, mb=MAX_FILE_BYTES // (1024 * 1024)))
        reserved = created = False
        tmp = None
        try:
            with self.lock:
                if self._used(batch, folder) + length > MAX_BATCH_BYTES:
                    raise TooBig(i18n.t("intake_batch_too_big", mb=MAX_BATCH_BYTES // (1024 * 1024)))
                self.used[batch] += length  # reserved now, so parallel uploads cannot overshoot
                reserved = True
                target = _free(folder / rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=False)  # claims the name for this upload (and only ours is removed)
                created = True
            if not target.resolve().is_relative_to(folder.resolve()):
                raise PathError(i18n.t("intake_bad_path", path=rel))
            tmp = target.with_name(target.name + ".part")
            h, left = hashlib.sha256(), length
            with tmp.open("wb") as out:
                while left > 0:
                    chunk = stream.read(min(left, 1 << 16))
                    if not chunk:
                        raise IntakeError(i18n.t("intake_incomplete", path=rel))
                    h.update(chunk)
                    out.write(chunk)
                    left -= len(chunk)
            if sha and h.hexdigest() != sha.lower():
                raise IntakeError(i18n.t("intake_hash_mismatch", path=rel))
            os.replace(tmp, target)
        except BaseException:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            if created:
                target.unlink(missing_ok=True)
            if reserved:
                with self.lock:
                    self.used[batch] -= length
            raise
        return target.relative_to(self.root / i18n.name("local")).as_posix()


# ── Screening the documents folder before a comparison ─────────────────────────

def _blank(path: Path) -> bool:
    if path.stat().st_size == 0:
        return True
    if path.suffix.lower() in (".md", ".markdown", ".txt"):
        return not path.read_bytes().strip()
    return False


def screen(local_root: Path, patterns: list[str]) -> tuple[set[str], list[dict]]:
    """Files of the upload batches that are not compared, and why; the old documents are untouched."""
    if not local_root.is_dir():
        return set(), []
    files = sorted(p for p in local_root.rglob("*") if p.is_file() and not p.name.endswith(".part"))
    seen: dict[str, str] = {}
    for p in files:  # the user's own documents win over a copy that came in a pile
        rel = p.relative_to(local_root).as_posix()
        if not is_intake(rel) and p.suffix.lower() in LOCAL_EXTENSIONS:
            seen.setdefault(_sha_file(p), rel)
    skip, skipped = set(), []
    piled = [p.relative_to(local_root).as_posix() for p in files]
    for rel in sorted((r for r in piled if is_intake(r)), key=lambda r: (r.split("/", 1)[0], _keeper(r))):
        p = local_root / rel
        inner = rel.split("/", 1)[1] if "/" in rel else rel
        hit = noise(inner, patterns)
        reason, detail = ("noise", hit) if hit else (_type_reason(rel), "")
        if not reason and _blank(p):
            reason = "empty"
        if not reason:
            sha = _sha_file(p)
            if sha in seen:
                reason, detail = "duplicate", seen[sha]
            else:
                seen[sha] = rel
        if reason:
            skip.add(rel)
            skipped.append({"rel": rel, "reason": reason, "detail": detail})
    return skip, skipped


# ── What a pile means for the comparison ───────────────────────────────────────

def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def score(doc: LocalDoc) -> float:
    """How much a file looks like a page of its own: words, structure, a real title."""
    words = len(doc.body.split())
    headings = len(re.findall(r"^#{1,6}\s", doc.body, re.MULTILINE))
    value = min(words, 1500) / 25 + min(headings, 10) * 3
    value += 15 if normalize_title(doc.title) != normalize_title(PurePosixPath(doc.rel).stem) else 0  # a real title
    value -= 25 if words < 40 else 0
    value -= 15 if GENERIC_TITLE.match(normalize_title(doc.title)) else 0
    return round(value, 1)


def promoted(root: Path) -> list[str]:
    return log._load(root / i18n.name("out") / PROMOTED_FILE, [])


def promote(root: Path, rel: str) -> list[str]:
    """A file that matched no page goes to be written as a new page on the next comparison."""
    local = root / i18n.name("local")
    path = (local / rel).resolve()
    if not is_intake(rel) or ".." in rel.split("/") or not path.is_relative_to(local.resolve()) or not path.is_file():
        raise IntakeError(i18n.t("intake_unknown_file", rel=rel))
    chosen = promoted(root)
    if rel not in chosen:
        chosen.append(rel)
    out = root / i18n.name("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / PROMOTED_FILE).write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    return chosen


MARKER = re.compile(r"⟦[^⟧]*⟧")


def adjust(rows: list[Row], pages: list[Page], local: list[LocalDoc], chosen: set[str]) -> tuple[list[Row], set[str]]:
    """The pile's rules on top of compare(): returns the rows and the files that are new material.
    A page's Confluence-only markers do not count when telling whether a file says the same."""
    page_text = {p.title: _norm(MARKER.sub("", _content(p.markdown))) for p in pages}
    by_text = {text: title for title, text in page_text.items() if text}
    docs = {d.rel: d for d in local}
    material: set[str] = set()
    out = []
    for r in rows:
        d = docs.get(r.local)
        if not r.local or not is_intake(r.local) or d is None or d.has_update_instructions:
            out.append(r)
            continue
        body = _norm(d.body)
        if r.kind in ("same_title_no_instructions", "similar_content"):
            target = r.title if r.kind == "same_title_no_instructions" else r.match
            if body == page_text.get(target):
                out.append(Row("intake_identical", target, r.local, target))
            else:
                material.add(r.local)
                out.append(Row("update" if r.kind == "same_title_no_instructions" else "update_by_content",
                               r.title, r.local, r.match, r.score, r.detail))
        elif r.kind == "new":
            if body and body in by_text:
                out.append(Row("intake_identical", by_text[body], r.local, by_text[body]))
            elif r.local in chosen:
                out.append(r)
            else:
                out.append(Row("intake_unmatched", r.title, r.local))
        else:
            out.append(r)
    return out, material


def write_summary(root: Path, rows: list[Row], local: list[LocalDoc], skipped: list[dict], source: dict) -> dict:
    """output/intake.json: what each batch brought, for the app and for the next person."""
    docs = {d.rel: d for d in local}
    batches: dict[str, dict] = {}

    def count(rel: str, key: str) -> None:
        b = batches.setdefault(rel.split("/", 1)[0], {"used": 0, "skipped": 0, "updates": 0, "identical": 0,
                                                      "unmatched": 0, "new": 0})
        b[key] += 1

    local_root = root / i18n.name("local")
    for folder in sorted(local_root.glob(BATCH_PREFIX + "*")) if local_root.is_dir() else []:
        if folder.is_dir():
            batches.setdefault(folder.name, {"used": 0, "skipped": 0, "updates": 0, "identical": 0, "unmatched": 0,
                                             "new": 0})
    for rel in docs:
        if is_intake(rel):
            count(rel, "used")
    for s in skipped:
        count(s["rel"], "skipped")
    updates: dict[str, list[str]] = {}
    identical, unmatched = [], []
    for r in rows:
        if not r.local or not is_intake(r.local):
            continue
        if r.kind in ("update", "update_by_content"):
            title = r.match if r.kind == "update_by_content" else r.title
            updates.setdefault(title, []).append(r.local)
        elif r.kind == "intake_identical":
            identical.append({"rel": r.local, "title": r.title})
            count(r.local, "identical")
        elif r.kind == "intake_unmatched":
            unmatched.append({"rel": r.local, "title": r.title, "words": len(docs[r.local].body.split()),
                              "score": score(docs[r.local])})
            count(r.local, "unmatched")
        elif r.kind == "new":
            count(r.local, "new")
    for title, rels in updates.items():
        for rel in {rel.split("/", 1)[0]: rel for rel in rels}.values():
            count(rel, "updates")
    unmatched.sort(key=lambda u: (-u["score"], u["title"].casefold()))
    for b in batches.values():
        b["files"] = b["used"] + b["skipped"]
    data = {"when": log._now(), "source": source, "batches": batches, "skipped": skipped,
            "updates": [{"title": t, "rels": r} for t, r in sorted(updates.items())], "identical": identical,
            "unmatched": unmatched, "promoted": promoted(root)}
    out = root / i18n.name("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / SUMMARY_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load_summary(root: Path, shown: int = CANDIDATES_SHOWN) -> dict:
    """The summary for the app: the best candidates only, and how many there are."""
    data = log._load(root / i18n.name("out") / SUMMARY_FILE, {})
    if not data:
        return {}
    unmatched = data.get("unmatched", [])
    return {**data, "unmatched": unmatched[:shown], "unmatched_total": len(unmatched),
            "skipped": data.get("skipped", [])[:200], "skipped_total": len(data.get("skipped", []))}
