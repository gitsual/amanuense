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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .confluence import (
    SECTIONS,
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
)

EXPORT_DIR = "1-export-confluence"
LOCAL_DIR = "2-mi-documentacion"
BIBLE_DIR = "3-biblia"
OUT_DIR = "salida"
GUIDE = "LEEME.md"
RESULT = "RESULTADO.md"
BIBLE_DOC_CHARS = 8000
CHAT_LIMIT_CHARS = 120_000  # ~30k tokens: beyond this a plain chat window truncates
TEMPLATE_TITLE = re.compile(r"\b(plantilla|template)\b", re.IGNORECASE)
WANTS_TEMPLATE = re.compile(r"^\s*plantilla\s*:", re.IGNORECASE | re.MULTILINE)

Ai = Callable[[str], str]

GUIDE_TEXT = """# Taller de documentación

1. Copia en `1-export-confluence/` el Word exportado de Confluence
   (menú «···» de la página → Exportar → Exportar a Word → «Esta página y sus hijos»).
2. Copia en `2-mi-documentacion/` tu carpeta de trabajo. Cada documento que
   sustituye a una página lleva su mismo título y un párrafo que empieza por
   «Instrucciones de actualización:». Los documentos nuevos no lo llevan; si uno
   nuevo debe seguir la plantilla (por ejemplo, una capacidad), añade una línea
   «Plantilla: sí».
3. Copia en `3-biblia/` los documentos que mandan sobre todo lo demás
   (arquitectura de referencia, requisitos de publicación, estándares de repos).
   Si dejas aquí un documento cuyo nombre o título contenga «plantilla», será la
   plantilla de las páginas nuevas; si no, se usa la del export.
4. Ejecuta el taller. Se abre `salida/index.html` con el informe y una tarea por página.
5. En cada tarea, da `TAREA.md` a tu IA y guarda su respuesta como `RESULTADO.md`
   en la misma carpeta. Vuelve a ejecutar el taller.
6. Revisa `CAMBIOS.html`, abre `PARA-CONFLUENCE.html`, selecciona todo, copia y
   pega en la página de Confluence.

Nada sale de este equipo salvo que configures una IA con --ai-url.
"""

RULES = """## Reglas

1. No inventes datos: nombres, versiones, URL, fechas ni responsables.
   No añadas contenido que no esté en esta tarea: sólo redacta y ordena lo que ya hay.
   Si falta algo, deja una línea `> PENDIENTE: qué falta`.
{bible_rule}3. Coherente y reducida: quita repeticiones; si un bloque ya vive en otra página,
   sustitúyelo por «Ver la página «Título»».
4. Formato: Markdown, empezando por `# {title}`; tablas en Markdown; sin HTML.
5. Termina con `## Registro de cambios`, una viñeta por cambio.
6. Responde SOLO con la página.
"""
BIBLE_RULE = """2. La Biblia manda. Si algo la contradice, no elijas tú: deja una línea
   `> CONFLICTO: qué choca con qué` y conserva el texto actual.
"""
NO_BIBLE_RULE = """2. Si dos partes de esta tarea se contradicen, no elijas tú: deja una línea
   `> CONFLICTO: qué choca con qué` y conserva el texto actual.
"""


@dataclass
class Task:
    slug: str
    kind: str  # "update" | "new"
    title: str
    local_rel: str
    page: Page | None


def init_workspace(root: Path) -> Path:
    for name in (EXPORT_DIR, LOCAL_DIR, BIBLE_DIR):
        (root / name).mkdir(parents=True, exist_ok=True)
    from . import registro as log
    for name, text in ((GUIDE, GUIDE_TEXT), (log.REQUESTS_FILE, log.REQUESTS_TEXT), (log.REPOS_FILE, log.REPOS_TEXT)):
        if not (root / name).exists():
            (root / name).write_text(text, encoding="utf-8")
    return root


def _inputs(folder: Path, suffix: str) -> list[Path]:
    return sorted(p for p in folder.rglob(f"*{suffix}") if p.is_file() and not p.name.startswith("~$"))


def _bible(root: Path) -> str:
    folder = root / BIBLE_DIR
    if not folder.is_dir():
        return ""
    parts = []
    for d in load_local(folder):
        text = _read_local(folder / d.rel).strip()
        if len(text) > BIBLE_DOC_CHARS:
            text = text[:BIBLE_DOC_CHARS] + "\n\n[… recortado]"
        parts.append(f"### {d.title} (`{d.rel}`)\n\n{text}")
    return "\n\n".join(parts)


