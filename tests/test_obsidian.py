"""obsidian: a Confluence Word export (page + children) as an Obsidian vault."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import obsidian  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
STYLES = {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"}
PNG = b"\x89PNG\r\n\x1a\nfake"


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _img(rid):
    return f'<w:p><w:r><w:drawing><a:blip r:embed="{rid}"/></w:drawing></w:r></w:p>'


def _docx(path, body):
    st = "".join(f'<w:style w:styleId="{k}"><w:name w:val="{v}"/></w:style>' for k, v in STYLES.items())
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/image1.png"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W} {R} {A}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/media/image1.png", PNG)
    return path


def _export(tmp_path):
    body = (_p("Bricks", "Heading1") + _p("Portada del espacio.")
            + _p("Route Planner", "Heading2") + _p("Planifica rutas.") + _img("rId9")
            + _p("Contratos", "Heading3") + _p("RouteRequest v2")
            + _p("Despliegue", "Heading3") + _p("Puerto 8443")
            + _p("Weather Layer", "Heading2") + _p("Capa de meteorología.")
            + _p("Plantillas", "Heading1") + _p("Brick Template", "Heading2") + _p("Nombre: …"))
    return _docx(tmp_path / "Bricks.docx", body)


def test_export_becomes_a_tree_of_notes(tmp_path):
    vault = tmp_path / "vault" / "MIND"
    summary = obsidian.export_to_vault(_export(tmp_path), vault)
    notes = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md"))
    assert notes == [
        "Bricks/Route Planner/Contratos.md", "Bricks/Route Planner/Despliegue.md",
        "Bricks/Route Planner/_index.md", "Bricks/Weather Layer.md", "Bricks/_index.md",
        "Plantillas/Brick Template.md", "Plantillas/_index.md", "_index.md"]
    assert summary == {"notes": 8, "media": 1, "vault": vault}
    planner = (vault / "Bricks/Route Planner/_index.md").read_text(encoding="utf-8")
    assert planner.startswith("# Route Planner\n")
    assert "Planifica rutas." in planner and "![[image1.png]]" in planner
    assert "[[Bricks/Route Planner/Contratos|Contratos]]" in planner
    assert (vault / "_media" / "image1.png").read_bytes() == PNG
    top = (vault / "Bricks/_index.md").read_text(encoding="utf-8")
    assert "Portada del espacio." in top and "[[Bricks/Weather Layer|Weather Layer]]" in top
    assert "[[Bricks/_index|Bricks]]" in (vault / "_index.md").read_text(encoding="utf-8")


def test_unsafe_titles_and_duplicates_get_distinct_files(tmp_path):
    body = (_p("A/B: C?", "Heading1") + _p("Pág", "Heading2") + _p("uno")
            + _p("Pág", "Heading2") + _p("dos"))
    vault = tmp_path / "v"
    obsidian.export_to_vault(_docx(tmp_path / "x.docx", body), vault)
    names = sorted(p.name for p in (vault / "A B C").glob("*.md"))
    assert names == ["Pág (2).md", "Pág.md", "_index.md"]


def test_rerun_refuses_to_overwrite_without_force(tmp_path):
    vault = tmp_path / "v"
    export = _export(tmp_path)
    obsidian.export_to_vault(export, vault)
    (vault / "Bricks/Weather Layer.md").write_text("mi nota\n", encoding="utf-8")
    import pytest
    with pytest.raises(FileExistsError):
        obsidian.export_to_vault(export, vault)
    obsidian.export_to_vault(export, vault, force=True)
    assert "Capa de meteorología." in (vault / "Bricks/Weather Layer.md").read_text(encoding="utf-8")


def test_cli_obsidian_command(tmp_path, capsys):
    from amanuense import taller
    taller.main(["obsidian", str(_export(tmp_path)), str(tmp_path / "v")])
    assert "8 notas" in capsys.readouterr().out
