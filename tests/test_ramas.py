"""Code watch: repos.txt lists local clones or remote URLs, optionally with the branches to
follow. Remote ones are cloned into the workshop and fetched on every run; the log notes
the branch of each commit; and every page a new commit touches gets a task that carries
the commits and their diff, so the AI can propose the updated text."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n, registro as log, taller as docs_kit  # noqa: E402
from test_registro import _export, _p  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=Pepe Code", "-c", "user.email=pepe@example.com",
                           "-c", "init.defaultBranch=main", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout


def _commit(repo, path, text, message):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


def _origin(tmp_path):
    """A repo with main and a feature branch, and a bare copy that plays Bitbucket."""
    work = tmp_path / "work" / "hmi-tracks"
    work.mkdir(parents=True)
    _git(work, "init", "-q")
    _commit(work, "src/track_table.py", "x = 1\n", "feat: paginate track table")
    _git(work, "checkout", "-q", "-b", "feature/filters")
    _commit(work, "src/track_filter.py", "y = 2\n", "feat: filter tracks by speed")
    _git(work, "checkout", "-q", "main")
    bare = tmp_path / "remote" / "hmi-tracks.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return work, bare


def test_repos_lines_take_a_path_or_url_and_optional_branches(tmp_path):
    root = tmp_path / "taller"
    root.mkdir()
    (root / "repos.txt").write_text(
        "# clones\n"
        "~/code/hmi-web\n"
        "C:\\code\\hmi-map @ develop, feature/x\n"
        "https://bitbucket.example.com/scm/team/hmi-tracks.git @ *\n"
        "git@bitbucket.example.com:team/hmi-base.git\n", encoding="utf-8")
    specs = log.read_repos(root)
    assert [(s.url, s.refs) for s in specs] == [
        ("", ()), ("", ("develop", "feature/x")),
        ("https://bitbucket.example.com/scm/team/hmi-tracks.git", ("*",)),
        ("git@bitbucket.example.com:team/hmi-base.git", ())]
    assert specs[0].path == Path("~/code/hmi-web").expanduser()
    assert specs[2].path == root / "repos" / "hmi-tracks"
    assert specs[3].path == root / "repos" / "hmi-base"


def test_all_branches_are_read_and_each_commit_names_its_branch(tmp_path):
    work, _ = _origin(tmp_path)
    head = log.git_commits(work, "2000-01-01T00:00:00Z")
    assert [c["subject"] for c in head] == ["feat: paginate track table"]
    every = log.git_commits(work, "2000-01-01T00:00:00Z", refs=("*",))
    assert {c["subject"]: c["branch"] for c in every} == {
        "feat: filter tracks by speed": "feature/filters", "feat: paginate track table": "main"}
    one = log.git_commits(work, "2000-01-01T00:00:00Z", refs=("feature/filters",))
    assert [c["subject"] for c in one] == ["feat: filter tracks by speed", "feat: paginate track table"]


def test_a_remote_repo_is_cloned_then_fetched_and_its_branches_followed(tmp_path):
    work, bare = _origin(tmp_path)
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    (root / "repos.txt").write_text(f"{bare.as_uri()} @ *\n", encoding="utf-8")
    spec = log.read_repos(root)[0]
    assert log.sync_repo(spec) == "clone"
    assert (spec.path / ".git").is_dir()
    _commit(work, "src/track_table.py", "x = 3\n", "fix: keep the page on refresh")
    _git(work, "push", "-q", str(bare), "main")
    assert log.sync_repo(spec) == "fetch"
    subjects = {c["subject"]: c["branch"] for c in log.git_commits(spec.path, "2000-01-01T00:00:00Z", spec.refs)}
    assert subjects["fix: keep the page on refresh"] == "main"
    assert subjects["feat: filter tracks by speed"] == "feature/filters"


def test_a_named_branch_is_read_from_the_remote_after_a_fetch(tmp_path):
    work, bare = _origin(tmp_path)
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    (root / "repos.txt").write_text(f"{bare.as_uri()} @ feature/filters\n", encoding="utf-8")
    spec = log.read_repos(root)[0]
    log.sync_repo(spec)  # the clone only has main checked out
    commits = log.git_commits(spec.path, "2000-01-01T00:00:00Z", spec.refs)
    assert commits[0]["subject"] == "feat: filter tracks by speed"
    assert commits[0]["branch"] == "feature/filters"


def test_a_local_clone_is_never_fetched(tmp_path):
    work, _ = _origin(tmp_path)
    root = tmp_path / "taller"
    root.mkdir()
    (root / "repos.txt").write_text(f"{work}\n", encoding="utf-8")
    calls = []
    assert log.sync_repo(log.read_repos(root)[0], run=lambda *a, **k: calls.append(a)) is None
    assert calls == []


def test_a_page_touched_by_new_commits_gets_a_task_with_their_diff(tmp_path):
    work, bare = _origin(tmp_path)
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    (root / log.REPOS_FILE).write_text(f"{bare.as_uri()} @ *\n", encoding="utf-8")
    page = (_p("Tabla de tracks", "Heading1") + _p("La tabla vive en track_table.py y pagina de 20 en 20.")
            + _p("Filtros", "Heading1") + _p("El filtro está en track_filter.py.")
            + _p("Otra", "Heading1") + _p("Nada que ver."))
    _export(root, page, "2026-10-01T10:00:00Z")
    docs_kit.run_workspace(root)

    out = root / docs_kit.OUT_DIR
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    by_subject = {e["what"]: e for e in entries if e["kind"] == "codigo"}
    table = by_subject["feat: paginate track table"]
    assert table["branch"] == "main" and table["pages"] == ["Tabla de tracks"]
    assert table["tasks"] and (out / table["tasks"][0] / "TAREA.md").is_file()
    task = (out / table["tasks"][0] / "TAREA.md").read_text(encoding="utf-8")
    assert "# Tarea: actualizar la página «Tabla de tracks» de Confluence" in task
    assert "feat: paginate track table" in task and "+x = 1" in task  # the diff goes in
    assert "track_filter" not in task  # another page's commit stays out
    assert by_subject["feat: filter tracks by speed"]["branch"] == "feature/filters"
    log_html = (out / log.LOG_HTML).read_text(encoding="utf-8")
    assert f'href="{table["tasks"][0]}/TAREA.md"' in log_html and "main" in log_html

    before = sorted(p.name for p in (out / "codigo").iterdir())
    docs_kit.run_workspace(root)  # nothing new: no new task
    assert sorted(p.name for p in (out / "codigo").iterdir()) == before

    (out / table["tasks"][0] / "RESULTADO.md").write_text(
        "# Tabla de tracks\n\nLa tabla vive en track_table.py.\n", encoding="utf-8")
    docs_kit.run_workspace(root)
    assert (out / table["tasks"][0] / "PARA-CONFLUENCE.html").is_file()


def test_code_tasks_follow_the_english_workshop(tmp_path):
    i18n.use("en")
    work, _ = _origin(tmp_path)
    root = tmp_path / "ws"
    docs_kit.init_workspace(root, lang="en")
    (root / "repos.txt").write_text(f"{work}\n", encoding="utf-8")
    _export_en = root / "1-confluence-export"
    from test_registro import _docx
    _docx(_export_en / "export.docx", _p("Track table", "Heading1") + _p("It lives in track_table.py."))
    docs_kit.run_workspace(root)
    tasks = [p for p in (root / "output" / "code").iterdir()]
    assert len(tasks) == 1
    text = (tasks[0] / "TASK.md").read_text(encoding="utf-8")
    assert "Commits in the code touch what this page describes" in text