def _template(root: Path, exports: list[Path], level: int) -> Page | None:
    """Template for new pages: a «plantilla» document in the bible wins; otherwise the
    export page named like one, taken whole (with its child pages) at its own level."""
    folder = root / BIBLE_DIR
    if folder.is_dir():
        for d in load_local(folder):
            if TEMPLATE_TITLE.search(d.title) or TEMPLATE_TITLE.search(Path(d.rel).stem.replace("-", " ")):
                return Page(d.title, _read_local(folder / d.rel))
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


def _tasks(rows, pages: list[Page]) -> list[Task]:
    by_title = {p.title: p for p in pages}
    tasks: list[Task] = []
    for r in rows:
        if r.kind in ("update", "update_by_content"):
            page = by_title.get(r.match or r.title)
            tasks.append(Task("", "update", page.title if page else r.title, r.local, page))
    for r in rows:
        if r.kind == "new":  # instructions without a page stay in the report: map them by hand
            tasks.append(Task("", "new", r.title, r.local, None))
    for n, t in enumerate(tasks, 1):
        verb = "actualizar" if t.kind == "update" else "nueva"
        t.slug = f"{n:02d}-{verb}-{_slug(t.title)}"
    return tasks


def _prompt(task: Task, local_text: str, template: Page | None, bible: str) -> str:
    out = []
    if task.kind == "update":
        out += [f"# Tarea: actualizar la página «{task.title}» de Confluence", "",
                "Actúa como redactor técnico. Reescribe la página actual aplicando SOLO lo que "
                "piden las instrucciones de actualización; lo que no mencionan se conserva.", "",
                RULES.format(title=task.title, bible_rule=BIBLE_RULE if bible else NO_BIBLE_RULE),
                f"## Instrucciones de actualización (`{task.local_rel}`)", "", _demote(local_text), "",
                "## Página actual en Confluence", "", _demote(task.page.markdown if task.page else ""), ""]
    else:
        out += [f"# Tarea: página nueva «{task.title}»", "",
                "Actúa como redactor técnico. Convierte el borrador en una página de Confluence.", "",
                RULES.format(title=task.title, bible_rule=BIBLE_RULE if bible else NO_BIBLE_RULE)]
        if template and WANTS_TEMPLATE.search(local_text):
            out += [f"## Plantilla («{template.title}»)", "",
                    "Usa sus secciones y etiquetas en el mismo orden; «…» marca dónde va contenido. "
                    "Rellena sólo con lo que diga el borrador o la Biblia y deja `> PENDIENTE` en el resto.",
                    "", _demote(template_skeleton(template.markdown), 1), ""]
        out += [f"## Borrador local (`{task.local_rel}`)", "", _demote(local_text), ""]
    if bible:
        out += ["## Biblia (referencias que mandan)", "", _demote(bible, 1), ""]
    return "\n".join(out).rstrip() + "\n"


# ── Markdown → HTML (enough for a clean paste into Confluence) ────────────────

def _inline(text: str) -> str:
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img alt="\1" src="\2">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
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


def unsupported_terms(result: str, sources: str) -> list[str]:
    """Data-like terms in an AI result that appear nowhere in what the AI was given:
    figures, versions, acronyms, identifiers and proper names mid-sentence. A cheap,
    model-independent check for invented content before a page is approved."""
    folded = _fold(sources)
    found = set()
    for line in result.splitlines():
        for m in TOKEN.finditer(line):
            token = m.group(0).rstrip(".-/")
            if not token or not _looks_like_data(token, line[:m.start()]):
                continue
            pattern = r"(?<!\w)" + re.escape(_fold(token)) + r"(?!\w)"
            if not re.search(pattern, folded):
                found.add(token)
    return sorted(found)


PAGE_CSS = ("body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;"
            "line-height:1.5}table{border-collapse:collapse}td,th{border:1px solid #999;padding:.3rem .6rem}"
            "blockquote{border-left:4px solid #999;margin:0;padding-left:1rem}")


def _html_page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"<style>{PAGE_CSS}</style></head><body>\n{body}</body></html>\n")


def _publish(task_dir: Path, task: Task) -> list[str] | None:
    """Writes the paste-ready page and the change view; returns the unsupported terms."""
    result = task_dir / RESULT
    if not result.is_file():
        return None
    proposal = result.read_text(encoding="utf-8")
    unsupported = unsupported_terms(proposal, (task_dir / "TAREA.md").read_text(encoding="utf-8"))
    (task_dir / "PARA-CONFLUENCE.html").write_text(_html_page(task.title, markdown_to_html(proposal)),
                                                     encoding="utf-8")
    before_name = "ACTUAL.md" if task.page else "LOCAL.md"
    before = (task_dir / before_name).read_text(encoding="utf-8")
    diff = difflib.HtmlDiff(wrapcolumn=90).make_file(
        before.splitlines(), proposal.splitlines(),
        "Confluence hoy" if task.page else "Borrador local", "Propuesta", context=True, numlines=3)
    if unsupported:
        note = ("<p><b>Datos sin fuente</b> (no aparecen en nada de lo que se dio a la IA; "
                "compruébalos antes de aprobar): " + html.escape(", ".join(unsupported)) + "</p>")
        diff = diff.replace("<body>", "<body>\n" + note, 1)
    (task_dir / "CAMBIOS.html").write_text(diff, encoding="utf-8")
    return unsupported


