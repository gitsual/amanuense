"""obsidian: a Confluence Word export (page + children) as an Obsidian vault."""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import obsidian, taller  # noqa: E402

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


def test_cli_rerun_explains_instead_of_crashing(tmp_path):
    import pytest
    from amanuense import taller
    args = ["obsidian", str(_export(tmp_path)), str(tmp_path / "v")]
    taller.main(args)
    with pytest.raises(SystemExit) as stop:
        taller.main(args)
    assert "--force" in str(stop.value.code)


# ── a whole workshop becomes a vault ──────────────────────────────────────────

def _workshop(tmp_path):
    from amanuense import i18n
    ws = tmp_path / "ws"
    export = ws / i18n.name("export")
    export.mkdir(parents=True)
    _export(tmp_path).rename(export / "Bricks.docx")
    (ws / i18n.name("local")).mkdir()
    (ws / i18n.name("local") / "Contrato.md").write_text("# Contrato\n", encoding="utf-8")
    (ws / i18n.name("bible")).mkdir()
    (ws / i18n.name("bible") / "Norma.md").write_text("# Norma\n", encoding="utf-8")
    return ws


def test_workshop_becomes_a_vault_with_mind_local_and_bible(tmp_path):
    from amanuense import i18n
    ws, vault = _workshop(tmp_path), tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    done = obsidian.workshop_to_vault(ws, vault)
    assert (vault / "MIND" / "Bricks" / "_index.md").exists()
    assert (vault / i18n.name("local") / "Contrato.md").read_text(encoding="utf-8") == "# Contrato\n"
    assert (vault / i18n.name("bible") / "Norma.md").exists()
    assert (vault / ".obsidian" / "app.json").exists(), "the vault's own settings are never touched"
    assert done["notes"] == 8 and done["copied"] == 2


def test_workshop_rerun_needs_force_and_then_regenerates(tmp_path):
    import pytest
    ws, vault = _workshop(tmp_path), tmp_path / "vault"
    obsidian.workshop_to_vault(ws, vault)
    with pytest.raises(FileExistsError):
        obsidian.workshop_to_vault(ws, vault)
    stale = vault / "MIND" / "Old page.md"
    stale.write_text("# Old\n", encoding="utf-8")
    obsidian.workshop_to_vault(ws, vault, force=True)
    assert not stale.exists(), "the derived tree is rebuilt, not merged"
    assert (vault / "MIND" / "Bricks" / "_index.md").exists()


def test_workshop_without_export_explains(tmp_path):
    import pytest
    from amanuense import i18n
    ws = tmp_path / "ws"
    (ws / i18n.name("export")).mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        obsidian.workshop_to_vault(ws, tmp_path / "vault")


def test_cli_obsidian_accepts_a_workshop(tmp_path, capsys):
    from amanuense import taller
    taller.main(["obsidian", str(_workshop(tmp_path)), str(tmp_path / "vault")])
    out = capsys.readouterr().out
    assert "8" in out and str(tmp_path / "vault") in out


# ── a vault must never overlap the workshop, and a failed rebuild keeps the old one ──

def _snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _overlaps(tmp_path):
    from amanuense import i18n
    ws = _workshop(tmp_path)
    (ws / i18n.name("out")).mkdir()
    return ws, {"equal": ws, "contains": tmp_path, "in_local": ws / i18n.name("local") / "vault",
                "in_export": ws / i18n.name("export") / "vault", "in_out": ws / i18n.name("out") / "vault"}


@pytest.mark.parametrize("where", ["equal", "contains", "in_local", "in_export", "in_out"])
def test_a_vault_that_overlaps_the_workshop_is_refused_and_nothing_is_deleted(tmp_path, where):
    ws, vaults = _overlaps(tmp_path)
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError):
        obsidian.workshop_to_vault(ws, vaults[where], force=True)
    assert _snapshot(tmp_path) == before


