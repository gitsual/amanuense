#!/usr/bin/env python3
"""
confluence_docs.py — Export de Confluence (Word) ↔ carpeta local. NO DESTRUCTIVO.

Pensado para una carpeta de documentación con dos fuentes mezcladas:
  * el último «Export to Word» de una sección de Confluence (página + hijos);
  * una estructura local nueva, con ficheros nuevos y ficheros viejos que llevan
    unas «instrucciones de actualización» y el mismo título que su página.

Qué hace:
  1. Parte el .docx en una página por encabezado de nivel 1 (sólo stdlib: un
     .docx es un zip con XML) y escribe cada página como Markdown.
  2. Empareja páginas y documentos locales por título normalizado.
  3. Con --content, empareja además por contenido (embeddings): páginas
     renombradas, copias con otro título y duplicados dentro de la carpeta local.
     Con --contradictions, enfrenta frase a frase cada pareja y un juez NLI marca
     las que se contradicen.
  4. Clasifica cada documento y escribe un report.md.

Clases del informe:
  update                       mismo título y el local trae instrucciones
  same_title_no_instructions   mismo título sin instrucciones (¿duplicado o versión nueva?)
  new                          sólo en local, sin instrucciones
  instructions_without_target  trae instrucciones pero no hay página que actualizar
  update_by_content            trae instrucciones y su página aparece por contenido (renombrada)
  similar_content              sin instrucciones, se parece a una página con otro título
  local_duplicate              dos documentos locales casi iguales
  contradiction                frase local opuesta a su frase gemela en la pareja
  confluence_only              página de Confluence sin equivalente local

Nunca escribe en las carpetas de entrada: todo va a --out.

Uso:
  python -m amanuense.confluence EXPORT.docx CARPETA_LOCAL --out DIR [--content [--contradictions]]
"""
from __future__ import annotations

import argparse
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import i18n

Embed = Callable[[list[str]], Sequence[Sequence[float]]]
# (premisas, hipótesis) → P(contradicción) alineada.
Judge = Callable[[list[str], list[str]], Sequence[float]]

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{%s}" % NS["w"]
LOCAL_EXTENSIONS = {".md", ".txt", ".docx"}
UPDATE_MARKER = re.compile(r"instrucciones\s+de\s+actualizaci[oó]n|update\s+instructions", re.IGNORECASE)
UNTITLED_TITLES = {i18n.TEXT["untitled"][lang] for lang in i18n.LANGS}


@dataclass
class Page:
    title: str
    markdown: str


@dataclass
class LocalDoc:
    title: str
    rel: str
    has_update_instructions: bool
    body: str = ""


@dataclass
class Row:
    kind: str
    title: str
    local: str = ""
    match: str = ""
    score: float | None = None
    detail: str = ""


def normalize_title(title: str) -> str:
    t = re.sub(r"\.(md|txt|docx)$", "", title.strip(), flags=re.IGNORECASE)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^\s*\d+(\.\d+)*\s*[-_.)]*\s*", "", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _slug(title: str) -> str:
    return normalize_title(title).replace(" ", "-") or "pagina"


def _heading_levels(z: zipfile.ZipFile) -> dict[str, int]:
    """styleId → nivel, leyendo el nombre del estilo (los ids cambian con el idioma)."""
    levels: dict[str, int] = {}
    if "word/styles.xml" not in z.namelist():
        return levels
    for st in ET.fromstring(z.read("word/styles.xml")).iter(W + "style"):
        name = st.find("w:name", NS)
        m = re.fullmatch(r"heading (\d)", (name.get(W + "val") if name is not None else "").lower())
        if m:
            levels[st.get(W + "styleId")] = int(m.group(1))
    return levels


def _style_level(style_id: str, levels: dict[str, int]) -> int:
    if style_id in levels:
        return levels[style_id]
    m = re.fullmatch(r"(?:heading|t[ií]?tulo|ttulo)\s*(\d)", style_id.lower())
    return int(m.group(1)) if m else 0


def _text(el: ET.Element) -> str:
    out = []
    for node in el.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag == W + "br":
            out.append(" ")
    return "".join(out).strip()


def _cell(tc: ET.Element) -> str:
    """Cell text with its paragraphs kept apart, so «Nombre: x» and «Estado: y» never fuse."""
    paras = [t for t in (_text(p) for p in tc.iter(W + "p")) if t]
    return "<br>".join(paras or [_text(tc)]).replace("|", "\\|")


def _table(tbl: ET.Element) -> list[str]:
    rows = [[_cell(tc) for tc in tr.findall("w:tc", NS)] for tr in tbl.findall("w:tr", NS)]
    if not rows:
        return []
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * len(rows[0])]
    return lines + ["| " + " | ".join(r) + " |" for r in rows[1:]]