def _index(out: Path, rows, tasks: list[Task], ready: dict[str, list[str]], level: int,
           sizes: dict[str, int], errors: dict[str, str] | None = None) -> str:
    counts = "".join(f"<li>{html.escape(label)}: <b>{sum(r.kind == k for r in rows)}</b></li>"
                     for k, label, _ in SECTIONS)
    trs = []
    for t in tasks:
        base = f"tareas/{t.slug}"
        links = [f'<a href="{base}/TAREA.md">TAREA.md</a>']
        if t.slug in ready:
            links += [f'<a href="{base}/CAMBIOS.html">CAMBIOS.html</a>',
                      f'<a href="{base}/PARA-CONFLUENCE.html">PARA-CONFLUENCE.html</a>']
        state = "listo" if t.slug in ready else "pendiente: falta RESULTADO.md"
        if ready.get(t.slug):
            n = len(ready[t.slug])
            state += f" · revisar {n} dato{'s' if n > 1 else ''} sin fuente"
        if (errors or {}).get(t.slug):
            state += f" · falló la IA: {html.escape(errors[t.slug])}"
        if sizes.get(t.slug, 0) > CHAT_LIMIT_CHARS:
            state += (f" · grande ({sizes[t.slug] // 1000}k caracteres): usa una IA de contexto largo "
                      "o divide el documento local por subpáginas")
        trs.append(f"<tr><td>{html.escape(t.slug)}</td><td>{html.escape(t.title)}</td>"
                   f"<td>{state}</td><td>{' · '.join(links)}</td></tr>")
    body = (f"<h1>Taller de documentación</h1><p>Páginas del export al nivel de encabezado {level}. "
            f'Informe completo: <a href="informe.md">informe.md</a>. '
            f'Qué cambió y quién: <a href="registro.html">registro.html</a>.</p><ul>{counts}</ul>'
            f"<h2>Tareas ({len(ready)}/{len(tasks)} listas)</h2><table><thead><tr><th>Carpeta</th>"
            f"<th>Página</th><th>Estado</th><th>Ficheros</th></tr></thead><tbody>{''.join(trs)}</tbody></table>")
    return _html_page("Taller de documentación", body)


def run_workspace(root: Path, embed=None, judge=None, ai: Ai | None = None, history=None,
                  router: Ai | None = None) -> dict:
    """`history` gives Confluence authors to the change log; `router` (default: `ai`) routes requests."""
    init_workspace(root)
    exports = _inputs(root / EXPORT_DIR, ".docx")
    local_root = root / LOCAL_DIR
    local = load_local(local_root)
    level = best_page_level(exports, local) if exports else 1
    pages = [p for e in exports for p in docx_to_pages(e, level)]
    rows = compare(pages, local, embed)
    if embed and judge:
        rows += find_contradictions(rows, pages, local, embed, judge)

    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "informe.md").write_text(render_report(rows), encoding="utf-8")

    template = _template(root, exports, level)
    bible = _bible(root)
    tasks = _tasks(rows, pages)
    ready: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    errors: dict[str, str] = {}
    for t in tasks:
        d = out / "tareas" / t.slug
        d.mkdir(parents=True, exist_ok=True)
        local_text = _read_local(local_root / t.local_rel)
        (d / "LOCAL.md").write_text(local_text, encoding="utf-8")
        if t.page:
            (d / "ACTUAL.md").write_text(t.page.markdown, encoding="utf-8")
        prompt = _prompt(t, local_text, template, bible)
        (d / "TAREA.md").write_text(prompt, encoding="utf-8")
        sizes[t.slug] = len(prompt)
        if ai and not (d / RESULT).exists():
            try:
                (d / RESULT).write_text(ai(prompt).strip() + "\n", encoding="utf-8")
            except Exception as exc:  # one failing task must not stop the rest
                errors[t.slug] = str(exc)
        unsupported = _publish(d, t)
        if unsupported is not None:
            ready[t.slug] = unsupported

    from . import registro as log
    done = {f"tareas/{t.slug}": t for t in tasks if t.slug in ready}
    changes = log.update_log(root, exports, pages, done, history, router or ai, template, bible)

    index = out / "index.html"
    index.write_text(_index(out, rows, tasks, ready, level, sizes, errors), encoding="utf-8")
    return {"page_level": level, "tasks": [t.slug for t in tasks], "ready": sorted(ready), "errors": errors,
            "index": index, "template": template.title if template else None,
            "log": out / log.LOG_HTML, "log_errors": changes["errors"]}