def test_the_workshop_vault_folder_is_a_valid_vault_and_leaves_the_sources_alone(tmp_path):
    """<workshop>/vault is the documented layout (amanuense.sh vault, settings default)."""
    from amanuense import i18n
    ws = _workshop(tmp_path)
    sources = {k: _snapshot(ws / i18n.name(k)) for k in ("export", "local", "bible")}
    for _ in range(2):  # a rebuild over the previous vault, as the vault job does
        done = obsidian.workshop_to_vault(ws, ws / "vault", force=True)
    assert done["vault"] == ws / "vault"
    assert (ws / "vault" / i18n.name("local") / "Contrato.md").is_file()
    assert {k: _snapshot(ws / i18n.name(k)) for k in sources} == sources


def test_the_cli_reports_an_overlapping_vault_without_a_traceback(tmp_path, capsys):
    ws = _workshop(tmp_path)
    with pytest.raises(SystemExit) as e:
        taller.main(["obsidian", str(ws), str(ws), "--force"])
    assert str(e.value).startswith("✗ ")


def test_a_vault_reached_through_a_symlink_to_the_workshop_is_refused(tmp_path):
    ws = _workshop(tmp_path)
    link = tmp_path / "alias"
    try:
        link.symlink_to(ws, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")
    before = _snapshot(ws)
    with pytest.raises(ValueError):
        obsidian.workshop_to_vault(ws, link, force=True)
    assert _snapshot(ws) == before


def test_a_failed_rebuild_leaves_the_old_vault_byte_identical_and_no_temp_dirs(tmp_path, monkeypatch):
    ws, vault = _workshop(tmp_path), tmp_path / "vault"
    obsidian.workshop_to_vault(ws, vault)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    before = _snapshot(vault)
    names = sorted(p.name for p in vault.iterdir())

    def boom(*_a, **_k):
        raise RuntimeError("broken docx")
    monkeypatch.setattr(obsidian, "export_to_vault", boom)
    with pytest.raises(RuntimeError, match="broken docx"):
        obsidian.workshop_to_vault(ws, vault, force=True)
    assert _snapshot(vault) == before
    assert sorted(p.name for p in vault.iterdir()) == names, "no temporary folder is left behind"


def test_a_failed_copy_also_keeps_the_old_vault(tmp_path, monkeypatch):
    ws, vault = _workshop(tmp_path), tmp_path / "vault"
    obsidian.workshop_to_vault(ws, vault)
    before = _snapshot(vault)

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(obsidian.shutil, "copytree", boom)
    with pytest.raises(OSError):
        obsidian.workshop_to_vault(ws, vault, force=True)
    assert _snapshot(vault) == before
    assert {p.name for p in vault.iterdir()} == {key.split("/")[0] for key in before}


def test_a_failed_rollback_keeps_the_old_data_and_says_where(tmp_path, monkeypatch):
    ws, vault = _workshop(tmp_path), tmp_path / "vault"
    obsidian.workshop_to_vault(ws, vault)
    marker = vault / "MIND" / "Mine.md"
    marker.write_text("precious\n", encoding="utf-8")
    real = obsidian.os.replace

    def flaky(src, dst):
        parts = Path(src).parts
        if ".old" in parts:  # rollback: aside -> vault
            raise OSError("rollback denied")
        if Path(src).parent.name.startswith(".amanuense-new-"):  # placing the new subtrees
            raise OSError("place denied")
        return real(src, dst)
    monkeypatch.setattr(obsidian.os, "replace", flaky)
    with pytest.raises(OSError, match=r"\.amanuense-new-") as info:
        obsidian.workshop_to_vault(ws, vault, force=True)
    assert "rollback denied" in str(info.value) or "place denied" in str(info.value)
    kept = [p for p in vault.rglob("Mine.md")]
    assert kept and kept[0].read_text(encoding="utf-8") == "precious\n"
    assert ".old" in kept[0].parts
