"""service: the framework-free core both the stdlib app and the FastAPI router drive."""
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amanuense import i18n, intake, mind, revision, service  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from test_revision import NEW, UPDATE, _ready  # noqa: E402


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AMANUENSE_USER", "Alex")
    for k in ("AMANUENSE_CONFLUENCE_URL", "AMANUENSE_CONFLUENCE_TOKEN", "AMANUENSE_AI_CLI", "AMANUENSE_AI_URL"):
        monkeypatch.delenv(k, raising=False)
    return service.Workshop(_ready(tmp_path, "# Convenciones de nomenclatura\n\n> CONFLICTO: dev\n\nResto.\n"))


@pytest.fixture
def blocking(monkeypatch):
    """A comparison that waits until the test lets it go."""
    gate = threading.Event()
    monkeypatch.setattr(docs_kit, "run_workspace",
                        lambda *a, **k: gate.wait(5) and {"ready": [], "tasks": [], "log_errors": []})
    yield gate
    gate.set()


def _wait(job):
    for _ in range(300):
        if not job.running():
            return
        threading.Event().wait(0.02)
    raise AssertionError("job did not finish")


# ── Job ────────────────────────────────────────────────────────────────────────

def test_a_second_job_is_refused_and_the_first_state_is_untouched():
    job, gate = service.Job(), threading.Event()
    job.start("first", lambda: gate.wait(5) and "done")
    before = job.snapshot()
    with pytest.raises(service.Busy):
        job.start("second", lambda: "never")
    assert job.snapshot() == before and before["name"] == "first" and before["running"]
    gate.set()
    _wait(job)
    assert job.snapshot()["result"] == "done" and not job.snapshot()["running"]


def test_a_new_job_starts_once_the_previous_one_finished_and_errors_are_kept():
    job = service.Job()
    job.start("boom", lambda: 1 / 0)
    _wait(job)
    assert job.snapshot()["error"] == "division by zero" and job.snapshot()["result"] is None
    job.start("ok", lambda: "fine")
    _wait(job)
    assert job.snapshot()["name"] == "ok" and job.snapshot()["result"] == "fine" and job.snapshot()["error"] == ""


def test_snapshot_is_a_copy():
    job = service.Job()
    job.snapshot()["name"] = "tampered"
    assert job.snapshot()["name"] == ""


# ── Reads ──────────────────────────────────────────────────────────────────────

def test_state_without_texts_lists_the_pages(workshop):
    state = workshop.state(texts=False)
    assert "texts" not in state
    assert {p["title"] for p in state["proposals"]} == {"Convenciones de nomenclatura", "Capacidad de mapas"}
    assert state["user"] == "Alex" and state["lang"] == "es" and state["workspace"] == str(workshop.root)


def test_state_with_texts_carries_the_ui_labels(workshop):
    assert workshop.state()["texts"]["ui_run"] == "Buscar cambios"


def test_detail_has_opcodes_and_the_preview(workshop):
    page = workshop.detail(UPDATE)
    assert "Resto." in page["result"] and "<blockquote>" in page["preview"]
    assert page["diff"] and all({"op", "a", "b", "a_start", "b_start"} <= set(row) for row in page["diff"])
    assert {row["op"] for row in page["diff"]} & {"insert", "replace"}


def test_diff_marks_equal_and_changed_runs():
    rows = service.diff("a\nb\nc", "a\nB\nc")
    assert [r["op"] for r in rows] == ["equal", "replace", "equal"]
    assert rows[1]["a"] == ["b"] and rows[1]["b"] == ["B"] and rows[1]["a_start"] == 2


def test_unknown_page_is_a_review_error(workshop):
    with pytest.raises(revision.ReviewError):
        workshop.detail("tareas/nope")


def test_preview_escapes_html(workshop):
    assert "<script>" not in workshop.act("preview", {"markdown": "<script>alert(1)</script>"})["html"]


# ── Writes and jobs ────────────────────────────────────────────────────────────

def test_act_walks_a_review_and_returns_the_page(workshop):
    with pytest.raises(revision.ReviewError):
        workshop.act("approve", {"rel": UPDATE})  # the conflict is open
    page = workshop.act("resolve", {"rel": UPDATE, "notice": "CONFLICTO: dev", "decision": "Apariencia."})
    assert page["proposal"]["conflicts"] == 0
    assert workshop.act("approve", {"rel": UPDATE})["proposal"]["status"] == "aprobada"


def test_act_needs_its_fields_and_knows_its_actions(workshop):
    with pytest.raises(ValueError):
        workshop.act("approve", {})
    with pytest.raises(service.Unknown):
        workshop.act("shutdown", {})


def test_edits_wait_while_a_job_runs_but_read_only_actions_do_not(workshop, blocking):
    workshop.start_job("run", {})
    with pytest.raises(service.Busy):
        workshop.act("approve", {"rel": NEW})
    assert "html" in workshop.act("preview", {"markdown": "x"})
    assert workshop.job.snapshot()["running"]
    blocking.set()
    _wait(workshop.job)
    assert workshop.act("approve", {"rel": NEW})["proposal"]["status"] == "aprobada"


