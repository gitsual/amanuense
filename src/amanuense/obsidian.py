"""
obsidian.py — Pasa un «Export to Word» de Confluence a un vault de Obsidian.

Los niveles de encabezado del export son el árbol de páginas:
  H1 = página raíz (una carpeta con _index.md), H2 = página hija (una nota),
  H3 = nieta (la hija pasa a carpeta con _index.md y una nota por nieta).
Los encabezados más profundos se quedan dentro de su nota. Las imágenes van a
_media/ y se insertan como ![[nombre]]. Sólo biblioteca estándar.

Uso:
  amanuense obsidian EXPORT.docx VAULT/MIND [--force]
"""
from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .confluence import NS, W, _heading_levels, _style_level, _table, _text

REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
MEDIA_DIR = "_media"
INDEX = "_index"
SKIP_TITLES = {"table of contents", "índice", "indice", "contenido"}


def safe_name(title: str) -> str:
    """A file name every OS and Obsidian accept."""
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", title)
    return re.sub(r"\s+", " ", name).strip(" .")[:90] or "sin título"


def _images(z: zipfile.ZipFile) -> dict[str, str]:
    """Relationship id → path of the image inside the .docx."""
    rels = "word/_rels/document.xml.rels"
    if rels not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(rels)):
        if rel.get("Type", "").endswith("/image") and rel.get("TargetMode") != "External":
            out[rel.get("Id")] = posixpath.normpath(posixpath.join("word", rel.get("Target", "")))
    return out


def _blocks(path: Path, media: dict[str, bytes]) -> list[tuple[int, str]]:
    """The body as (heading level, text) pairs; level 0 is a plain Markdown line."""
    with zipfile.ZipFile(path) as z:
        levels = _heading_levels(z)
        images = _images(z)
        body = ET.fromstring(z.read("word/document.xml")).find("w:body", NS)
        names = {rid: posixpath.basename(target) for rid, target in images.items()}
        for rid, target in images.items():
            if target in z.namelist():
                media[names[rid]] = z.read(target)
    out: list[tuple[int, str]] = []
    for el in body:
        if el.tag == W + "tbl":
            out += [(0, "")] + [(0, l) for l in _table(el)] + [(0, "")]
            continue
        if el.tag != W + "p":
            continue
        text = _text(el)
        style = el.find("w:pPr/w:pStyle", NS)
        level = _style_level(style.get(W + "val"), levels) if style is not None else 0
        if level and text:
            out.append((level, text))
            continue
        if text:
            out.append((0, ("- " if el.find("w:pPr/w:numPr", NS) is not None else "") + text))
        for blip in el.iter(BLIP):
            name = names.get(blip.get(REL + "embed"))
            if name:
                out.append((0, f"![[{name}]]"))
    return out


def _split(blocks: list[tuple[int, str]], level: int):
    """[(title, blocks)] cut at headings of exactly `level`; the preamble has title None."""
    parts, title, buf = [], None, []
    for lvl, text in blocks:
        if lvl == level:
            if title is not None or buf:
                parts.append((title, buf))
            title, buf = text, []
        else:
            buf.append((lvl, text))
    if title is not None or buf:
        parts.append((title, buf))
    return parts


def _markdown(blocks: list[tuple[int, str]], note_level: int) -> list[str]:
    lines = []
    for lvl, text in blocks:
        if lvl:
            lines += ["", "#" * min(6, lvl - note_level + 1) + " " + text, ""]
        else:
            lines.append(text)
    return lines


class _Vault:
    def __init__(self, root: Path):
        self.root, self.notes, self.taken = root, {}, set()

    def reserve(self, folder: Path, name: str) -> Path:
        path, n = folder / f"{name}.md", 2
        while path in self.taken:
            path, n = folder / f"{name} ({n}).md", n + 1
        self.taken.add(path)
        return path

    def link(self, path: Path, label: str) -> str:
        return f"- [[{path.relative_to(self.root).with_suffix('').as_posix()}|{label}]]"

    def put(self, path: Path, title: str, body: list[str], links_title: str = "", links=()) -> None:
        lines = [f"# {title}", ""] + body
        if links:
            lines += ["", f"## {links_title}", ""] + list(links)
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
        self.notes[path] = text


def export_to_vault(export: Path, vault: Path, force: bool = False) -> dict:
    """Writes the export as notes under `vault`; refuses to overwrite unless `force`."""
    export, vault = Path(export), Path(vault)
    media: dict[str, bytes] = {}
    blocks = _blocks(export, media)
    v = _Vault(vault)
    top_links = []
    for top, top_blocks in _split(blocks, 1):
        if top is None or top.strip().lower() in SKIP_TITLES:
            continue
        folder = vault / safe_name(top)
        top_index = v.reserve(folder, INDEX)
        pages = _split(top_blocks, 2)
        intro = pages.pop(0)[1] if pages and pages[0][0] is None else []
        page_links = []
        for page, page_blocks in pages:
            subs = _split(page_blocks, 3)
            head = subs.pop(0)[1] if subs and subs[0][0] is None else []
            if subs:
                sub_folder = folder / safe_name(page)
                page_index = v.reserve(sub_folder, INDEX)
                sub_links = []
                for sub, sub_blocks in subs:
                    target = v.reserve(sub_folder, safe_name(sub))
                    v.put(target, sub, _markdown(sub_blocks, 3))
                    sub_links.append(v.link(target, sub))
                v.put(page_index, page, _markdown(head, 2), "Subpáginas", sub_links)
                page_links.append(v.link(page_index, page))
            else:
                target = v.reserve(folder, safe_name(page))
                v.put(target, page, _markdown(head, 2))
                page_links.append(v.link(target, page))
        v.put(top_index, top, _markdown(intro, 1), "Páginas", page_links)
        top_links.append(v.link(top_index, top))
    v.put(vault / f"{INDEX}.md", "Export de Confluence", [f"Origen: `{export.name}`"], "Páginas", top_links)

    clashes = [p for p in v.notes if p.exists()]
    if clashes and not force:
        raise FileExistsError(f"{len(clashes)} notas ya existen (p. ej. {clashes[0]}); usa --force para reescribirlas")
    for path, text in v.notes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if media:
        (vault / MEDIA_DIR).mkdir(parents=True, exist_ok=True)
        for name, data in media.items():
            (vault / MEDIA_DIR / name).write_bytes(data)
    return {"notes": len(v.notes), "media": len(media), "vault": vault}
