"""revision: what a reviewer sees and decides, page by page, before anything reaches Confluence."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amanuense import registro as log  # noqa: E402
from amanuense import revision  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_taller import _workspace  # noqa: E402

UPDATE = "tareas/01-actualizar-convenciones-de-nomenclatura"
NEW = "tareas/02-nueva-capacidad-de-mapas"
COMMIT = {"when": "2026-10-14T09:00:00Z", "what": "feat: x", "files": [], "page": ""}


def _ready(tmp_path, proposal="# Convenciones de nomenclatura\n\nLas ramas usan PROJ-.\n"):
    ws = _workspace(tmp_path)
    docs_kit.run_workspace(ws)
    out = ws / docs_kit.OUT_DIR
    (out / UPDATE / "RESULTADO.md").write_text(proposal, encoding="utf-8")
    (out / NEW / "RESULTADO.md").write_text("# Capacidad de mapas\n\nMapas.\n", encoding="utf-8")
    docs_kit.run_workspace(ws)
    return ws


def _by_title(ws):
    return {p["title"]: p for p in revision.proposals(ws)}


def test_one_proposal_per_page_with_its_origin_and_kind(tmp_path):
    ws = _ready(tmp_path)
    found = _by_title(ws)
    assert set(found) == {"Convenciones de nomenclatura", "Capacidad de mapas"}
    update, new = found["Convenciones de nomenclatura"], found["Capacidad de mapas"]
    assert update["rel"] == UPDATE and not update["new"] and new["new"]
    assert update["origin"]["kind"] == "docs" and update["status"] == "pendiente"


def test_a_chained_code_task_wins_over_the_page_task(tmp_path):
    ws = _ready(tmp_path)
    out = ws / docs_kit.OUT_DIR
    task = out / "codigo" / "convenciones-de-nomenclatura-abc123"
    task.mkdir(parents=True)
    (task / "ACTUAL.md").write_text("# Convenciones de nomenclatura\n", encoding="utf-8")
    (task / "RESULTADO.md").write_text("# Convenciones de nomenclatura\n\nCon código.\n", encoding="utf-8")
    (task / log.TRIAGE_FILE).write_text(json.dumps({"categoria": "encadenar", "motivo": "m", "cambios": []}),
                                        encoding="utf-8")
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    entries += [{"id": "c1", "kind": "codigo", "repo": "tracks", "branch": "develop", "by": "Ana", **COMMIT,
                 "task_pages": {"codigo/convenciones-de-nomenclatura-abc123": "Convenciones de nomenclatura"}},
                {"id": "t1", "kind": "taller", "when": "2026-10-14T10:00:00Z", "by": "x", "what": "w",
                 "page": "Convenciones de nomenclatura",
                 "task": "codigo/convenciones-de-nomenclatura-abc123"}]
    (out / log.LOG_JSON).write_text(json.dumps(entries), encoding="utf-8")

    page = _by_title(ws)["Convenciones de nomenclatura"]
    assert page["rel"] == "codigo/convenciones-de-nomenclatura-abc123"
    assert page["origin"] == {"kind": "chained", "by": [], "repos": ["tracks@develop"]}
    assert UPDATE in page["others"]


def test_notices_and_conflicts_are_counted(tmp_path):
    ws = _ready(tmp_path, "# Convenciones de nomenclatura\n\n> PENDIENTE: la versión\n\n"
                          "> CONFLICTO: el repo dice dev\n")
    page = _by_title(ws)["Convenciones de nomenclatura"]
    assert page["notices"] == ["PENDIENTE: la versión", "CONFLICTO: el repo dice dev"]
    assert page["conflicts"] == 1


def test_approve_then_publish_then_a_new_export_reopens_an_approval(tmp_path):
    ws = _ready(tmp_path)
    revision.approve(ws, UPDATE, by="Alex")
    assert _by_title(ws)["Convenciones de nomenclatura"]["status"] == "aprobada"

    (ws / docs_kit.OUT_DIR / UPDATE / "ACTUAL.md").write_text("# Otro texto en MIND\n", encoding="utf-8")
    page = _by_title(ws)["Convenciones de nomenclatura"]
    assert page["status"] == "pendiente" and page["stale"]

    revision.approve(ws, UPDATE, by="Alex")
    revision.mark_published(ws, UPDATE, by="Alex", mode="manual", url="https://mind/x", version=None)
    page = _by_title(ws)["Convenciones de nomenclatura"]
    assert page["status"] == "publicada" and page["published"]["mode"] == "manual"


def test_publishing_with_open_conflicts_is_refused(tmp_path):
    ws = _ready(tmp_path, "# Convenciones de nomenclatura\n\n> CONFLICTO: el repo dice dev\n")
    try:
        revision.approve(ws, UPDATE, by="Alex")
    except revision.ReviewError as exc:
        assert "CONFLICTO" in str(exc)
    else:
        raise AssertionError("approved with an open conflict")


def test_editing_keeps_the_ai_version_and_reopens_the_review(tmp_path):
    ws = _ready(tmp_path)
    out = ws / docs_kit.OUT_DIR / UPDATE
    original = (out / "RESULTADO.md").read_text(encoding="utf-8")
    revision.approve(ws, UPDATE, by="Alex")
    revision.save_text(ws, UPDATE, "# Convenciones de nomenclatura\n\nRetocado.\n", by="Alex")
    revision.save_text(ws, UPDATE, "# Convenciones de nomenclatura\n\nRetocado otra vez.\n", by="Alex")

    assert (out / "RESULTADO.ia.md").read_text(encoding="utf-8") == original  # the first, never overwritten
    assert "Retocado otra vez." in (out / "PARA-CONFLUENCE.html").read_text(encoding="utf-8")
    assert _by_title(ws)["Convenciones de nomenclatura"]["status"] == "pendiente"


def test_a_conflict_is_resolved_by_replacing_its_line(tmp_path):
    ws = _ready(tmp_path, "# Convenciones de nomenclatura\n\n> CONFLICTO: el repo dice dev\n\nResto.\n")
    revision.resolve_notice(ws, UPDATE, "CONFLICTO: el repo dice dev", "Apariencia es básica.", by="Alex")
    text = (ws / docs_kit.OUT_DIR / UPDATE / "RESULTADO.md").read_text(encoding="utf-8")
    assert "CONFLICTO" not in text and "Apariencia es básica.\n\nResto." in text
    revision.approve(ws, UPDATE, by="Alex")  # nothing open any more


def test_rework_asks_the_ai_with_the_instruction_and_the_current_text(tmp_path):
    ws = _ready(tmp_path)
    seen = []
    revision.rework(ws, UPDATE, "quita la sección de ramas",
                    lambda p: seen.append(p) or "# Convenciones de nomenclatura\n\nSin ramas.\n", by="Alex")
    assert "quita la sección de ramas" in seen[0] and "Las ramas usan PROJ-." in seen[0]
    assert "Sin ramas." in (ws / docs_kit.OUT_DIR / UPDATE / "RESULTADO.md").read_text(encoding="utf-8")


def test_every_review_action_is_in_the_log(tmp_path):
    ws = _ready(tmp_path)
    revision.approve(ws, UPDATE, by="Alex")
    revision.discard(ws, NEW, by="Alex", reason="ya existe en otro espacio")
    entries = json.loads((ws / docs_kit.OUT_DIR / log.LOG_JSON).read_text(encoding="utf-8"))
    mine = [e for e in entries if e["kind"] == "revision"]
    assert [(e["by"], e["task"]) for e in mine] == [("Alex", UPDATE), ("Alex", NEW)]
    assert "ya existe en otro espacio" in mine[1]["what"]
    assert _by_title(ws)["Capacidad de mapas"]["status"] == "descartada"


def test_triaged_out_tasks_are_listed_and_can_be_promoted(tmp_path):
    ws = _ready(tmp_path)
    out = ws / docs_kit.OUT_DIR
    task = out / "codigo" / "pagina-antigua-def456"
    task.mkdir(parents=True)
    (task / "ACTUAL.md").write_text("# Página antigua\n", encoding="utf-8")
    (task / log.TRIAGE_FILE).write_text(json.dumps({"categoria": "ruido", "motivo": "solo tests"}),
                                        encoding="utf-8")
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    entries.append({"id": "c2", "kind": "codigo", "repo": "r", "branch": "b", "by": "Ana", **COMMIT,
                    "task_pages": {"codigo/pagina-antigua-def456": "Página antigua"}})
    (out / log.LOG_JSON).write_text(json.dumps(entries), encoding="utf-8")

    [left] = revision.set_aside(ws)
    assert left == {"rel": "codigo/pagina-antigua-def456", "title": "Página antigua",
                    "categoria": "ruido", "motivo": "solo tests"}
    revision.promote(ws, left["rel"], by="Alex")
    verdict = json.loads((task / log.TRIAGE_FILE).read_text(encoding="utf-8"))
    assert verdict["categoria"] == "actualizar" and "Alex" in verdict["motivo"]
    assert revision.set_aside(ws) == []


def test_deliver_still_picks_the_same_pages(tmp_path):
    ws = _ready(tmp_path)
    folder = docs_kit.deliver_workspace(ws, today="2026-10-14")
    assert (folder / "paginas" / "Convenciones de nomenclatura").is_dir()
    assert (folder / "nuevas" / "Capacidad de mapas").is_dir()


def test_deliver_leaves_out_discarded_pages(tmp_path):
    ws = _ready(tmp_path)
    revision.discard(ws, NEW, by="Alex", reason="no hace falta")
    folder = docs_kit.deliver_workspace(ws, today="2026-10-14")
    assert not (folder / "nuevas").exists()