def test_read_only_actions_are_the_documented_ones():
    assert service.READS_ONLY == {"preview", "preflight", "settings/test", "intake/plan"}


def test_jobs_are_the_documented_ones_and_unknown_names_are_refused(workshop):
    assert service.JOBS == {"run", "intake", "radiator", "deliver", "rework"}
    with pytest.raises(service.Unknown):
        workshop.start_job("bogus", {})
    with pytest.raises(ValueError):
        workshop.start_job("rework", {"rel": UPDATE})  # no instruction


def test_a_second_job_while_one_runs_is_busy(workshop, blocking):
    assert workshop.start_job("run", {})["running"]
    with pytest.raises(service.Busy):
        workshop.start_job("radiator", {})


def test_upload_while_a_job_runs_is_busy_and_big_files_are_refused(workshop, blocking, monkeypatch):
    workshop.start_job("run", {})
    with pytest.raises(service.Busy):
        workshop.upload("b", "f.txt", None, 1, "")
    blocking.set()
    _wait(workshop.job)
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 10)
    with pytest.raises(intake.TooBig):
        workshop.upload("b", "f.txt", None, 11, "")


def test_only_batches_started_here_can_be_cancelled(workshop):
    batch = workshop.act("intake/start", {})["batch"]
    assert workshop.act("intake/cancel", {"batch": batch}) == {"ok": True}
    with pytest.raises(ValueError):
        workshop.act("intake/cancel", {"batch": batch})  # gone, and no longer ours


def test_a_failed_cancel_leaves_the_batch_cancellable(workshop, monkeypatch):
    batch = workshop.act("intake/start", {})["batch"]

    def locked(_folder):
        raise PermissionError("file in use")
    monkeypatch.setattr(service.shutil, "rmtree", locked)
    with pytest.raises(PermissionError):
        workshop.act("intake/cancel", {"batch": batch})
    assert batch in workshop._started  # still ours: the reviewer can retry
    monkeypatch.undo()
    assert workshop.act("intake/cancel", {"batch": batch}) == {"ok": True}
    assert batch not in workshop._started


def test_cancelling_a_batch_whose_folder_is_already_gone_succeeds(workshop):
    batch = workshop.act("intake/start", {})["batch"]
    service.shutil.rmtree(service.intake.batch_dir(workshop.root, batch))
    assert workshop.act("intake/cancel", {"batch": batch}) == {"ok": True}
    assert batch not in workshop._started


def test_a_job_at_rest_already_reports_its_progress_shape():
    assert service.Job().snapshot()["progress"] == {"stage": "", "done": 0, "total": 0}


def test_rework_checks_the_ai_engine_before_the_fields(workshop, monkeypatch):
    with pytest.raises(ValueError, match=i18n.t("ui_ai_not_configured")):
        workshop.start_job("rework", {})  # no fields either: the engine is reported first
    monkeypatch.setenv("AMANUENSE_AI_CLI", "claude")
    monkeypatch.setattr(docs_kit, "cli_client", lambda name: object())
    with pytest.raises(ValueError, match="rel"):
        workshop.start_job("rework", {})  # engine ok: now the missing fields are reported


def test_target_resolves_known_places_and_refuses_the_rest(workshop):
    assert workshop.target("workspace") == workshop.root
    with pytest.raises(ValueError):
        workshop.target("delivery")  # nothing delivered yet


# ── Token and errors ───────────────────────────────────────────────────────────

def test_tokens_are_long_unique_and_compared_exactly():
    a, b = service.new_token(), service.new_token()
    assert len(a) >= 24 and a != b
    assert service.check_token(a, a) and not service.check_token(a, b)
    assert not service.check_token(a, None) and not service.check_token(a, "") and not service.check_token(a, a + "x")
    assert service.TOKEN_HEADER == "X-Amanuense-Token"


@pytest.mark.parametrize("exc, code", [
    (service.Busy(), 423),
    (revision.ReviewError("open conflict"), 409),
    (intake.TooBig("too big"), 413),
    (mind.MindError("down"), 400),
    (ValueError("bad"), 400),
    (FileNotFoundError("gone"), 400),
    (service.Unknown("nope"), 404),
])
def test_error_status_maps_known_errors(exc, code):
    status, body = service.error_status(exc)
    assert status == code
    expected = {423: i18n.t("ui_busy"), 404: "not found"}.get(code, str(exc))
    assert body == {"error": expected}


def test_error_status_hides_nothing_on_a_crash(capsys):
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        assert service.error_status(exc) == (500, {"error": "RuntimeError: boom"})
    assert "Traceback" in capsys.readouterr().err


# ── No web framework ───────────────────────────────────────────────────────────

def _python(code: str) -> str:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                          cwd=str(SRC)).stdout.strip()


def test_import_without_fastapi():
    out = _python("import sys; sys.modules['fastapi'] = None\n"
                  "import amanuense.service, amanuense.app\nprint('ok')")
    assert out == "ok"


def test_the_service_does_not_pull_in_a_server():
    out = _python("import sys\nimport amanuense.service\n"
                  "print(sorted(m for m in ('http.server', 'fastapi', 'starlette') if m in sys.modules))")
    assert out == "[]"
