"""intake: a messy pile of documents, screened and compared without flooding the inbox."""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n, intake, space  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402
from amanuense.confluence import Page  # noqa: E402


# ── Paths ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, safe", [
    ("notes.md", "notes.md"),
    ("pile/sub/notes.md", "pile/sub/notes.md"),
    ("pile\\sub\\notes.md", "pile/sub/notes.md"),
    ("/pile/notes.md", "pile/notes.md"),
    ("C:\\Users\\dana\\pile\\notes.md", "Users/dana/pile/notes.md"),
    ("./pile/./notes.md", "pile/notes.md"),
    ("pile//notes.md", "pile/notes.md"),
    ("pile/what?.md", "pile/what_.md"),
    ("pile/CON.md", "pile/_CON.md"),
    ("pile/trailing. ", "pile/trailing"),
])
def test_paths_are_made_relative_and_safe(raw, safe):
    assert intake.safe_relpath(raw) == safe


@pytest.mark.parametrize("raw", ["", "../secret.md", "pile/../../x.md", "a/\x00b.md", "///", "..", "a/" * 40 + "x.md"])
def test_dangerous_paths_are_refused(raw):
    with pytest.raises(intake.PathError):
        intake.safe_relpath(raw)


# ── Classification ──────────────────────────────────────────────────────────────

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_plan_says_what_is_used_and_why_the_rest_is_skipped(tmp_path):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    (ws / "2-my-docs" / "already.md").write_bytes(b"# Already\n\nKnown.\n")  # bytes: no \r\n on Windows
    files = [
        {"path": "pile/a.md", "size": 10, "sha256": _sha("a")},
        {"path": "pile/copy-of-a.md", "size": 10, "sha256": _sha("a")},
        {"path": "pile/b.docx", "size": 2000, "sha256": _sha("b")},
        {"path": "pile/empty.txt", "size": 0, "sha256": _sha("")},
        {"path": "pile/manual.pdf", "size": 900, "sha256": _sha("pdf")},
        {"path": "pile/logo.png", "size": 900, "sha256": _sha("png")},
        {"path": "pile/test-results.txt", "size": 50, "sha256": _sha("tr")},
        {"path": "pile/node_modules/x/README.md", "size": 50, "sha256": _sha("nm")},
        {"path": "pile/build.log", "size": 50, "sha256": _sha("log")},
        {"path": "pile/huge.md", "size": intake.MAX_FILE_BYTES + 1, "sha256": _sha("huge")},
        {"path": "pile/known.md", "size": 19, "sha256": _sha("# Already\n\nKnown.\n")},
        {"path": "../escape.md", "size": 5, "sha256": _sha("e")},
        {"path": "pile/page.html", "size": 50, "sha256": _sha("h")},
    ]
    plan = intake.plan(ws, files)
    got = {i["path"]: (i["status"], i["reason"]) for i in plan["items"]}
    assert got["pile/a.md"] == ("use", "")
    assert got["pile/copy-of-a.md"] == ("skip", "duplicate")
    assert got["pile/b.docx"] == ("use", "") and got["pile/page.html"] == ("use", "")
    assert got["pile/empty.txt"] == ("skip", "empty")
    assert got["pile/manual.pdf"] == ("skip", "pdf")
    assert got["pile/logo.png"] == ("skip", "unsupported")
    assert got["pile/test-results.txt"] == ("skip", "noise")
    assert got["pile/node_modules/x/README.md"] == ("skip", "noise")
    assert got["pile/build.log"] == ("skip", "noise")
    assert got["pile/huge.md"] == ("skip", "too_big")
    assert got["pile/known.md"] == ("skip", "known")
    assert got["../escape.md"] == ("skip", "bad_path")
    dup = next(i for i in plan["items"] if i["path"] == "pile/copy-of-a.md")
    assert dup["detail"] == "pile/a.md"
    assert plan["totals"]["use"] == 3 and plan["totals"]["skip"] == 10
    assert plan["totals"]["use_bytes"] == 2060
    # the workshop file to extend the noise patterns now exists, commented
    assert (ws / "intake-ignore.txt").read_text(encoding="utf-8").startswith("#")


