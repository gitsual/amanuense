#!/usr/bin/env python3
"""
amanuense — taller para reescribir y actualizar páginas de Confluence. No destructivo.

Un espacio de trabajo con tres carpetas de entrada y una de salida:

  1-export-confluence/  el «Export to Word» de la sección (página + hijos)
  2-mi-documentacion/   la carpeta propia: páginas nuevas y páginas viejas con
                        «Instrucciones de actualización» (.md, .txt o .docx)
  3-biblia/             documentos de referencia que toda página debe respetar
  salida/               informe, una carpeta de tarea por página y un index.html

Cada tarea trae un TAREA.md listo para dárselo a cualquier IA (pegarlo en un chat,
o que un agente lo lea). La respuesta se guarda como RESULTADO.md en la misma
carpeta; al volver a ejecutar, cada RESULTADO.md se convierte en
PARA-CONFLUENCE.html (abrir, copiar y pegar en Confluence) y CAMBIOS.html
(lo que cambia respecto a la página actual). Con --ai-url, el propio taller pide
los RESULTADO.md que falten a una API compatible con OpenAI (Ollama, LM Studio...).

Sólo usa la biblioteca estándar; --content y --contradictions necesitan el RAG.
Nunca escribe en las carpetas de entrada ni pisa un RESULTADO.md existente.

Uso:
  amanuense init CARPETA
  amanuense obsidian EXPORT.docx VAULT/MIND
  amanuense run CARPETA [--ai-cli claude|codex|gemini|copilot] [--content]
  amanuense run CARPETA [--ai-url URL --ai-model MODELO]
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import unicodedata
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import i18n
from .confluence import (
    Page,
    _read_local,
    _slug,
    best_page_level,
    compare,
    docx_to_pages,
    find_contradictions,
    load_local,
    normalize_title,
    rag_embed,
    rag_judge,
    render_report,
    sections,
)

BIBLE_DOC_CHARS = 8000
MAX_REWRITE = 40_000  # beyond this the AI answers with edit blocks, not the whole page
CHAT_LIMIT_CHARS = 120_000  # ~30k tokens: beyond this a plain chat window truncates
TEMPLATE_TITLE = re.compile(r"\b(plantilla|template)\b", re.IGNORECASE)
WANTS_TEMPLATE = re.compile(r"^\s*(plantilla|template)\s*:", re.IGNORECASE | re.MULTILINE)

Ai = Callable[[str], str]

# Workshop names, kept as module attributes; they follow the current language.
_NAMES = {"EXPORT_DIR": "export", "LOCAL_DIR": "local", "BIBLE_DIR": "bible", "OUT_DIR": "out",
          "GUIDE": "guide", "RESULT": "result"}


def __getattr__(attr: str) -> str:
    if attr in _NAMES:
        return i18n.name(_NAMES[attr])
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


@dataclass
class Task:
    slug: str
    kind: str  # "update" | "new"
    title: str
    local_rel: str
    page: Page | None
    sources: list[str] = field(default_factory=list)  # every local file it is built from (a pile can bring several)
    material: bool = False  # uploaded material without update instructions: the page takes what is new in it


def init_workspace(root: Path, lang: str | None = None) -> Path:
    """Creates the input folders and their guides; an existing workshop keeps its language."""
    i18n.choose(root, lang)
    for key in ("export", "local", "bible"):
        (root / i18n.name(key)).mkdir(parents=True, exist_ok=True)
    for key, text in (("guide", "guide_text"), ("requests", "requests_text"), ("repos", "repos_text")):
        name, text = i18n.name(key), i18n.t(text)
        if not (root / name).exists():
            (root / name).write_text(text, encoding="utf-8")
    return root


def _inputs(folder: Path, suffix: str) -> list[Path]:
    return sorted(p for p in folder.rglob(f"*{suffix}") if p.is_file() and not p.name.startswith("~$"))


def _bible(root: Path) -> str:
    folder = root / i18n.name("bible")
    if not folder.is_dir():
        return ""
    parts = []
    for d in load_local(folder):
        text = _read_local(folder / d.rel).strip()
        if len(text) > BIBLE_DOC_CHARS:
            text = text[:BIBLE_DOC_CHARS] + "\n\n" + i18n.t("cut")
        parts.append(f"### {d.title} (`{d.rel}`)\n\n{text}")
    return "\n\n".join(parts)


def _template(root: Path, exports: list[Path], level: int, pages: list[Page] | None = None) -> Page | None:
    """Template for new pages: a «plantilla» document in the bible wins; otherwise the
    export page named like one, taken whole (with its child pages) at its own level,
    or the live page named like one when the pages come from Confluence itself."""
    folder = root / i18n.name("bible")
    if folder.is_dir():
        for d in load_local(folder):
            if TEMPLATE_TITLE.search(d.title) or TEMPLATE_TITLE.search(Path(d.rel).stem.replace("-", " ")):
                return Page(d.title, _read_local(folder / d.rel))
    if pages is not None:
        return next((p for p in pages if TEMPLATE_TITLE.search(p.title)), None)
    for lvl in range(1, level + 1):
        for e in exports:
            for p in docx_to_pages(e, lvl):
                if TEMPLATE_TITLE.search(p.title):
                    return p
    return None


LABEL = re.compile(r"^\s*([^:|]{1,40}?):(?:\s|$)")
TABLE_RULE = re.compile(r"^\|?[\s:|-]+\|?$")


def _labels_only(text: str) -> str:
    labels = [f"{m.group(1).strip()}: …" for part in text.split("<br>") if (m := LABEL.match(part))]
    return "<br>".join(labels) or "…"


def template_skeleton(markdown: str) -> str:
    """The template's shape without its example content: headings, table headers and
    «Etiqueta: …» labels stay; every example value, paragraph and list item becomes «…».
    A template filled in with a real example otherwise leaks into every new page."""
    lines = [l.strip() for l in markdown.splitlines()]
    out: list[str] = []

    def add(line: str) -> None:
        if line != (out[-1] if out else None) or line.startswith(("|", "#")):
            out.append(line)

    for i, line in enumerate(lines):
        if not line:
            add("")
        elif re.match(r"^#{1,6}\s", line):
            add(line)
        elif line.startswith("|"):
            header = i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]
            if TABLE_RULE.match(line) and "-" in line:
                add(line)
            elif header:  # a short title cell is structure; a sentence is example content
                add("| " + " | ".join(c if len(c) <= 40 and not c.endswith(".") else "…"
                                      for c in _cells(line)) + " |")
            else:
                add("| " + " | ".join(_labels_only(c) for c in _cells(line)) + " |")
        elif re.match(r"^([-*+]|\d+[.)])\s", line):
            add("- …")
        else:
            add(_labels_only(line))
    return "\n".join(out).strip() + "\n"


def _demote(markdown: str, levels: int = 2) -> str:
    """Push headings down so an embedded page never competes with the task's own."""
    return re.sub(r"^(#{1,6})(?=\s)", lambda m: "#" * min(6, len(m.group(1)) + levels),
                  markdown, flags=re.MULTILINE)


