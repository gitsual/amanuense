"""
revision — what a reviewer sees and decides before anything reaches Confluence.

One proposal per page (the task that carries the most: chained > request > code > page),
its origin, its notices and a review state kept in output/estado.json:

    pendiente → aprobada → publicada        (or descartada)

An approval is tied to the page as it was read (a hash of its current text): a newer
export puts it back to pendiente. Every action is written to the log with who did it.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import i18n
from . import registro as log
from . import taller as kit

STATE_FILE = "estado.json"
AI_COPY = ".ia.md"  # suffix of the AI's own proposal, kept the first time someone edits it
STATES = ("pendiente", "aprobada", "publicada", "descartada")


class ReviewError(ValueError):
    """An action that cannot be done now; the message is for the reviewer."""


def _out(root: Path) -> Path:
    i18n.choose(root)
    return root / i18n.name("out")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else ""


def _states(root: Path) -> dict:
    return log._load(_out(root) / STATE_FILE, {})


def _save_states(root: Path, states: dict) -> None:
    (_out(root) / STATE_FILE).write_text(json.dumps(states, ensure_ascii=False, indent=1), encoding="utf-8")


def _entries(root: Path) -> list[dict]:
    return log._load(_out(root) / i18n.name("log_json"), [])


def _record(root: Path, rel: str, page: str, by: str, what: str) -> None:
    out = _out(root)
    entries = _entries(root)
    when = log._now()
    entries.append({"id": log._id("revision", rel, what, when, str(len(entries))), "kind": "revision",
                    "when": when, "by": by, "page": page, "what": what, "task": rel})
    (out / i18n.name("log_json")).write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / i18n.name("log_html")).write_text(log.render_log(entries), encoding="utf-8")


def _verdict(out: Path, rel: str) -> dict:
    return log._load(out / rel / log.TRIAGE_FILE, {})


def _conflicts(notices: list[str]) -> list[str]:
    word = i18n.t("conflict_word")
    return [x for x in notices if re.match(r"\**" + word + r"\**\s*:", x)]


def candidates(root: Path) -> dict[str, list[str]]:
    """{page title: its ready task folders, best first}."""
    out = _out(root)
    entries = _entries(root)
    requests = {e["task"] for e in entries if e["kind"] == "peticion" and e.get("task")}
    code = {rel: title for e in entries if e["kind"] == "codigo" for rel, title in log.code_task_pages(e).items()}

    def rank(rel: str) -> int:
        if _verdict(out, rel).get("categoria") == "encadenar":
            return 0
        return 1 if rel in requests else 2 if rel in code else 3

    by_page: dict[str, list[str]] = {}
    for e in entries:
        if e["kind"] == "taller" and (out / e["task"] / i18n.name("result")).is_file():
            title = code.get(e["task"]) or e["page"]  # old logs may carry a mismatched title
            rels = by_page.setdefault(title, [])
            if e["task"] not in rels:
                rels.append(e["task"])
    return {title: sorted(rels, key=rank) for title, rels in sorted(by_page.items())}


def _origin(entries: list[dict], out: Path, rel: str, title: str) -> dict:
    requests = {e["task"]: e for e in entries if e["kind"] == "peticion" and e.get("task")}
    asked = list(dict.fromkeys(e["by"] for e in requests.values() if e["page"] == title))
    commits = [e for e in entries if e["kind"] == "codigo" and rel in log.code_task_pages(e)]
    repos = list(dict.fromkeys(f'{e.get("repo", "?")}@{e["branch"]}' if e.get("branch") else e.get("repo", "?")
                               for e in commits))
    if rel in requests:
        return {"kind": "request", "by": [requests[rel]["by"]], "repos": []}
    if commits:
        chained = _verdict(out, rel).get("categoria") == "encadenar"
        return {"kind": "chained" if chained else "code", "by": asked if chained else [], "repos": repos}
    return {"kind": "docs", "by": [], "repos": []}


def proposals(root: Path) -> list[dict]:
    out = _out(root)
    n = i18n.name
    entries = _entries(root)
    states = _states(root)
    found = []
    for title, rels in candidates(root).items():
        rel = rels[0]
        text = (out / rel / n("result")).read_text(encoding="utf-8")
        notices = kit.notices(text)
        state = states.get(title, {})
        status = state.get("status", "pendiente")
        stale = status == "aprobada" and state.get("current") != _hash(out / rel / n("current"))
        found.append({"title": title, "rel": rel, "others": rels[1:],
                      "new": not (out / rel / n("current")).is_file(),
                      "origin": _origin(entries, out, rel, title), "notices": notices,
                      "conflicts": len(_conflicts(notices)), "status": "pendiente" if stale else status,
                      "stale": stale, "published": state.get("published"), "by": state.get("by", ""),
                      "when": state.get("when", ""), "note": state.get("note", "")})
    return found


def find(root: Path, rel: str) -> dict:
    for p in proposals(root):
        if p["rel"] == rel:
            return p
    raise ReviewError(i18n.t("review_unknown", rel=rel))


def _set(root: Path, rel: str, status: str, by: str, what: str, **extra) -> dict:
    page = find(root, rel)
    states = _states(root)
    states[page["title"]] = {"status": status, "by": by, "when": log._now(), "rel": rel,
                             "current": _hash(_out(root) / rel / i18n.name("current")), **extra}
    _save_states(root, states)
    _record(root, rel, page["title"], by, what)
    return find(root, rel)


def approve(root: Path, rel: str, by: str) -> dict:
    page = find(root, rel)
    open_ = _conflicts(page["notices"])
    if open_:
        raise ReviewError(i18n.t("review_open_conflicts", n=len(open_), first=open_[0]))
    return _set(root, rel, "aprobada", by, i18n.t("review_approved"))


def discard(root: Path, rel: str, by: str, reason: str) -> dict:
    return _set(root, rel, "descartada", by, i18n.t("review_discarded", reason=reason), note=reason)


def reopen(root: Path, rel: str, by: str) -> dict:
    return _set(root, rel, "pendiente", by, i18n.t("review_reopened"))


def mark_published(root: Path, rel: str, by: str, mode: str, url: str, version: int | None, **extra) -> dict:
    """`extra` keeps what an undo needs (page_id, backup)."""
    if find(root, rel)["status"] != "aprobada":
        raise ReviewError(i18n.t("review_publish_unapproved"))
    published = {"mode": mode, "url": url, "version": version, "by": by, "when": log._now(), **extra}
    what = i18n.t("review_published_api" if mode == "api" else "review_published_manual", url=url)
    return _set(root, rel, "publicada", by, what, published=published)


def _task(root: Path, rel: str) -> kit.Task:
    """Enough of a task for _publish: it only asks whether the page exists in Confluence."""
    page = find(root, rel)
    return kit.Task(Path(rel).name, "new" if page["new"] else "update", page["title"], "",
                    None if page["new"] else kit.Page(page["title"], ""))


def save_text(root: Path, rel: str, markdown: str, by: str, what: str | None = None) -> dict:
    """Saves the reviewer's text; the AI's first proposal is kept beside it."""
    find(root, rel)  # an unknown page is refused before anything is written
    d = _out(root) / rel
    result = d / i18n.name("result")
    copy = result.with_name(result.stem + AI_COPY)
    if not copy.exists():
        copy.write_text(result.read_text(encoding="utf-8"), encoding="utf-8")
    result.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
    kit._publish(d, _task(root, rel))
    return _set(root, rel, "pendiente", by, what or i18n.t("review_edited"))


def resolve_notice(root: Path, rel: str, notice: str, decision: str, by: str) -> dict:
    find(root, rel)
    result = _out(root) / rel / i18n.name("result")
    lines = result.read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if line.strip().lstrip(">").strip() == notice]
    if len(hits) != 1:
        raise ReviewError(i18n.t("review_notice_gone"))
    lines[hits[0]] = decision.strip()
    return save_text(root, rel, "\n".join(lines) + "\n", by, i18n.t("review_decided", notice=notice,
                                                                     decision=decision.strip()))


def rework(root: Path, rel: str, instruction: str, ai, by: str) -> dict:
    """Asks the AI again: the original task, the text as it is now and the reviewer's instruction."""
    d = _out(root) / rel
    n = i18n.name
    current = (d / n("result")).read_text(encoding="utf-8")
    prompt = i18n.t("rework_prompt", task=(d / n("task")).read_text(encoding="utf-8"),
                    proposal=current, instruction=instruction.strip())
    return save_text(root, rel, kit.solve(prompt, current, ai), by,
                     i18n.t("review_reworked", instruction=instruction.strip()))