def openai_client(url: str, model: str, key: str = "", opener=urllib.request.urlopen,
                  timeout: float = 900) -> Ai:
    """Chat completions against any OpenAI-compatible API (Ollama, LM Studio, vLLM...)."""
    endpoint = url.rstrip("/") + "/chat/completions"

    def ask(prompt: str) -> str:
        body = {"model": model, "temperature": 0.2, "messages": [
            {"role": "system", "content": "Eres un redactor técnico. Responde solo con la página en Markdown."},
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
    "gemini": ["-p", "Sigue la tarea anterior.", "--output-format", "text"],
    # copilot ignores stdin when given -p, so the task goes only through the pipe.
    "copilot": ["-s", "--no-ask-user"],
}


def cli_client(engine: str, run=subprocess.run, which=shutil.which, timeout: float = 1800) -> Ai:
    """An installed agent CLI (Claude Code, Codex, Gemini, Copilot) as the AI.

    Each call runs in an empty temporary folder: the task carries everything the
    page needs, so the agent never has a reason to read the user's folders."""
    if engine not in ENGINES:
        raise ValueError(f"motor desconocido: {engine} (usa {', '.join(ENGINES)})")
    exe = which(engine)
    if not exe:
        raise RuntimeError(f"{engine} no está instalado o no está en el PATH")

    def ask(prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="amanuense-") as tmp:
            last = Path(tmp) / "last-message.md"
            args = [exe] + [a.replace("{last}", str(last)) for a in ENGINES[engine]]
            proc = run(args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=tmp)
            if proc.returncode != 0:
                raise RuntimeError(f"{engine} terminó con código {proc.returncode}: "
                                   f"{(proc.stderr or proc.stdout or '').strip()[-400:]}")
            answer = last.read_text(encoding="utf-8") if last.is_file() else proc.stdout
            if not answer.strip():
                raise RuntimeError(f"{engine} no devolvió texto")
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
    """Write the skills and agents of `src` (skills/<name>/SKILL.md, agentes/*.md,
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

    for agent in sorted((src / "agentes").glob("*.md")):
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="crea las carpetas del taller").add_argument("root", type=Path)
    agents = sub.add_parser("agents", help="escribe skills y agentes para Claude Code, Codex, Gemini y Copilot")
    agents.add_argument("dest", type=Path, help="raíz del repo donde dejarlos")
    agents.add_argument("--src", type=Path, default=Path(__file__).resolve().parent / "skeleton",
                        help="carpeta con skills/, agentes/ y AGENTS.md")
    run = sub.add_parser("run", help="analiza, prepara tareas y publica los RESULTADO.md")
    run.add_argument("root", type=Path)
    run.add_argument("--ai-url", default=os.environ.get("AMANUENSE_AI_URL", ""),
                     help="API compatible con OpenAI, p. ej. http://localhost:11434/v1")
    run.add_argument("--ai-model", default=os.environ.get("AMANUENSE_AI_MODEL", ""))
    run.add_argument("--ai-cli", default=os.environ.get("AMANUENSE_AI_CLI", ""), choices=["", *ENGINES],
                     help="usar un agente instalado: claude, codex, gemini o copilot")
    run.add_argument("--content", action="store_true", help="comparar también por contenido (RAG)")
    run.add_argument("--contradictions", action="store_true", help="con --content, juez de contradicciones")
    run.add_argument("--device", default=None)
    run.add_argument("--no-open", action="store_true", help="no abrir el navegador al terminar")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        print(init_workspace(a.root) / GUIDE)
        return
    if a.cmd == "agents":
        for path in export_agents(a.src, a.dest):
            print(path)
        return
    ai = None
    if a.ai_cli:
        ai = cli_client(a.ai_cli)
    elif a.ai_url:
        if not a.ai_model:
            ap.error("--ai-url necesita --ai-model (o AMANUENSE_AI_MODEL)")
        ai = openai_client(a.ai_url, a.ai_model, os.environ.get("AMANUENSE_AI_KEY", ""))
    embed = judge = None
    if a.content:
        embed = rag_embed(a.device)
        if a.contradictions:
            judge = rag_judge()
    from . import registro as log
    summary = run_workspace(a.root, embed, judge, ai, log.history_from_env())
    for warning in summary["log_errors"]:
        print("aviso:", warning)
    print(f"{len(summary['ready'])}/{len(summary['tasks'])} tareas listas")
    print(summary["index"])
    if not a.no_open:
        webbrowser.open(summary["index"].resolve().as_uri())


if __name__ == "__main__":
    main()