def test_the_workshop_ignore_file_adds_and_removes_patterns(tmp_path):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    (ws / "intake-ignore.txt").write_text("# mine\ndrafts-old/\n*.bak.md\n!build.log\n", encoding="utf-8")
    files = [{"path": "p/drafts-old/x.md", "size": 5, "sha256": _sha("1")},
             {"path": "p/y.bak.md", "size": 5, "sha256": _sha("2")},
             {"path": "p/build.log", "size": 5, "sha256": _sha("3")}]
    got = {i["path"]: i["reason"] for i in intake.plan(ws, files)["items"]}
    assert got == {"p/drafts-old/x.md": "noise", "p/y.bak.md": "noise", "p/build.log": "unsupported"}


def test_a_batch_beyond_its_limits_skips_the_rest(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    monkeypatch.setattr(intake, "MAX_BATCH_BYTES", 25)
    monkeypatch.setattr(intake, "MAX_BATCH_FILES", 3)
    files = [{"path": f"p/{i}.md", "size": 10, "sha256": _sha(str(i))} for i in range(5)]
    reasons = [i["reason"] for i in intake.plan(ws, files)["items"]]
    assert reasons == ["", "", "batch_full", "batch_full", "batch_full"]


# ── Storing an upload ───────────────────────────────────────────────────────────

def test_uploads_land_in_their_own_batch_folder_and_never_overwrite(tmp_path):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    (ws / "2-my-docs" / "mine.md").write_text("mine", encoding="utf-8")
    batch = intake.new_batch(ws, now="2026-10-14T10:42:07+00:00")
    assert batch == "intake-20261014-104207"
    ledger = intake.Ledger(ws)
    rel = ledger.store(batch, "pile/sub/a.md", io.BytesIO(b"# A\n"), 4, _sha("# A\n"))
    rel2 = ledger.store(batch, "pile/sub/a.md", io.BytesIO(b"# A2\n"), 5)
    assert rel == "intake-20261014-104207/pile/sub/a.md"
    assert rel2 == "intake-20261014-104207/pile/sub/a (2).md"
    assert (ws / "2-my-docs" / rel2).read_text(encoding="utf-8") == "# A2\n"
    assert (ws / "2-my-docs" / "mine.md").read_text(encoding="utf-8") == "mine"
    assert intake.new_batch(ws, now="2026-10-14T10:42:07+00:00") == "intake-20261014-104207-2"


def test_uploads_refuse_bad_batches_paths_types_sizes_and_hashes(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    batch = intake.new_batch(ws)
    ledger = intake.Ledger(ws)
    with pytest.raises(intake.IntakeError):
        ledger.store("../../etc", "a.md", io.BytesIO(b"x"), 1)
    with pytest.raises(intake.IntakeError):
        ledger.store("intake-20990101-000000", "a.md", io.BytesIO(b"x"), 1)  # never created
    with pytest.raises(intake.PathError):
        ledger.store(batch, "../a.md", io.BytesIO(b"x"), 1)
    with pytest.raises(intake.IntakeError):
        ledger.store(batch, "run.exe", io.BytesIO(b"x"), 1)
    with pytest.raises(intake.IntakeError):
        ledger.store(batch, "a.md", io.BytesIO(b"x"), 1, _sha("other"))
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 3)
    with pytest.raises(intake.TooBig):
        ledger.store(batch, "big.md", io.BytesIO(b"xxxx"), 4)
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 100)
    monkeypatch.setattr(intake, "MAX_BATCH_BYTES", 6)
    ledger.store(batch, "one.md", io.BytesIO(b"xxxx"), 4)
    with pytest.raises(intake.TooBig):
        ledger.store(batch, "two.md", io.BytesIO(b"xxxx"), 4)
    assert sorted(p.name for p in (ws / "2-my-docs" / batch).iterdir()) == ["one.md"]


