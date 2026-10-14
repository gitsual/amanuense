"""The workshop speaks English by default and Spanish on request; a workshop that already
has its Spanish folders keeps speaking Spanish without being told."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n, obsidian  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_taller import _docx, _p  # noqa: E402

EN_INPUTS = ["1-confluence-export", "2-my-docs", "3-bible", "GUIDE.md", "repos.txt", "requests.md"]
ES_INPUTS = ["1-export-confluence", "2-mi-documentacion", "3-biblia", "LEEME.md", "repos.txt", "peticiones.md"]


@pytest.fixture(autouse=True)
def _no_lang_env(monkeypatch):
    monkeypatch.delenv("AMANUENSE_LANG", raising=False)


def _names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def _english_workshop(tmp_path) -> Path:
    ws = docs_kit.init_workspace(tmp_path / "ws")
    _docx(ws / "1-confluence-export" / "export.docx",
          _p("Route Planner", "Heading1") + _p("Deployment", "Heading2") + _p("The service listens on port 8080.")
          + _p("Old page", "Heading2") + _p("Nobody migrated this."))
    (ws / "2-my-docs" / "Deployment.md").write_text(
        "# Deployment\n\nUpdate instructions: the port is now 8443.\n", encoding="utf-8")
    (ws / "2-my-docs" / "Weather layer.md").write_text("# Weather layer\n\nShows the forecast.\n", encoding="utf-8")
    return ws


def test_a_new_workshop_is_english_by_default(tmp_path):
    assert _names(docs_kit.init_workspace(tmp_path / "ws")) == sorted(EN_INPUTS)
    assert "Update instructions:" in (tmp_path / "ws" / "GUIDE.md").read_text(encoding="utf-8")


def test_lang_es_builds_the_spanish_workshop(tmp_path, monkeypatch):
    assert _names(docs_kit.init_workspace(tmp_path / "a", lang="es")) == sorted(ES_INPUTS)
    monkeypatch.setenv("AMANUENSE_LANG", "es")
    assert _names(docs_kit.init_workspace(tmp_path / "b")) == sorted(ES_INPUTS)


def test_an_existing_spanish_workshop_stays_spanish(tmp_path):
    ws = docs_kit.init_workspace(tmp_path / "ws", lang="es")
    assert i18n.detect(ws) == "es"
    summary = docs_kit.run_workspace(ws)
    assert summary["index"] == ws / "salida" / "index.html"
    assert not (ws / "1-confluence-export").exists()
    assert "Taller de documentación" in summary["index"].read_text(encoding="utf-8")


def test_unknown_language_is_refused(tmp_path):
    with pytest.raises(ValueError):
        docs_kit.init_workspace(tmp_path / "ws", lang="fr")


def test_english_run_writes_english_tasks_and_pages(tmp_path):
    ws = _english_workshop(tmp_path)
    summary = docs_kit.run_workspace(ws)
    out = ws / "output"
    assert summary["index"] == out / "index.html"
    assert summary["tasks"] == ["01-update-deployment", "02-new-weather-layer"]
    task = (out / "tasks" / "01-update-deployment" / "TASK.md").read_text(encoding="utf-8")
    assert task.startswith("# Task: update the Confluence page \"Deployment\"")
    assert "## Update instructions (`Deployment.md`)" in task and "## Rules" in task
    assert "> PENDING:" in task and "## Change log" in task
    assert (out / "tasks" / "01-update-deployment" / "CURRENT.md").is_file()
    assert "## Update in Confluence (1)" in (out / "report.md").read_text(encoding="utf-8")
    index = summary["index"].read_text(encoding="utf-8")
    assert "Documentation workshop" in index and "pending: RESULT.md missing" in index
    assert '<html lang="en">' in index


def test_english_result_becomes_paste_ready_page_and_change_view(tmp_path):
    ws = _english_workshop(tmp_path)
    docs_kit.run_workspace(ws)
    task = ws / "output" / "tasks" / "01-update-deployment"
    (task / "RESULT.md").write_text("# Deployment\n\nThe service listens on port 8443 behind Nginx.\n",
                                    encoding="utf-8")
    summary = docs_kit.run_workspace(ws)
    assert summary["ready"] == ["01-update-deployment"]
    assert "<h1>Deployment</h1>" in (task / "FOR-CONFLUENCE.html").read_text(encoding="utf-8")
    changes = (task / "CHANGES.html").read_text(encoding="utf-8")
    assert "Confluence today" in changes and "Proposal" in changes
    assert "<b>Data without a source</b>" in changes and "Nginx" in changes
    index = summary["index"].read_text(encoding="utf-8")
    assert "ready · check 1 unsourced item" in index
    log = (ws / "output" / "log.html").read_text(encoding="utf-8")
    assert "<h1>Change log</h1>" in log and "proposal ready for review" in log


def test_both_markers_work_in_either_language(tmp_path):
    ws = _english_workshop(tmp_path)
    (ws / "2-my-docs" / "Deployment.md").write_text(
        "# Deployment\n\nInstrucciones de actualización: el puerto pasa a 8443.\n", encoding="utf-8")
    assert docs_kit.run_workspace(ws)["tasks"][0] == "01-update-deployment"


def test_english_requests_are_routed_with_english_keys(tmp_path):
    ws = _english_workshop(tmp_path)
    (ws / "requests.md").write_text("- Ana: the port is 8443 now\n", encoding="utf-8")
    prompts = []

    def router(prompt):
        prompts.append(prompt)
        return '{"page": "Deployment", "change": "port 8443", "reason": "new proxy"}'

    docs_kit.run_workspace(ws, router=router)
    assert "## Request from Ana" in prompts[0]
    log = (ws / "output" / "log.html").read_text(encoding="utf-8")
    assert "<b>What:</b> port 8443" in log and "<b>Why:</b> new proxy" in log
    assert (ws / "output" / "requests").is_dir()


def test_obsidian_index_note_follows_the_language(tmp_path):
    export = _docx(tmp_path / "export.docx", _p("Space", "Heading1") + _p("Hello."))
    obsidian.export_to_vault(export, tmp_path / "vault")
    assert "# Confluence export" in (tmp_path / "vault" / "_index.md").read_text(encoding="utf-8")
    i18n.use("es")
    try:
        obsidian.export_to_vault(export, tmp_path / "vault-es")
    finally:
        i18n.use("en")
    assert "# Export de Confluence" in (tmp_path / "vault-es" / "_index.md").read_text(encoding="utf-8")


def test_cli_help_and_messages_follow_lang(tmp_path, capsys):
    docs_kit.main(["--lang", "es", "init", str(tmp_path / "ws")])
    assert capsys.readouterr().out.strip().endswith("LEEME.md")
    docs_kit.main(["init", str(tmp_path / "ws2")])
    assert capsys.readouterr().out.strip().endswith("GUIDE.md")
    docs_kit.main(["init", str(tmp_path / "ws3"), "--lang", "es"])
    assert capsys.readouterr().out.strip().endswith("LEEME.md")