def _tasks(rows, pages: list[Page], material: set[str] | frozenset = frozenset()) -> list[Task]:
    """One task per update and per new page; the files of an upload that update the same page
    share one task, so a pile with three copies of a page asks the AI once."""
    from .intake import MAX_SOURCES, is_intake
    by_title = {p.title: p for p in pages}
    tasks: list[Task] = []
    piled: dict[str, Task] = {}
    for r in rows:
        if r.kind in ("update", "update_by_content"):
            page = by_title.get(r.match or r.title)
            title = page.title if page else r.title
            if is_intake(r.local) and title in piled:
                if len(piled[title].sources) < MAX_SOURCES:
                    piled[title].sources.append(r.local)
                piled[title].material = piled[title].material and r.local in material
                continue
            task = Task("", "update", title, r.local, page, [r.local], r.local in material)
            if is_intake(r.local):
                piled[title] = task
            tasks.append(task)
    for r in rows:
        if r.kind == "new":  # instructions without a page stay in the report: map them by hand
            tasks.append(Task("", "new", r.title, r.local, None))
    for n, t in enumerate(tasks, 1):
        verb = i18n.name("verb_update" if t.kind == "update" else "verb_new")
        t.slug = f"{n:02d}-{verb}-{_slug(t.title)}"
    return tasks


def _prompt(task: Task, local_text: str, template: Page | None, bible: str) -> str:
    t = i18n.t
    rules = t("rules", title=task.title, bible_rule=t("bible_rule" if bible else "no_bible_rule"))
    out = []
    if task.kind == "update" and task.material:
        rels = ", ".join(f"`{r}`" for r in task.sources or [task.local_rel])
        out += [t("task_update_title", title=task.title), "", t("task_material_intro"), "", rules,
                t("task_material", rels=rels), "", _demote(local_text), "",
                t("task_current_page"), "", _demote(task.page.markdown if task.page else ""), ""]
    elif task.kind == "update":
        out += [t("task_update_title", title=task.title), "", t("task_update_intro"), "", rules,
                t("task_update_instructions", rel=task.local_rel), "", _demote(local_text), "",
                t("task_current_page"), "", _demote(task.page.markdown if task.page else ""), ""]
    else:
        out += [t("task_new_title", title=task.title), "", t("task_new_intro"), "", rules]
        if template and WANTS_TEMPLATE.search(local_text):
            out += [t("task_template", title=template.title), "", t("task_template_hint"),
                    "", _demote(template_skeleton(template.markdown), 1), ""]
        out += [t("task_draft", rel=task.local_rel), "", _demote(local_text), ""]
    if bible:
        out += [t("task_bible"), "", _demote(bible, 1), ""]
    return "\n".join(out).rstrip() + "\n"