# ── A failed store gives its quota back and keeps no claimed file ───────────────

def _ledger_batch(tmp_path, monkeypatch, limit=8):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    batch = intake.new_batch(ws)
    monkeypatch.setattr(intake, "MAX_BATCH_BYTES", limit)
    return ws, batch, intake.Ledger(ws)


def _held(ws, batch):
    return sorted(p.name for p in (ws / "2-my-docs" / batch).rglob("*"))


def test_a_failing_mkdir_gives_the_quota_back(tmp_path, monkeypatch):
    ws, batch, ledger = _ledger_batch(tmp_path, monkeypatch)
    real = Path.mkdir

    def mkdir(self, *a, **k):
        if self.name == "sub":
            raise OSError("disk trouble")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(OSError):
        ledger.store(batch, "sub/a.md", io.BytesIO(b"xxxx"), 4)
    monkeypatch.setattr(Path, "mkdir", real)
    assert _held(ws, batch) == []
    ledger.store(batch, "full.md", io.BytesIO(b"x" * 8), 8)  # the whole quota is still there


def test_a_failing_touch_gives_the_quota_back(tmp_path, monkeypatch):
    ws, batch, ledger = _ledger_batch(tmp_path, monkeypatch)
    real = Path.touch

    def touch(self, *a, **k):
        raise OSError("disk trouble")
    monkeypatch.setattr(Path, "touch", touch)
    with pytest.raises(OSError):
        ledger.store(batch, "a.md", io.BytesIO(b"xxxx"), 4)
    monkeypatch.setattr(Path, "touch", real)
    assert _held(ws, batch) == []
    ledger.store(batch, "full.md", io.BytesIO(b"x" * 8), 8)


def test_a_failing_free_gives_the_quota_back(tmp_path, monkeypatch):
    ws, batch, ledger = _ledger_batch(tmp_path, monkeypatch)
    real = intake._free
    monkeypatch.setattr(intake, "_free", lambda path: (_ for _ in ()).throw(OSError("disk trouble")))
    with pytest.raises(OSError):
        ledger.store(batch, "a.md", io.BytesIO(b"xxxx"), 4)
    monkeypatch.setattr(intake, "_free", real)
    ledger.store(batch, "full.md", io.BytesIO(b"x" * 8), 8)


def test_a_containment_failure_gives_the_quota_back_and_removes_the_claimed_file(tmp_path, monkeypatch):
    ws, batch, ledger = _ledger_batch(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "2-my-docs" / batch / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(intake.PathError):
        ledger.store(batch, "link/a.md", io.BytesIO(b"xxxx"), 4)
    assert list(outside.iterdir()) == []  # the file claimed through the link is gone
    ledger.store(batch, "full.md", io.BytesIO(b"x" * 8), 8)


# ── The comparison of a pile ────────────────────────────────────────────────────

def _pile(tmp_path, files: dict[str, str]):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws, "en")
    batch = intake.new_batch(ws, now="2026-10-14T10:42:07+00:00")
    for rel, text in files.items():
        p = ws / "2-my-docs" / batch / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return ws, batch


PAGES = [Page("Fare Engine overview", "# Fare Engine overview\n\nComputes the fare of a journey.\n"),
         Page("Service Alerts overview", "# Service Alerts overview\n\nAlerts reach the boards in 2 minutes.\n"),
         Page("Departures Board deployment", "# Departures Board deployment\n\nPort 8080.\n")]


def _live(pages=PAGES):
    return space.Source("live", list(pages), "2026-10-14T10:42:00+00:00", {"space": "TRAMS"})