def set_aside(root: Path) -> list[dict]:
    """Code tasks the triage left out (noise, doubtful), so a person can still look at them."""
    out = _out(root)
    found = []
    for e in _entries(root):
        if e["kind"] != "codigo":
            continue
        for rel, title in log.code_task_pages(e).items():
            verdict = _verdict(out, rel)
            if verdict.get("categoria") in ("ruido", "dudosa") and not (out / rel / i18n.name("result")).exists():
                found.append({"rel": rel, "title": title, "categoria": verdict["categoria"],
                              "motivo": verdict.get("motivo", "")})
    return list({x["rel"]: x for x in found}.values())


def promote(root: Path, rel: str, by: str) -> None:
    """Sends a set-aside task back to be written: the next search solves it."""
    find_aside = [x for x in set_aside(root) if x["rel"] == rel]
    if not find_aside:
        raise ReviewError(i18n.t("review_unknown", rel=rel))
    out = _out(root)
    path = out / rel / log.TRIAGE_FILE
    verdict = log._load(path, {})
    title = find_aside[0]["title"]
    verdict.update(categoria="actualizar", motivo=i18n.t("review_promoted_reason", by=by,
                                                          before=verdict.get("motivo", "")))
    path.write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    _record(root, rel, title, by, i18n.t("review_promoted"))