# ── Markdown → HTML (enough for a clean paste into Confluence) ────────────────

SAFE_SCHEMES = ("http", "https", "mailto")


def _safe_url(url: str) -> bool:
    """Relative links and http(s)/mailto only: no javascript: or data: in a page someone opens."""
    scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", url)
    return not scheme or scheme.group(1).lower() in SAFE_SCHEMES


def _attr(value: str) -> str:
    return value.replace('"', "&quot;")  # the text is escaped already, but not its quotes


def _inline(text: str) -> str:
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: f'<img alt="{_attr(m.group(1))}" src="{_attr(m.group(2))}">' if _safe_url(m.group(2))
                  else m.group(1), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{_attr(m.group(2))}">{m.group(1)}</a>' if _safe_url(m.group(2))
                  else m.group(1), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"&lt;br\s*/?&gt;", "<br>", text)  # line breaks inside table cells
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            body = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(body), quote=False)}</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2).strip())}</h{n}>")
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            head = "".join(f"<th>{_inline(c)}</th>" for c in _cells(line))
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")
            continue
        for tag, pattern in (("ul", r"^\s*[-*+]\s+(.*)$"), ("ol", r"^\s*\d+[.)]\s+(.*)$")):
            if re.match(pattern, line):
                items = []
                while i < len(lines) and re.match(pattern, lines[i]):
                    items.append(f"<li>{_inline(re.match(pattern, lines[i]).group(1))}</li>")
                    i += 1
                out.append(f"<{tag}>{''.join(items)}</{tag}>")
                break
        else:
            if line.startswith(">"):
                quote = []
                while i < len(lines) and lines[i].startswith(">"):
                    quote.append(lines[i].lstrip(">").strip())
                    i += 1
                out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
            elif line.strip():
                para = []
                while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|>|```|\s*[-*+]\s|\s*\d+[.)]\s|\s*\|)", lines[i]):
                    para.append(lines[i].strip())
                    i += 1
                if not para:  # a line no block rule claimed
                    para, i = [line.strip()], i + 1
                out.append(f"<p>{_inline(' '.join(para))}</p>")
            else:
                i += 1
    return "\n".join(out) + "\n"


TOKEN = re.compile(r"[^\W_][\w./-]*")
SENTENCE_START = re.compile(r"(^|[.!?|>#*(\-–•✅❌«“\"']|<br>)\s*$")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def _looks_like_data(token: str, before: str) -> bool:
    if any(c.isdigit() for c in token) or "-" in token or "_" in token or "/" in token:
        return True
    if len(token) >= 2 and token.isupper():
        return True
    if any(c.isupper() for c in token[1:]):
        return True  # CamelCase
    return token[0].isupper() and not SENTENCE_START.search(before)


def _has_term(text: str, term: str) -> bool:
    """`term` in `text` with no word character either side; both are folded to ASCII, where a
    word character is a letter, a digit or "_". str.find beats a regex on a long task."""
    def word(i: int) -> bool:
        return 0 <= i < len(text) and (text[i].isalnum() or text[i] == "_")
    at = text.find(term)
    while at != -1:
        if not word(at - 1) and not word(at + len(term)):
            return True
        at = text.find(term, at + 1)
    return False


def unsupported_terms(result: str, sources: str) -> list[str]:
    """Data-like terms in an AI result that appear nowhere in what the AI was given:
    figures, versions, acronyms, identifiers and proper names mid-sentence. A cheap,
    model-independent check for invented content before a page is approved."""
    folded = _fold(sources)
    found, seen = set(), {}
    for line in result.splitlines():
        for m in TOKEN.finditer(line):
            token = m.group(0).rstrip(".-/")
            if not token or not _looks_like_data(token, line[:m.start()]):
                continue
            term = _fold(token)
            if term not in seen:
                seen[term] = _has_term(folded, term)
            if not seen[term]:
                found.add(token)
    return sorted(found)


PAGE_CSS = ("body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;"
            "line-height:1.5}table{border-collapse:collapse}td,th{border:1px solid #999;padding:.3rem .6rem}"
            "blockquote{border-left:4px solid #999;margin:0;padding-left:1rem}")


EDIT_BLOCK = re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n?>>>>>>> REPLACE\n?", re.DOTALL)


def _level(text: str) -> int:
    """Level of the first heading in `text`."""
    m = re.search(r"^(#+)", text, re.MULTILINE)
    return len(m.group(1)) if m else 0


def apply_edits(page: str, answer: str) -> tuple[str, list[str]]:
    """Applies SEARCH/REPLACE blocks whose text is unique; a failed one becomes a PENDING line.

    Whatever the answer has outside the blocks (the change log) goes at the end."""
    failed: list[str] = []
    for search, replace in EDIT_BLOCK.findall(answer):
        hits = page.count(search)
        if not hits:  # the task shows headings demoted, so the AI may copy a different level
            loose = re.compile("\n".join(r"#+" + re.escape(line.lstrip("#")) if line.startswith("#")
                                         else re.escape(line) for line in search.split("\n")))
            found = loose.findall(page)
            if len(found) == 1:
                shift = _level(found[0]) - _level(search)  # keep the page's own heading levels
                search, hits = found[0], 1
                replace = "\n".join("#" * max(1, _level(line) + shift) + line.lstrip("#") if line.startswith("#")
                                    else line for line in replace.split("\n"))
            hits = hits or len(found)
        if hits == 1:
            page = page.replace(search, replace, 1)
        else:
            why = i18n.t("edit_missing") if not hits else i18n.t("edit_ambiguous", n=hits)
            failed.append(i18n.t("edit_failed", why=why, search=" ".join(search.split())[:120]))
    tail = EDIT_BLOCK.sub("", answer).strip()
    parts = [page.rstrip(), *failed, tail] if failed else [page.rstrip(), tail]
    return "\n\n".join(x for x in parts if x) + "\n", failed


def solve(prompt: str, base: str, ai: Ai) -> str:
    """The AI's proposal: the whole page, or edit blocks applied to `base` when it is long."""
    if len(base) <= MAX_REWRITE:
        return ai(prompt).strip() + "\n"
    return apply_edits(base, ai(prompt.rstrip() + "\n\n" + i18n.t("edits_mode") + "\n"))[0]


def notices(markdown: str) -> list[str]:
    """The PENDING / CONFLICT lines of a proposal, without their quote marker."""
    marker = re.compile(r"^\s*>?\s*\**" + i18n.t("notice_marker") + r"\**\s*:")
    return [line.strip().lstrip(">").strip() for line in markdown.splitlines() if marker.match(line)]


def _notice_box(markdown: str) -> str:
    found = notices(markdown)
    if not found:
        return f'<p id="notices"><b>{html.escape(i18n.t("notices_none"))}</b></p>'
    items = "".join(f"<li>{html.escape(x)}</li>" for x in found)
    return (f'<div id="notices" style="border:2px solid #b45309;padding:.5rem 1rem;margin:1rem 0">'
            f'<b>{html.escape(i18n.t("notices_n", n=len(found)))}</b><ul>{items}</ul></div>')


def _html_page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="{i18n.current()}"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"<style>{PAGE_CSS}</style></head><body>\n{body}</body></html>\n")


def _publish(task_dir: Path, task: Task) -> list[str] | None:
    """Writes the paste-ready page and the change view; returns the unsupported terms."""
    n = i18n.name
    result = task_dir / n("result")
    if not result.is_file():
        return None
    proposal = result.read_text(encoding="utf-8")
    unsupported = unsupported_terms(proposal, (task_dir / n("task")).read_text(encoding="utf-8"))
    (task_dir / n("paste")).write_text(_html_page(task.title, markdown_to_html(proposal)), encoding="utf-8")
    before = (task_dir / n("current" if task.page else "local_copy")).read_text(encoding="utf-8")
    diff = difflib.HtmlDiff(wrapcolumn=90).make_file(
        before.splitlines(), proposal.splitlines(),
        i18n.t("confluence_today" if task.page else "local_draft"), i18n.t("proposal"), context=True, numlines=3)
    note = _notice_box(proposal)
    if unsupported:
        note += i18n.t("unsourced_note", terms=html.escape(", ".join(unsupported)))
    diff = diff.replace("<body>", "<body>\n" + note, 1)
    (task_dir / n("changes")).write_text(diff, encoding="utf-8")
    return unsupported


def _index(out: Path, rows, tasks: list[Task], ready: dict[str, list[str]], level: int,
           sizes: dict[str, int], errors: dict[str, str] | None = None) -> str:
    n, t = i18n.name, i18n.t
    counts = "".join(f"<li>{html.escape(label)}: <b>{sum(r.kind == k for r in rows)}</b></li>"
                     for k, label, _ in sections())
    trs = []
    for task in tasks:
        base = f"{n('tasks')}/{task.slug}"
        links = [f'<a href="{base}/{n("task")}">{n("task")}</a>']
        if task.slug in ready:
            links += [f'<a href="{base}/{n("changes")}">{n("changes")}</a>',
                      f'<a href="{base}/{n("paste")}">{n("paste")}</a>']
        state = t("state_ready") if task.slug in ready else t("state_pending", result=n("result"))
        if ready.get(task.slug):
            count = len(ready[task.slug])
            state += t("state_unsourced_1") if count == 1 else t("state_unsourced_n", n=count)
        if (errors or {}).get(task.slug):
            state += t("state_ai_failed", error=html.escape(errors[task.slug]))
        if sizes.get(task.slug, 0) > CHAT_LIMIT_CHARS:
            state += t("state_big", k=sizes[task.slug] // 1000)
        trs.append(f"<tr><td>{html.escape(task.slug)}</td><td>{html.escape(task.title)}</td>"
                   f"<td>{state}</td><td>{' · '.join(links)}</td></tr>")
    report, log = n("report"), n("log_html")
    intro = t("index_intro", level=level, report=f'<a href="{report}">{report}</a>', log=f'<a href="{log}">{log}</a>')
    body = (f"<h1>{t('workshop_title')}</h1><p>{intro}</p><ul>{counts}</ul>"
            f"<h2>{t('index_tasks', ready=len(ready), total=len(tasks))}</h2><table><thead><tr>"
            f"<th>{t('col_folder')}</th><th>{t('col_page')}</th><th>{t('col_state')}</th>"
            f"<th>{t('col_files')}</th></tr></thead><tbody>{''.join(trs)}</tbody></table>")
    return _html_page(t("workshop_title"), body)


def _local_text(local_root: Path, task: Task) -> str:
    rels = task.sources or [task.local_rel]
    if len(rels) == 1:
        return _read_local(local_root / rels[0])
    return "\n\n".join(f"{i18n.t('task_material_from', rel=rel)}\n\n{_read_local(local_root / rel).strip()}"
                       for rel in rels) + "\n"


def run_workspace(root: Path, embed=None, judge=None, ai: Ai | None = None, history=None,
                  router: Ai | None = None, lang: str | None = None, source=None, progress=None,
                  sync_repos: bool = True) -> dict:
    """`history` gives Confluence authors to the change log; `router` (default: `ai`) routes requests.
    `source` (space.Source) brings the pages read live from Confluence; without it, or when it
    falls back, the Word export in the workshop is read. `progress(stage, done, total)` hears
    how far it is (stages: compare, write, log)."""
    from . import intake
    from . import registro as log
    from . import space
    tell = progress or (lambda stage, done, total: None)
    init_workspace(root, lang)
    n = i18n.name
    exports = _inputs(root / n("export"), ".docx")
    local_root = root / n("local")
    tell("compare", 0, 0)
    skip, skipped = intake.screen(local_root, intake.noise_patterns(root))
    local = load_local(local_root, skip)
    live = source is not None and source.pages is not None
    if live:
        level, pages = 1, source.pages
    else:
        level = best_page_level(exports, local) if exports else 1
        pages = [p for e in exports for p in docx_to_pages(e, level)]
        created = max((log.export_created(e) for e in exports), default="")
        source = space.Source("export" if exports else "none", pages, created,
                              {"files": [e.name for e in exports]}, source.warning if source else "")
    used = space.write_summary(root, source)
    rows = compare(pages, local, embed)
    rows, material = intake.adjust(rows, pages, local, set(intake.promoted(root)))
    if embed and judge:
        rows += find_contradictions(rows, pages, local, embed, judge)
    if skipped or any(intake.is_intake(d.rel) for d in local) or any(local_root.glob(intake.BATCH_PREFIX + "*")):
        intake.write_summary(root, rows, local, skipped, used)

    out = root / n("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / n("report")).write_text(render_report(rows), encoding="utf-8")

    template = _template(root, exports, level, pages if live else None)
    bible = _bible(root)
    tasks = _tasks(rows, pages, material)
    ready: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    errors: dict[str, str] = {}
    for i, t in enumerate(tasks):
        tell("write", i, len(tasks))
        d = out / n("tasks") / t.slug
        d.mkdir(parents=True, exist_ok=True)
        local_text = _local_text(local_root, t)
        (d / n("local_copy")).write_text(local_text, encoding="utf-8")
        if t.page:
            (d / n("current")).write_text(t.page.markdown, encoding="utf-8")
        prompt = _prompt(t, local_text, template, bible)
        (d / n("task")).write_text(prompt, encoding="utf-8")
        sizes[t.slug] = len(prompt)
        if ai and not (d / n("result")).exists():
            try:
                base = t.page.markdown if t.page else local_text
                (d / n("result")).write_text(solve(prompt, base, ai), encoding="utf-8")
            except Exception as exc:  # one failing task must not stop the rest
                errors[t.slug] = str(exc)
        unsupported = _publish(d, t)
        if unsupported is not None:
            ready[t.slug] = unsupported

    tell("write", len(tasks), len(tasks))
    tell("log", 0, 0)
    done = {f"{n('tasks')}/{t.slug}": t for t in tasks if t.slug in ready}
    changes = log.update_log(root, exports, pages, done, history, router or ai, template, bible, ai=ai,
                             created=source.created if live else None, source=source.kind if live else "export",
                             sync_repos=sync_repos)

    index = out / "index.html"
    index.write_text(_index(out, rows, tasks, ready, level, sizes, errors), encoding="utf-8")
    return {"page_level": level, "tasks": [t.slug for t in tasks], "ready": sorted(ready), "errors": errors,
            "index": index, "template": template.title if template else None,
            "log": out / n("log_html"), "log_errors": changes["errors"], "source": used}


UNSAFE_NAME = re.compile(r'[\\/:*?"<>|]')


def deliver_workspace(root: Path, make_zip: bool = False, today: str | None = None,
                      lang: str | None = None) -> Path:
    """Gathers every ready proposal into output/delivery-DATE/: one folder per page and a README."""
    from datetime import date
    from . import registro as log
    from . import revision
    i18n.choose(root, lang)
    n, t = i18n.name, i18n.t
    out = root / n("out")
    entries = log._load(out / n("log_json"), [])
    requests = {e["task"]: e for e in entries if e["kind"] == "peticion" and e.get("task")}
    code = {rel: title for e in entries if e["kind"] == "codigo" for rel, title in log.code_task_pages(e).items()}

    def verdict(rel: str) -> dict:
        path = out / rel / log.TRIAGE_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    folder = out / f'{n("delivery")}-{today or date.today().isoformat()}'
    if folder.exists():
        shutil.rmtree(folder)
    lines = [t("deliver_title", date=folder.name.split("-", 1)[1]), ""]
    sections: dict[str, list[str]] = {"pages": [], "new": []}
    notes: list[str] = []
    discarded = {p["title"] for p in revision.proposals(root) if p["status"] == "descartada"}
    for title, rels in revision.candidates(root).items():
        if title in discarded:
            continue
        rel = rels[0]
        src = out / rel
        new = not (src / n("current")).is_file()
        dest = folder / n("new_dir" if new else "pages_dir") / UNSAFE_NAME.sub("_", title)
        dest.mkdir(parents=True)
        for key in ("result", "paste", "changes", "current"):
            if (src / n(key)).is_file():
                shutil.copy2(src / n(key), dest / n(key))
        found = notices((src / n("result")).read_text(encoding="utf-8"))
        asked = [requests[r]["by"] for r in requests if requests[r]["page"] == title]
        if rel in requests:
            origin = t("deliver_from_request", by=requests[rel]["by"])
        elif rel in code:
            chained = verdict(rel).get("categoria") == "encadenar" and asked
            origin = (t("deliver_from_request", by=", ".join(dict.fromkeys(asked))) + " · " if chained else "") \
                + t("deliver_from_code")
        else:
            origin = t("deliver_from_docs")
        sections["new" if new else "pages"].append(
            f"- {title} · {origin}" + (f" · {t('deliver_notes' if len(found) > 1 else 'deliver_note', n=len(found))}"
                                      if found else ""))
        notes += [f"- {title}: {x}" for x in found]
    for key, head, dir_key in (("pages", "deliver_pages", "pages_dir"), ("new", "deliver_new", "new_dir")):
        if sections[key]:
            lines += [t(head, dir=n(dir_key)), "", *sections[key], ""]
    if sections["pages"] or sections["new"]:
        lines += [t("deliver_files", changes=n("changes"), paste=n("paste"), result=n("result")), ""]
    doubtful = {rel: f'- {title}: {verdict(rel).get("motivo", "")}'
                for e in entries if e["kind"] == "codigo"
                for rel, title in log.code_task_pages(e).items() if verdict(rel).get("categoria") == "dudosa"}
    if doubtful:
        lines += [t("deliver_doubtful"), "", *sorted(doubtful.values()), ""]
    if notes:
        lines += [t("deliver_notices"), "", *notes, ""]
    radiator = out / "radiador"
    if radiator.is_dir():
        shutil.copytree(radiator, folder / "radiador")
        lines += [t("deliver_radiator"), ""]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / n("readme")).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if make_zip:
        shutil.make_archive(str(folder), "zip", folder.parent, folder.name)
    return folder


def openai_client(url: str, model: str, key: str = "", opener=urllib.request.urlopen,
                  timeout: float = 900) -> Ai:
    """Chat completions against any OpenAI-compatible API (Ollama, LM Studio, vLLM...)."""
    endpoint = url.rstrip("/") + "/chat/completions"

    def ask(prompt: str) -> str:
        body = {"model": model, "temperature": 0.2, "messages": [
            {"role": "system", "content": i18n.t("system_prompt")},
            {"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(endpoint, json.dumps(body).encode("utf-8"), headers)
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]

    return ask


# Headless invocations; the prompt always goes on stdin (a task can exceed the
# Windows command-line limit). "{last}" is a file the CLI writes its answer to.
ENGINES: dict[str, list[str]] = {
    "claude": ["-p", "--output-format", "text"],
    "codex": ["exec", "--skip-git-repo-check", "--sandbox", "read-only",
              "--output-last-message", "{last}", "-"],
    # -p forces headless; its text is appended to what arrives on stdin.
    "gemini": ["-p", "{nudge}", "--output-format", "text"],
    # copilot ignores stdin when given -p, so the task goes only through the pipe.
    "copilot": ["-s", "--no-ask-user"],
}


def cli_client(engine: str, run=subprocess.run, which=shutil.which, timeout: float = 1800) -> Ai:
    """An installed agent CLI (Claude Code, Codex, Gemini, Copilot) as the AI.

    Each call runs in an empty temporary folder: the task carries everything the
    page needs, so the agent never has a reason to read the user's folders."""
    if engine not in ENGINES:
        raise ValueError(i18n.t("err_engine", engine=engine, engines=", ".join(ENGINES)))
    exe = which(engine)
    if not exe:
        raise RuntimeError(i18n.t("err_not_installed", engine=engine))

    def ask(prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="amanuense-") as tmp:
            last = Path(tmp) / "last-message.md"
            args = [exe] + [a.replace("{last}", str(last)).replace("{nudge}", i18n.t("gemini_nudge")) for a in ENGINES[engine]]
            proc = run(args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=tmp)
            if proc.returncode != 0:
                raise RuntimeError(i18n.t("err_exit", engine=engine, code=proc.returncode,
                                          tail=(proc.stderr or proc.stdout or "").strip()[-400:]))
            answer = last.read_text(encoding="utf-8") if last.is_file() else proc.stdout
            if not answer.strip():
                raise RuntimeError(i18n.t("err_empty", engine=engine))
            return answer

    return ask


# ── Native agent/skill files for each agent tool, from one source ─────────────

def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML frontmatter: `key: value` and `key:` followed by `  - item` lists."""
    if not text.startswith("---"):
        return {}, text
    head, body = text[3:].split("\n---", 1)
    meta: dict = {}
    key = None
    for line in head.strip().splitlines():
        if line.lstrip().startswith("- ") and key:
            meta.setdefault(key, []).append(line.lstrip()[2:].strip())
        elif ":" in line:
            key, value = (x.strip() for x in line.split(":", 1))
            meta[key] = value or []
    return meta, body.lstrip("\n")


def _frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        lines += [f"{k}:"] + [f"  - {i}" for i in v] if isinstance(v, list) else [f"{k}: {v}"]
    return "\n".join(lines + ["---", ""])


def _toml_text(value: str) -> str:
    if "\'\'\'" not in value:
        return "\'\'\'\n" + value + "\'\'\'"
    return json.dumps(value, ensure_ascii=False)


def export_agents(src: Path, dest: Path) -> list[Path]:
    """Write the skills and agents of `src` (skills/<name>/SKILL.md, agents/*.md or agentes/*.md,
    AGENTS.md) in the layout each tool reads: Claude Code, Codex, Gemini CLI and
    GitHub Copilot. `src` stays the only place to edit; rerun after changing it."""
    written: list[Path] = []

    def put(rel: str, data: str | bytes) -> None:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8", newline="\n")
        written.append(target)

    for skill in sorted((src / "skills").glob("*/SKILL.md")):
        name = skill.parent.name
        for base in (".claude/skills", ".agents/skills"):  # Claude | Codex, Gemini, Copilot
            put(f"{base}/{name}/SKILL.md", skill.read_bytes())

    for agent in sorted([*(src / "agents").glob("*.md"), *(src / "agentes").glob("*.md")]):
        meta, body = _split_frontmatter(agent.read_text(encoding="utf-8"))
        name, description = meta.get("name") or agent.stem, meta.get("description", "")
        plain = {"name": name, "description": description}
        claude = dict(plain, **({"skills": meta["skills"]} if meta.get("skills") else {}))
        put(f".claude/agents/{name}.md", _frontmatter(claude) + body)
        put(f".github/agents/{name}.md", _frontmatter(plain) + body)
        put(f".gemini/agents/{name}.md", _frontmatter(plain) + body)
        put(f".codex/agents/{name}.toml", f"name = {json.dumps(name)}\n"
            f"description = {json.dumps(description, ensure_ascii=False)}\n"
            f"developer_instructions = {_toml_text(body)}\n")

    if (src / "AGENTS.md").is_file() and src.resolve() != dest.resolve():
        put("AGENTS.md", (src / "AGENTS.md").read_bytes())
    put("CLAUDE.md", "@AGENTS.md\n")  # Claude Code skips AGENTS.md when a CLAUDE.md exists
    put(".gemini/settings.json", json.dumps({"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}},
                                            indent=2) + "\n")
    return written


def _lang_arg(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def radiator_workspace(root: Path, lang: str | None = None) -> Path:
    """The capability radiator of the workshop: repos.txt, its export pages and radiador.json."""
    from . import radiador, registro
    init_workspace(root, lang)
    exports = _inputs(root / i18n.name("export"), ".docx")
    level = best_page_level(exports, []) if exports else 1
    pages = [p for e in exports for p in docx_to_pages(e, level)]
    repos = [spec.path for spec in registro.read_repos(root) if spec.path.is_dir()]
    catalog = radiador.build_catalog(repos, pages, radiador.load_config(root))
    return radiador.write_radiator(root, catalog)


def main(argv: list[str] | None = None) -> None:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.choose(None, _lang_arg(argv))  # help and messages; a workshop's own language wins later
    t = i18n.t
    ap = argparse.ArgumentParser(description=t("cli_description"))
    ap.add_argument("--lang", choices=i18n.LANGS, help=t("cli_lang"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    after = argparse.ArgumentParser(add_help=False)  # --lang is also accepted after the subcommand
    after.add_argument("--lang", choices=i18n.LANGS, default=argparse.SUPPRESS, help=t("cli_lang"))
    sub.add_parser("init", help=t("cli_init"), parents=[after]).add_argument("root", type=Path)
    agents = sub.add_parser("agents", help=t("cli_agents"), parents=[after])
    agents.add_argument("dest", type=Path, help=t("cli_agents_dest"))
    agents.add_argument("--src", type=Path, default=None, help=t("cli_agents_src"))
    vault = sub.add_parser("obsidian", help=t("cli_obsidian"), parents=[after])
    vault.add_argument("export", type=Path, help=t("cli_export"))
    vault.add_argument("dest", type=Path, help=t("cli_vault"))
    vault.add_argument("--force", action="store_true", help=t("cli_force"))
    radiator = sub.add_parser("radiator", help=t("cli_radiator"), parents=[after])
    radiator.add_argument("root", type=Path)
    radiator.add_argument("--no-open", action="store_true", help=t("cli_no_open"))
    review = sub.add_parser("review", help=t("cli_review"), parents=[after])
    review.add_argument("root", type=Path)
    review.add_argument("--no-open", action="store_true", help=t("cli_no_open"))
    deliver = sub.add_parser("deliver", help=t("cli_deliver"), parents=[after])
    deliver.add_argument("root", type=Path)
    deliver.add_argument("--zip", action="store_true", help=t("cli_zip"))
    deliver.add_argument("--no-open", action="store_true", help=t("cli_no_open"))
    run = sub.add_parser("run", help=t("cli_run"), parents=[after])
    run.add_argument("root", type=Path)
    run.add_argument("--ai-url", default=os.environ.get("AMANUENSE_AI_URL", ""), help=t("cli_ai_url"))
    run.add_argument("--ai-model", default=os.environ.get("AMANUENSE_AI_MODEL", ""))
    run.add_argument("--ai-cli", default=os.environ.get("AMANUENSE_AI_CLI", ""), choices=["", *ENGINES],
                     help=t("cli_ai_cli"))
    run.add_argument("--content", action="store_true", help=t("cli_content"))
    run.add_argument("--contradictions", action="store_true", help=t("cli_contradictions"))
    run.add_argument("--device", default=None)
    run.add_argument("--no-open", action="store_true", help=t("cli_no_open"))
    a = ap.parse_args(argv)

    if a.cmd == "init":
        print(init_workspace(a.root, a.lang) / i18n.name("guide"))
        return
    if a.cmd == "obsidian":
        from .obsidian import export_to_vault
        try:
            done = export_to_vault(a.export, a.dest, a.force)
        except (FileExistsError, FileNotFoundError) as e:
            raise SystemExit(f"✗ {e}") from None
        print(t("cli_vault_done", notes=done["notes"], media=done["media"], vault=done["vault"]))
        return
    if a.cmd == "radiator":
        index = radiator_workspace(a.root, a.lang)
        print(index)
        if not a.no_open:
            webbrowser.open(index.resolve().as_uri())
        return
    if a.cmd == "review":
        from .app import run_app
        run_app(a.root, not a.no_open, a.lang)
        return
    if a.cmd == "deliver":
        folder = deliver_workspace(a.root, a.zip, lang=a.lang)
        print(folder)
        if not a.no_open:
            webbrowser.open(folder.resolve().as_uri())
        return
    if a.cmd == "agents":
        src = a.src or Path(__file__).resolve().parent / "skeleton" / i18n.current()
        for path in export_agents(src, a.dest):
            print(path)
        return
    ai = None
    if a.ai_cli:
        ai = cli_client(a.ai_cli)
    elif a.ai_url:
        if not a.ai_model:
            ap.error(t("cli_needs_model"))
        ai = openai_client(a.ai_url, a.ai_model, os.environ.get("AMANUENSE_AI_KEY", ""))
    embed = judge = None
    if a.content:
        embed = rag_embed(a.device)
        if a.contradictions:
            judge = rag_judge()
    from . import registro as log
    summary = run_workspace(a.root, embed, judge, ai, log.history_from_env(), lang=a.lang)
    for warning in summary["log_errors"]:
        print(i18n.t("cli_warning"), warning)
    print(i18n.t("cli_ready", ready=len(summary["ready"]), total=len(summary["tasks"])))
    print(summary["index"])
    if not a.no_open:  # straight into the review app, where every proposal is decided
        from .app import run_app
        run_app(a.root, True, a.lang)


if __name__ == "__main__":
    main()