def docx_to_pages(path: Path, page_level: int = 1) -> list[Page]:
    with zipfile.ZipFile(path) as z:
        levels = _heading_levels(z)
        body = ET.fromstring(z.read("word/document.xml")).find("w:body", NS)

    pages: list[Page] = []
    title, lines = None, []

    def flush():
        if title is not None or any(l.strip() for l in lines):
            pages.append(Page(title or i18n.t("untitled"), "\n".join(lines).strip() + "\n"))

    for el in body:
        if el.tag == W + "tbl":
            lines += [""] + _table(el) + [""]
            continue
        if el.tag != W + "p":
            continue
        text = _text(el)
        style = el.find("w:pPr/w:pStyle", NS)
        level = _style_level(style.get(W + "val"), levels) if style is not None else 0
        if level and level <= page_level and text:
            flush()
            title, lines = text, [f"# {text}", ""]
        elif level and text:
            lines += ["", "#" * (level - page_level + 1) + " " + text, ""]
        elif text:
            lines.append(("- " if el.find("w:pPr/w:numPr", NS) is not None else "") + text)
    flush()
    return pages


def _content(markdown: str) -> str:
    """Texto comparable: sin el título (se compara aparte) ni la marca de instrucciones."""
    lines = markdown.splitlines()
    if lines and re.match(r"^#\s", lines[0]):
        lines = lines[1:]
    return "\n".join(l for l in lines if not UPDATE_MARKER.search(l)).strip()


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def split_sentences(text: str, min_chars: int = 25, max_chars: int = 320) -> list[str]:
    """Frases comparables: fuera encabezados, filas de tabla y fragmentos cortos."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", line).strip()
        if not line or line.startswith(("#", "|", ">")):
            continue
        out += [f.strip() for f in re.split(r"(?<=[.!?])\s+", line)
                if min_chars <= len(f.strip()) <= max_chars]
    return out


def _read_local(p: Path) -> str:
    if p.suffix.lower() != ".docx":
        return p.read_text(encoding="utf-8", errors="replace")
    return "\n".join(pg.markdown for pg in docx_to_pages(p))


def load_local(root: Path) -> list[LocalDoc]:
    docs = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in LOCAL_EXTENSIONS or p.name.startswith("~$"):
            continue
        text = _read_local(p)
        h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        body = text[:h1.start()] + text[h1.end():] if h1 else text
        docs.append(LocalDoc(h1.group(1).strip() if h1 else p.stem, p.relative_to(root).as_posix(),
                             bool(UPDATE_MARKER.search(text)), _content(body)))
    return docs


def best_page_level(exports: Sequence[Path], local: list[LocalDoc], levels: Sequence[int] = (1, 2, 3)) -> int:
    """Heading level that opens a page: the one whose titles match most local titles.

    A Confluence «page + children» export writes the page tree as heading levels,
    so a local folder that mirrors its pages tells which level they live at. Exact
    titles count first; titles that only resemble a page break the tie."""
    best, best_hits = levels[0], (0, 0)
    for level in levels:
        pages = [p for e in exports for p in docx_to_pages(e, level)]
        titles = {normalize_title(p.title) for p in pages}
        exact = sum(normalize_title(d.title) in titles for d in local)
        similar = sum(normalize_title(d.title) not in titles and _similar_title(d.title, pages) is not None
                      for d in local)
        if (exact, similar) > best_hits:
            best, best_hits = level, (exact, similar)
    return best


def _similar_title(title: str, pages: list[Page]) -> int | None:
    """Page whose title contains this one's words (or the reverse), if one is clearly closest."""
    words = set(normalize_title(title).split())
    if not words:
        return None
    scored = []
    for i, p in enumerate(pages):
        other = set(normalize_title(p.title).split())
        if other and (words <= other or other <= words):
            scored.append((len(words & other) / len(words | other), i))
    scored.sort(reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def compare(pages: list[Page], local: list[LocalDoc], embed: Embed | None = None,
            similar_min: float = 0.75, dup_min: float = 0.85) -> list[Row]:
    """Sin `embed` sólo cruza títulos. Con `embed` (textos → vectores normalizados)
    puntúa cada pareja, busca por contenido la página de lo que no casa por título y
    señala duplicados locales."""
    pages = [p for p in pages if p.title not in UNTITLED_TITLES]
    by_title = {normalize_title(p.title): i for i, p in enumerate(pages)}
    sims = None
    if embed and pages and local:
        vecs = embed([_content(p.markdown) for p in pages] + [d.body for d in local])
        pv, lv = vecs[:len(pages)], vecs[len(pages):]
        sims = [[_cos(l, p) for p in pv] for l in lv]

    matched: set[int] = set()
    rows = []
    for li, d in enumerate(local):
        pi = by_title.get(normalize_title(d.title))
        if pi is not None:
            matched.add(pi)
            kind = "update" if d.has_update_instructions else "same_title_no_instructions"
            rows.append(Row(kind, pages[pi].title, d.rel, score=sims[li][pi] if sims else None))
            continue
        pi = _similar_title(d.title, pages)
        if pi is not None:
            matched.add(pi)
            kind = "update_by_content" if d.has_update_instructions else "similar_content"
            rows.append(Row(kind, d.title, d.rel, pages[pi].title,
                            sims[li][pi] if sims else None, i18n.t("similar_title")))
            continue
        if sims:
            best = max(range(len(pages)), key=lambda j: sims[li][j])
            if sims[li][best] >= similar_min:
                matched.add(best)
                kind = "update_by_content" if d.has_update_instructions else "similar_content"
                rows.append(Row(kind, d.title, d.rel, pages[best].title, sims[li][best]))
                continue
        kind = "instructions_without_target" if d.has_update_instructions else "new"
        rows.append(Row(kind, d.title, d.rel))
    rows += [Row("confluence_only", p.title) for i, p in enumerate(pages) if i not in matched]

    if embed and len(local) > 1:
        lv = embed([d.body for d in local])
        for i in range(len(local)):
            for j in range(i + 1, len(local)):
                s = _cos(lv[i], lv[j])
                if s >= dup_min:
                    rows.append(Row("local_duplicate", local[i].title, local[i].rel, local[j].rel, s))
    return rows


LINKED = {"update", "same_title_no_instructions", "update_by_content", "similar_content",
          "local_duplicate"}


def find_contradictions(rows: list[Row], pages: list[Page], local: list[LocalDoc], embed: Embed,
                        judge: Judge, sim_min: float = 0.6, sim_max: float = 0.985,
                        threshold: float = 0.5) -> list[Row]:
    """Para cada pareja enlazada, junta cada frase local con su gemela más próxima
    del otro lado. Las casi idénticas (≥ sim_max) no se juzgan; el resto pasa por
    el juez y quedan las que superan `threshold`."""
    page_text = {p.title: _content(p.markdown) for p in pages}
    local_by_rel = {d.rel: d for d in local}
    found = []
    for r in rows:
        if r.kind not in LINKED or r.local not in local_by_rel:
            continue
        other = r.match or r.title
        ref = local_by_rel[other].body if r.kind == "local_duplicate" else page_text.get(other, "")
        a, b = split_sentences(ref), split_sentences(local_by_rel[r.local].body)
        if not a or not b:
            continue
        vecs = embed(a + b)
        va, vb = vecs[:len(a)], vecs[len(a):]
        pairs = []
        for j, v in enumerate(vb):
            i = max(range(len(a)), key=lambda k: _cos(va[k], v))
            if sim_min <= _cos(va[i], v) < sim_max:
                pairs.append((a[i], b[j]))
        if not pairs:
            continue
        for (pa, pb), p in zip(pairs, judge([x for x, _ in pairs], [y for _, y in pairs])):
            if p >= threshold:
                found.append(Row("contradiction", r.title, r.local, other, round(float(p), 2),
                                 f"«{pa}» ↔ «{pb}»"))
    return found


_SECTIONS = {
    "en": [
        ("update", "Update in Confluence", "The local document carries instructions for its page."),
        ("same_title_no_instructions", "Same title, no instructions",
         "A duplicate of the export or an unmarked new version? Check by hand."),
        ("instructions_without_target", "Instructions without a target page",
         "They carry update instructions but the export has no such page (renamed or deleted?)."),
        ("update_by_content", "Update in Confluence (renamed page)",
         "They carry instructions; their page has another title but the same content."),
        ("similar_content", "Similar content under another title",
         "A copy of the export, a rename or a pending merge?"),
        ("local_duplicate", "Duplicates in local", "Two nearly identical local documents: keep one."),
        ("contradiction", "Contradictions",
         "Reference sentence ↔ local sentence. Under \"Update\" it may be the intended change; elsewhere, check it."),
        ("new", "New in local", "Candidates for a new page."),
        ("confluence_only", "Only in Confluence", "Pages with no local counterpart: current, obsolete or not migrated yet."),
    ],
    "es": [
        ("update", "Actualizar en Confluence", "El documento local trae instrucciones para su página."),
        ("same_title_no_instructions", "Mismo título, sin instrucciones",
         "¿Duplicado del export o versión nueva sin marcar? Revisar a mano."),
        ("instructions_without_target", "Instrucciones sin página destino",
         "Traen instrucciones de actualización pero el export no tiene esa página (¿renombrada o borrada?)."),
        ("update_by_content", "Actualizar en Confluence (página renombrada)",
         "Traen instrucciones; su página tiene otro título pero el mismo contenido."),
        ("similar_content", "Contenido parecido con otro título",
         "¿Copia del export, renombrado o fusión pendiente?"),
        ("local_duplicate", "Duplicados en local", "Dos documentos locales casi iguales: quedarse con uno."),
        ("contradiction", "Contradicciones",
         "Frase de referencia ↔ frase local. En «Actualizar» puede ser el cambio buscado; en el resto, revisar."),
        ("new", "Nuevos en local", "Candidatos a página nueva."),
        ("confluence_only", "Sólo en Confluence", "Páginas sin equivalente local: vigentes, obsoletas o pendientes de migrar."),
    ],
}


def sections() -> list[tuple[str, str, str]]:
    """(kind, label, hint) of every report section, in the current language."""
    return _SECTIONS[i18n.current()]


def _line(r: Row) -> str:
    line = f"- {r.title}" + (f" — `{r.local}`" if r.local else "")
    if r.kind == "local_duplicate":
        line += f" ≈ `{r.match}`"
    elif r.match:
        line += f" ≈ {r.match}"
    line += f" ({r.score:.2f})" if r.score is not None else ""
    return line + (f"\n  - {r.detail}" if r.detail else "")


def render_report(rows: list[Row]) -> str:
    out = [i18n.t("report_title"), ""]
    out += [f"- {label}: **{sum(r.kind == k for r in rows)}**" for k, label, _ in sections()]
    for kind, label, hint in sections():
        group = [r for r in rows if r.kind == kind]
        if not group:
            continue
        out += ["", f"## {label} ({len(group)})", "", f"_{hint}_", ""]
        out += [_line(r) for r in group]
    return "\n".join(out) + "\n"


def run(export: Path, local_root: Path, out: Path, page_level: int = 1,
        embed: Embed | None = None, judge: Judge | None = None) -> Path:
    exports = sorted(export.glob("*.docx")) if export.is_dir() else [export]
    pages = [p for e in exports for p in docx_to_pages(e, page_level)]
    pages_dir = out / "confluence_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    for p in pages:
        name, n = _slug(p.title), 2
        while name in used:
            name, n = f"{_slug(p.title)}-{n}", n + 1
        used.add(name)
        (pages_dir / f"{name}.md").write_text(p.markdown, encoding="utf-8")
    report = out / "report.md"
    local = load_local(local_root)
    rows = compare(pages, local, embed)
    if embed and judge:
        rows += find_contradictions(rows, pages, local, embed, judge)
    report.write_text(render_report(rows), encoding="utf-8")
    return report


RAG_MISSING = ("--content needs obsidian-search installed in this Python "
               "(https://github.com/gitsual/obsidian-search): its embeddings and NLI judge do the comparison")


def rag_embed(device: str | None = None) -> Embed:
    """Embeddings from obsidian-search, the optional companion that compares by meaning."""
    try:
        from obsidian_rag import common
    except ImportError as exc:
        raise SystemExit(RAG_MISSING) from exc
    model = common.get_model(device=device)
    return lambda texts: model.encode([t[:2000] for t in texts], normalize_embeddings=True,
                                      convert_to_numpy=True, show_progress_bar=False).tolist()


def rag_judge():
    try:
        from obsidian_rag import nli_judge
    except ImportError as exc:
        raise SystemExit(RAG_MISSING) from exc
    return nli_judge.score_contradiction


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("export", type=Path, help=".docx exportado de Confluence, o carpeta de .docx")
    ap.add_argument("local", type=Path, help="carpeta local de documentación")
    ap.add_argument("--out", type=Path, required=True, help="carpeta de salida (fuera de las entradas)")
    ap.add_argument("--page-level", type=int, default=1, help="nivel de encabezado que abre página")
    ap.add_argument("--content", action="store_true",
                    help="comparar también por contenido con el modelo de embeddings del RAG")
    ap.add_argument("--contradictions", action="store_true",
                    help="con --content, buscar frases contradictorias con el juez NLI (mDeBERTa)")
    ap.add_argument("--device", default=None, help="cpu o cuda (por defecto, el que haya)")
    a = ap.parse_args(argv)
    for src in (a.export, a.local):
        if a.out.resolve().is_relative_to(src.resolve()):
            ap.error(f"--out no puede estar dentro de {src}")
    embed = None
    if a.content:
        embed = rag_embed(a.device)
    judge = None
    if a.contradictions:
        if not embed:
            ap.error("--contradictions necesita --content")
        judge = rag_judge()
    print(run(a.export, a.local, a.out, a.page_level, embed, judge))


if __name__ == "__main__":
    main()