def test_a_pile_becomes_one_update_per_page_and_groups_what_matches_nothing(tmp_path):
    i18n.use("en")
    files = {
        "fares/Fare Engine overview.md": "# Fare Engine overview\n\nComputes the fare; adds the off-peak discount.\n",
        "fares/fare-engine-overview-v2.md": "# Fare Engine overview\n\nOff-peak is 20% cheaper.\n",
        "alerts/alerts.md": "# Service Alerts overview\n\nAlerts reach the boards in 2 minutes.\n",
        "alerts/alerts-copy.md": "# Service Alerts overview\n\nAlerts reach the boards in 2 minutes.\n",
        "same-as-page-other-name.md": "# Whatever\n\nPort 8080.\n",
        "logs/run.log.txt": "noise",
        "test-results.txt": "FAILED 3",
        "empty.md": "   \n",
        "manual.pdf": "%PDF-1.4",
    }
    files.update({f"ideas/idea-{i:02d}.md": f"# Idea {i:02d}\n\n" + "word " * (10 * i) for i in range(1, 15)})
    ws, batch = _pile(tmp_path, files)
    result = docs_kit.run_workspace(ws, source=_live())
    # one task for the fare page, built from both files; nothing for the identical alerts page
    assert len(result["tasks"]) == 1 and "fare-engine-overview" in result["tasks"][0]
    task = ws / "output" / "tasks" / result["tasks"][0]
    local = (task / "LOCAL.md").read_text(encoding="utf-8")
    assert "off-peak discount" in local and "20% cheaper" in local
    prompt = (task / "TASK.md").read_text(encoding="utf-8")
    assert "Computes the fare of a journey." in prompt and "New material" in prompt
    summary = json.loads((ws / "output" / "intake.json").read_text(encoding="utf-8"))
    counts = summary["batches"][batch]
    assert counts["updates"] == 1 and counts["identical"] == 2 and counts["unmatched"] == 14
    reasons = {s["rel"].split("/", 1)[1]: s["reason"] for s in summary["skipped"]}
    assert reasons == {"alerts/alerts-copy.md": "duplicate", "logs/run.log.txt": "noise", "test-results.txt": "noise",
                       "empty.md": "empty", "manual.pdf": "pdf"}
    ranked = [u["title"] for u in summary["unmatched"]]
    assert ranked[0] == "Idea 14" and ranked[-1] == "Idea 01"
    report = (ws / "output" / "report.md").read_text(encoding="utf-8")
    assert "Idea 07" in report and "match no page" in report


def test_a_chosen_candidate_becomes_a_new_page_task(tmp_path):
    ws, batch = _pile(tmp_path, {"night.md": "# Night Service\n\nRuns at night from 00:30.\n"})
    docs_kit.run_workspace(ws, source=_live())
    intake.promote(ws, f"{batch}/night.md")
    result = docs_kit.run_workspace(ws, source=_live())
    assert any("new-night-service" in t for t in result["tasks"])
    summary = json.loads((ws / "output" / "intake.json").read_text(encoding="utf-8"))
    assert summary["unmatched"] == [] and summary["promoted"] == [f"{batch}/night.md"]
    with pytest.raises(intake.IntakeError):
        intake.promote(ws, "../outside.md")


def test_documents_outside_a_batch_keep_the_old_rules(tmp_path):
    ws, _ = _pile(tmp_path, {})
    (ws / "2-my-docs" / "Fare Engine overview.md").write_text("# Fare Engine overview\n\nOther text.\n", encoding="utf-8")
    (ws / "2-my-docs" / "Brand new.md").write_text("# Brand new\n\nx\n", encoding="utf-8")
    result = docs_kit.run_workspace(ws, source=_live())
    assert [t.split("-", 1)[1] for t in result["tasks"]] == ["new-brand-new"]  # same title, no instructions: report only


def test_progress_is_reported_while_the_pile_is_compared(tmp_path):
    ws, _ = _pile(tmp_path, {"Fare Engine overview.md": "# Fare Engine overview\n\nNew.\n"})
    seen = []
    docs_kit.run_workspace(ws, source=_live(), progress=lambda stage, done, total: seen.append((stage, done, total)))
    stages = [s for s, _, _ in seen]
    assert stages[0] == "compare" and "write" in stages and stages[-1] == "log"
