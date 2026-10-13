import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense.confluence import (
    compare,
    docx_to_pages,
    find_contradictions,
    split_sentences,
    best_page_level,
    load_local,
    normalize_title,
    render_report,
    run,
)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text, style=None, numbered=False):
    ppr = ""
    if style or numbered:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        inner += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else ""
        ppr = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _table(rows):
    trs = "".join(
        "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows
    )
    return f"<w:tbl>{trs}</w:tbl>"


def _docx(path, body, styles=None):
    styles = styles or {"Heading1": "heading 1", "Heading2": "heading 2"}
    st = "".join(
        f'<w:style w:styleId="{sid}"><w:name w:val="{name}"/></w:style>' for sid, name in styles.items()
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
    return path


def test_docx_splits_pages_on_top_level_headings(tmp_path):
    body = (
        _p("Preamble text")
        + _p("Presentación del Brick", "Heading1")
        + _p("Intro paragraph")
        + _p("Detalle", "Heading2")
        + _p("First item", numbered=True)
        + _p("Coordinación", "Heading1")
        + _table([["Rol", "Persona"], ["Coordinación", "Rosa"]])
    )
    pages = docx_to_pages(_docx(tmp_path / "export.docx", body))

    assert [p.title for p in pages] == ["(sin título)", "Presentación del Brick", "Coordinación"]
    assert "Intro paragraph" in pages[1].markdown
    assert "## Detalle" in pages[1].markdown
    assert "- First item" in pages[1].markdown
    assert "| Rol | Persona |" in pages[2].markdown
    assert "| Coordinación | Rosa |" in pages[2].markdown


def test_docx_recognises_localized_heading_styles(tmp_path):
    body = _p("Arquitectura de referencia", "Ttulo1") + _p("Body")
    pages = docx_to_pages(_docx(tmp_path / "es.docx", body, {"Ttulo1": "heading 1"}))
    assert [p.title for p in pages] == ["Arquitectura de referencia"]


def test_normalize_title_ignores_accents_case_numbering_and_extension():
    assert normalize_title("01 - Presentación del BRICK.md") == normalize_title("presentacion del brick")


def test_load_local_detects_update_instructions(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text(
        "# Coordinación\n\n## Instrucciones de actualización\nCambiar X", encoding="utf-8"
    )
    (tmp_path / "b.md").write_text("Sin heading", encoding="utf-8")
    docs = {d.title: d for d in load_local(tmp_path)}
    assert docs["Coordinación"].has_update_instructions
    assert docs["Coordinación"].rel == "sub/a.md"
    assert not docs["b"].has_update_instructions


def test_compare_classifies_every_document(tmp_path):
    body = (
        _p("Presentación del Brick", "Heading1") + _p("old")
        + _p("Coordinación", "Heading1") + _p("old")
        + _p("Acciones habituales", "Heading1") + _p("old")
    )
    pages = docx_to_pages(_docx(tmp_path / "e.docx", body))
    local = tmp_path / "local"
    local.mkdir()
    (local / "coord.md").write_text("# Coordinacion\nInstrucciones de actualización: X", encoding="utf-8")
    (local / "pres.md").write_text("# Presentación del BRICK\nnuevo texto", encoding="utf-8")
    (local / "delivery.md").write_text("# Llegar a delivery\n...", encoding="utf-8")
    (local / "huerfana.md").write_text("# Página inexistente\nInstrucciones de actualización", encoding="utf-8")

    rows = {(r.kind, r.title) for r in compare(pages, load_local(local))}

    assert ("update", "Coordinación") in rows
    assert ("same_title_no_instructions", "Presentación del Brick") in rows
    assert ("new", "Llegar a delivery") in rows
    assert ("instructions_without_target", "Página inexistente") in rows
    assert ("confluence_only", "Acciones habituales") in rows


def test_render_report_and_run_write_outside_inputs(tmp_path):
    export = _docx(tmp_path / "e.docx", _p("Coordinación", "Heading1") + _p("old"))
    local = tmp_path / "local"
    local.mkdir()
    (local / "c.md").write_text("# Coordinación\nInstrucciones de actualización", encoding="utf-8")
    out = tmp_path / "out"

    report = run(export, local, out)

    assert report == out / "report.md"
    text = report.read_text(encoding="utf-8")
    assert "Coordinación" in text and "c.md" in text
    assert (out / "confluence_pages" / "coordinacion.md").exists()
    assert sorted(p.name for p in local.iterdir()) == ["c.md"]
    assert "# " in render_report([])


def _bow_embed(texts):
    """Bag-of-words cosine stand-in for the sentence model, deterministic and offline."""
    import math
    import re as _re

    tokenized = [set(_re.findall(r"\w+", t.lower())) for t in texts]
    vocab = sorted(set().union(*tokenized))
    vecs = []
    for toks in tokenized:
        v = [1.0 if w in toks else 0.0 for w in vocab]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        vecs.append([x / n for x in v])
    return vecs


def _content_fixture(tmp_path):
    body = (
        _p("Proceso de publicación", "Heading1")
        + _p("nexus versionado contrato metadatos repositorio licencia equipo soporte")
        + _p("Presentación del Brick", "Heading1")
        + _p("brick hmi equipo objetivos capacidades shell")
        + _p("Glosario", "Heading1")
        + _p("términos peers dependencias setup preference")
    )
    pages = docx_to_pages(_docx(tmp_path / "e.docx", body))
    local = tmp_path / "local"
    local.mkdir()
    (local / "publicar.md").write_text(
        "# Cómo publicar en Nexus\nInstrucciones de actualización\n"
        "nexus versionado contrato metadatos repositorio licencia equipo soporte",
        encoding="utf-8",
    )
    (local / "pres.md").write_text(
        "# Presentación del Brick\nbrick hmi equipo objetivos capacidades shell", encoding="utf-8"
    )
    (local / "glos-copia.md").write_text(
        "# Términos clave\ntérminos peers dependencias setup preference", encoding="utf-8"
    )
    (local / "deliveries.md").write_text(
        "# Llegar a delivery\nplantillas diarias jira ramas pull request", encoding="utf-8"
    )
    (local / "deliveries-old.md").write_text(
        "# Deliveries viejo\nplantillas diarias jira ramas pull request", encoding="utf-8"
    )
    return pages, load_local(local)


def test_content_matches_renamed_pages_and_flags_local_duplicates(tmp_path):
    pages, local = _content_fixture(tmp_path)
    rows = compare(pages, local, embed=_bow_embed, similar_min=0.7, dup_min=0.9)
    by = {(r.kind, r.title): r for r in rows}

    renamed = by[("update_by_content", "Cómo publicar en Nexus")]
    assert renamed.match == "Proceso de publicación" and renamed.score > 0.7
    assert by[("similar_content", "Términos clave")].match == "Glosario"
    assert by[("same_title_no_instructions", "Presentación del Brick")].score > 0.99
    dups = [r for r in rows if r.kind == "local_duplicate"]
    assert [{d.local, d.match} for d in dups] == [{"deliveries.md", "deliveries-old.md"}]
    assert not any(r.kind == "confluence_only" for r in rows)


def test_content_below_threshold_stays_new(tmp_path):
    pages, local = _content_fixture(tmp_path)
    rows = compare(pages, local, embed=_bow_embed, similar_min=0.7, dup_min=0.9)
    assert ("new", "Llegar a delivery") in {(r.kind, r.title) for r in rows}


def test_report_shows_content_matches_with_scores(tmp_path):
    pages, local = _content_fixture(tmp_path)
    text = render_report(compare(pages, local, embed=_bow_embed, similar_min=0.7, dup_min=0.9))
    assert "Cómo publicar en Nexus" in text and "≈ Proceso de publicación (1.00)" in text
    assert "deliveries-old.md" in text


def _neg_judge(premises, hypotheses, calls=None):
    """Stand-in NLI: a pair contradicts when exactly one side carries a 'no'."""
    if calls is not None:
        calls.extend(zip(premises, hypotheses))
    neg = lambda t: " no " in f" {t.lower()} "
    return [0.9 if neg(a) != neg(b) else 0.1 for a, b in zip(premises, hypotheses)]


def _contradiction_fixture(tmp_path):
    body = (
        _p("Publicación en Nexus", "Heading1")
        + _p("Una versión publicada se puede sobrescribir en Nexus por el equipo responsable.")
        + _p("El contrato de metadatos incluye licencia y canal de soporte del equipo.")
    )
    pages = docx_to_pages(_docx(tmp_path / "e.docx", body))
    local = tmp_path / "local"
    local.mkdir()
    (local / "nexus.md").write_text(
        "# Publicación en Nexus\n"
        "Una versión publicada no se puede sobrescribir en Nexus por el equipo responsable.\n"
        "El contrato de metadatos incluye licencia y canal de soporte del equipo.\n"
        "Las vistas no se versionan porque viven dentro de cada capacidad desplegada.",
        encoding="utf-8",
    )
    docs = load_local(local)
    return pages, docs, compare(pages, docs, embed=_bow_embed, similar_min=0.7, dup_min=0.9)


def test_split_sentences_skips_headings_tables_and_fragments():
    text = "# Title\n| a | b |\nCorto.\nPrimera frase con contenido real. Segunda frase con contenido real!"
    assert split_sentences(text) == [
        "Primera frase con contenido real.",
        "Segunda frase con contenido real!",
    ]


def test_find_contradictions_reports_opposed_sentences_only(tmp_path):
    pages, docs, rows = _contradiction_fixture(tmp_path)
    calls = []
    found = find_contradictions(
        rows, pages, docs, embed=_bow_embed, judge=lambda a, b: _neg_judge(a, b, calls)
    )

    assert len(found) == 1
    c = found[0]
    assert (c.kind, c.title, c.local, c.match) == (
        "contradiction", "Publicación en Nexus", "nexus.md", "Publicación en Nexus"
    )
    assert "se puede sobrescribir" in c.detail and "no se puede sobrescribir" in c.detail
    assert c.score == 0.9
    assert all("contrato de metadatos" not in a for a, _ in calls)


def test_find_contradictions_without_linked_pairs_is_empty(tmp_path):
    pages, docs, _ = _contradiction_fixture(tmp_path)
    assert find_contradictions([], pages, docs, embed=_bow_embed, judge=_neg_judge) == []


def test_report_lists_contradictions_with_both_sentences(tmp_path):
    pages, docs, rows = _contradiction_fixture(tmp_path)
    rows += find_contradictions(rows, pages, docs, embed=_bow_embed, judge=_neg_judge)
    text = render_report(rows)
    assert "## Contradicciones (1)" in text
    assert "no se puede sobrescribir" in text


def test_load_local_reads_word_documents(tmp_path):
    body = (_p("Convenciones de nomenclatura", "Heading1")
            + _p("Instrucciones de actualización: cambiar el prefijo a HMI-")
            + _p("Las ramas usan el prefijo HMI-"))
    _docx(tmp_path / "convenciones.docx", body)
    _docx(tmp_path / "sin-titulo.docx", _p("Solo texto"))
    docs = {d.rel: d for d in load_local(tmp_path)}
    conv = docs["convenciones.docx"]
    assert conv.title == "Convenciones de nomenclatura"
    assert conv.has_update_instructions
    assert "prefijo HMI-" in conv.body
    assert "Convenciones de nomenclatura" not in conv.body
    assert docs["sin-titulo.docx"].title == "sin-titulo"


def test_best_page_level_follows_the_local_titles(tmp_path):
    body = (_p("Brick IHM", "Heading1") + _p("Desarrollo", "Heading2") + _p("a")
            + _p("Coordinación", "Heading2") + _p("b") + _p("Detalle", "Heading3"))
    export = _docx(tmp_path / "export.docx", body,
                   {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"})
    local = tmp_path / "local"
    local.mkdir()
    for name in ("Desarrollo", "Coordinación", "Otra cosa"):
        (local / f"{name}.md").write_text(f"# {name}\ntexto\n", encoding="utf-8")
    assert best_page_level([export], load_local(local)) == 2
    assert best_page_level([export], []) == 1


def test_compare_matches_a_unique_title_contained_in_another(tmp_path):
    from amanuense.confluence import LocalDoc, Page
    pages = [Page("Convenciones de nomenclatura y trazabilidad", "# x\ncuerpo\n"),
             Page("Capacidades", "# c\n"), Page("Capacidades (Brick IHM)", "# d\n")]
    local = [LocalDoc("Convenciones", "conv.md", True, "cuerpo"),
             LocalDoc("Capacidades Brick", "cap.md", False, "x")]
    rows = {r.local: r for r in compare(pages, local) if r.local}
    assert rows["conv.md"].kind == "update_by_content"
    assert rows["conv.md"].match == "Convenciones de nomenclatura y trazabilidad"
    assert rows["conv.md"].detail == "título parecido"
    assert rows["cap.md"].kind == "similar_content"
    assert rows["cap.md"].match == "Capacidades (Brick IHM)"


def test_best_page_level_counts_similar_titles_when_none_is_exact(tmp_path):
    body = (_p("Brick IHM", "Heading1") + _p("Coordinación", "Heading2")
            + _p("Convenciones de nomenclatura y trazabilidad", "Heading3") + _p("x"))
    export = _docx(tmp_path / "export.docx", body,
                   {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"})
    local = tmp_path / "local"
    local.mkdir()
    (local / "conv.md").write_text("# Convenciones\nInstrucciones de actualización: x\n", encoding="utf-8")
    assert best_page_level([export], load_local(local)) == 3


def test_table_cell_paragraphs_stay_apart(tmp_path):
    cell = _p("Nombre: Route Planner") + _p("Estado: industrialized")
    body = _p("Plantilla", "Heading1") + f"<w:tbl><w:tr><w:tc>{_p('Resumen')}</w:tc></w:tr><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"
    page = docx_to_pages(_docx(tmp_path / "t.docx", body))[0]
    assert "| Nombre: Route Planner<br>Estado: industrialized |" in page.markdown


def test_content_mode_explains_that_it_needs_obsidian_search(monkeypatch):
    import pytest
    from amanuense import confluence
    monkeypatch.setitem(sys.modules, "obsidian_rag", None)
    for build in (confluence.rag_embed, confluence.rag_judge):
        with pytest.raises(SystemExit, match="obsidian-search"):
            build()
