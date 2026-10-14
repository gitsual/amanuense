"""registro: change log of a documentation workshop.

Who changed what: page diffs between two Word exports, authors from the
Confluence REST API, commits from local git clones, and change requests that an
AI turns into page tasks. Network and git are faked; nothing leaves the test.
"""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import registro as log, taller as docs_kit  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"}


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _docx(path, body, created="2026-10-01T10:00:00Z"):
    st = "".join(f'<w:style w:styleId="{k}"><w:name w:val="{v}"/></w:style>' for k, v in STYLES.items())
    core = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created></cp:coreProperties>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
        z.writestr("docProps/core.xml", core)
    return path


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.data).encode()


class FakeConfluence:
    """Answers the two REST calls the log makes, like Confluence Data Center."""

    def __init__(self, pages):
        self.pages, self.requests = pages, []  # title -> list of versions, newest last

    def __call__(self, req, timeout):
        from urllib.parse import parse_qs, urlparse
        self.requests.append(req)
        url = urlparse(req.full_url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.endswith("/rest/api/content"):
            versions = self.pages.get(q["title"])
            if not versions:
                return Response({"results": []})
            return Response({"results": [{"id": "77", "title": q["title"], "version": versions[-1]}]})
        number = int(q["version"])
        versions = next(iter(self.pages.values()))
        return Response({"id": "77", "version": versions[number - 1]})


def _version(n, who, when, message=""):
    return {"number": n, "by": {"displayName": who}, "when": when, "message": message}


def test_confluence_history_lists_versions_newer_than_a_date():
    fake = FakeConfluence({"Convenciones": [
        _version(1, "Ana", "2026-09-01T10:00:00.000+02:00"),
        _version(2, "Luis", "2026-10-03T09:00:00.000+02:00", "nuevo prefijo"),
        _version(3, "Marta", "2026-10-05T12:00:00.000+02:00"),
    ]})
    api = log.ConfluenceHistory("https://wiki.example.com/", "pat-123", space="DOC", opener=fake)
    changes = api.changes("Convenciones", since="2026-10-01T10:00:00Z")
    assert [(c["by"], c["number"], c["message"]) for c in changes] == [("Marta", 3, ""), ("Luis", 2, "nuevo prefijo")]
    first = fake.requests[0]
    assert first.full_url.startswith("https://wiki.example.com/rest/api/content?")
    assert "spaceKey=DOC" in first.full_url
    assert dict(first.header_items())["Authorization"] == "Bearer pat-123"
    assert api.changes("No existe", since="2026-10-01T10:00:00Z") == []


def test_confluence_cloud_uses_wiki_prefix_and_basic_auth():
    fake = FakeConfluence({})
    api = log.ConfluenceHistory("https://acme.atlassian.net", "tok", user="a@b.c", opener=fake)
    api.changes("X", since="2026-01-01T00:00:00Z")
    req = fake.requests[0]
    assert req.full_url.startswith("https://acme.atlassian.net/wiki/rest/api/content?")
    assert dict(req.header_items())["Authorization"].startswith("Basic ")


def _pages(*pairs):
    return [docs_kit.Page(t, f"# {t}\n\n{body}\n") for t, body in pairs]


def test_diff_pages_reports_what_changed_in_each_page():
    old = _pages(("Convenciones", "Prefijo CMP.\nRamas feature/"), ("Viejo", "adiós"))
    new = _pages(("Convenciones", "Prefijo HMI.\nRamas feature/"), ("Nuevo", "hola"))
    changes = {c.title: c for c in log.diff_pages(old, new)}
    assert changes["Convenciones"].kind == "cambiada"
    assert changes["Convenciones"].added == ["Prefijo HMI."]
    assert changes["Convenciones"].removed == ["Prefijo CMP."]
    assert changes["Nuevo"].kind == "nueva" and changes["Viejo"].kind == "eliminada"
    assert log.diff_pages(old, old) == []


def test_export_created_reads_the_word_metadata(tmp_path):
    path = _docx(tmp_path / "a.docx", _p("X", "Heading1"), created="2026-10-02T08:30:00Z")
    assert log.export_created(path) == "2026-10-02T08:30:00Z"


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=Pepe Code", "-c", "user.email=pepe@example.com", *args],
                   cwd=repo, check=True, capture_output=True)


def _repo(tmp_path):
    repo = tmp_path / "hmi-web"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "src" / "track_table.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: paginate track table")
    return repo


def test_git_commits_lists_author_files_and_affected_pages(tmp_path):
    repo = _repo(tmp_path)
    commits = log.git_commits(repo, since="2000-01-01T00:00:00Z")
    assert [(c["by"], c["subject"], c["files"]) for c in commits] == [
        ("Pepe Code", "feat: paginate track table", ["src/track_table.py"])]
    pages = _pages(("Tabla de tracks", "El componente vive en track_table.py"), ("Otra", "nada"))
    assert log.affected_pages(commits[0], pages) == ["Tabla de tracks"]


def test_affected_pages_ignores_names_common_to_many_pages_and_repeated_titles():
    commit = {"repo": "tracks", "files": ["README.md", "src/track_table.py"]}
    generic = [(f"Equipo", "ver el README del repo") for _ in range(10)]
    generic += [(f"Página {i}", "ver el README") for i in range(10)]
    pages = _pages(("Tabla de tracks", "El componente vive en track_table.py"), *generic)
    assert log.affected_pages(commit, pages) == ["Tabla de tracks"]


def test_code_task_keeps_diffs_of_the_newest_commits_and_lists_the_rest(tmp_path):
    class Done:
        returncode, stdout = 0, "+" + "x" * (log.MAX_DIFF - 1)

    page = _pages(("Platform", "texto"))[0]
    fresh = [(log.RepoSpec(path=tmp_path, url="", refs=()),
              {"repo": "base", "branch": "develop", "hash": f"{i:040d}", "by": "Ana",
               "when": f"2026-10-{i + 1:02d}T00:00:00Z", "what": f"commit {i}", "pages": ["Platform"], "tasks": []})
             for i in range(20)]
    [rel] = log._code_tasks(tmp_path, fresh, [page], None, "", lambda *a, **k: Done())
    local = (tmp_path / rel / log.i18n.name("local_copy")).read_text(encoding="utf-8")
    assert len(local) < log.MAX_TASK_DIFF + 10 * log.MAX_DIFF
    assert all(f"commit {i}" in local for i in range(20))
    assert local.index("commit 19") < local.index("commit 0")


def test_requests_without_ai_wait_for_a_page(tmp_path):
    reqs = log.read_requests("- Ana: el puerto de despliegue ahora es 8443\n# comentario\n")
    assert [(r["by"], r["text"]) for r in reqs] == [("Ana", "el puerto de despliegue ahora es 8443")]
    assert reqs[0]["id"] == log.read_requests("- Ana: el puerto de despliegue ahora es 8443")[0]["id"]


def test_route_request_asks_the_ai_which_page_and_why():
    seen = []

    def ai(prompt):
        seen.append(prompt)
        return 'Claro:\n```json\n{"pagina": "Despliegue", "cambio": "cambiar el puerto a 8443", "motivo": "nuevo puerto"}\n```'

    pages = _pages(("Despliegue", "Puerto 8080"), ("Convenciones", "Prefijos"))
    route = log.route_request({"by": "Ana", "text": "el puerto ahora es 8443"}, pages, ai)
    assert route == {"pagina": "Despliegue", "cambio": "cambiar el puerto a 8443", "motivo": "nuevo puerto"}
    assert "Despliegue" in seen[0] and "Convenciones" in seen[0] and "8443" in seen[0]
    bad = log.route_request({"by": "Ana", "text": "x"}, pages, lambda p: '{"pagina": "Inventada"}')
    assert bad["pagina"] == ""


def test_route_request_tolerates_a_title_copied_with_its_summary():
    pages = _pages(("Despliegue", "Puerto 8080"), ("Despliegue avanzado", "Kubernetes"))
    answer = '{"pagina": "Despliegue: El servicio escucha en el puerto 8080.", "cambio": "8443", "motivo": "m"}'
    assert log.route_request({"by": "Ana", "text": "x"}, pages, lambda p: answer)["pagina"] == "Despliegue"
    lower = '{"pagina": "despliegue avanzado", "cambio": "c", "motivo": "m"}'
    assert log.route_request({"by": "Ana", "text": "x"}, pages, lambda p: lower)["pagina"] == "Despliegue avanzado"


def _export(root, body, created):
    exp = root / docs_kit.EXPORT_DIR
    exp.mkdir(parents=True, exist_ok=True)
    for old in exp.glob("*.docx"):
        old.unlink()
    return _docx(exp / "Bricks.docx", body, created=created)


def test_run_workspace_keeps_a_log_of_who_changed_what(tmp_path, monkeypatch):
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    repo = _repo(tmp_path)
    (root / log.REPOS_FILE).write_text(f"# clones\n{repo}\n", encoding="utf-8")
    page = _p("Convenciones", "Heading1") + _p("Prefijo CMP.") + _p("Tabla de tracks", "Heading1") + _p("Ver track_table.py")
    _export(root, page, "2026-10-01T10:00:00Z")
    docs_kit.run_workspace(root)
    entries = json.loads((root / docs_kit.OUT_DIR / log.LOG_JSON).read_text(encoding="utf-8"))
    assert [e["kind"] for e in entries] == ["codigo"]  # first export: nothing to compare yet
    assert entries[0]["pages"] == ["Tabla de tracks"]

    _export(root, page.replace("CMP", "HMI"), "2026-10-08T10:00:00Z")
    (root / log.REQUESTS_FILE).write_text("- Ana: el prefijo de Convenciones se escribe en minúsculas\n",
                                          encoding="utf-8")
    fake = FakeConfluence({"Convenciones": [_version(1, "Ana", "2026-09-01T10:00:00Z"),
                                            _version(2, "Luis", "2026-10-03T09:00:00Z", "nuevo prefijo")]})
    history = log.ConfluenceHistory("https://wiki.example.com", "pat", opener=fake)
    ai = lambda p: '{"pagina": "Convenciones", "cambio": "prefijo en minúsculas", "motivo": "petición de Ana"}'
    monkeypatch.setenv("AMANUENSE_USER", "Rosa")
    docs_kit.run_workspace(root, history=history, router=ai)
    docs_kit.run_workspace(root, history=history, router=ai)  # a rerun adds nothing

    out = root / docs_kit.OUT_DIR
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    conf = [e for e in entries if e["kind"] == "confluence"]
    assert [(e["page"], e["by"], e["message"]) for e in conf] == [("Convenciones", "Luis", "nuevo prefijo")]
    assert "+ Prefijo HMI." in conf[0]["what"] and "- Prefijo CMP." in conf[0]["what"]
    req = [e for e in entries if e["kind"] == "peticion"]
    assert [(e["by"], e["page"], e["motivo"]) for e in req] == [("Ana", "Convenciones", "petición de Ana")]
    task = out / req[0]["task"] / "TAREA.md"
    assert "prefijo en minúsculas" in task.read_text(encoding="utf-8")
    assert len([e for e in entries if e["kind"] == "codigo"]) == 1

    (task.parent / docs_kit.RESULT).write_text("# Convenciones\n\nPrefijo hmi.\n", encoding="utf-8")
    docs_kit.run_workspace(root, history=history, router=ai)
    entries = json.loads((out / log.LOG_JSON).read_text(encoding="utf-8"))
    done = [e for e in entries if e["kind"] == "taller"]
    assert [(e["by"], e["page"]) for e in done] == [("Rosa", "Convenciones")]
    assert (task.parent / "PARA-CONFLUENCE.html").is_file()
    page_html = (out / log.LOG_HTML).read_text(encoding="utf-8")
    for text in ("Luis", "Ana", "Pepe Code", "Rosa", "nuevo prefijo", "Tabla de tracks"):
        assert text in page_html
    assert log.LOG_HTML in (out / "index.html").read_text(encoding="utf-8")


def test_a_request_without_a_page_is_retried_on_the_next_run(tmp_path):
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    _export(root, _p("Despliegue", "Heading1") + _p("Puerto 8080"), "2026-10-01T10:00:00Z")
    (root / log.REQUESTS_FILE).write_text("- Ana: puerto 8443\n", encoding="utf-8")
    docs_kit.run_workspace(root, router=lambda p: "no sé")
    docs_kit.run_workspace(root, router=lambda p: '{"pagina": "Despliegue", "cambio": "8443", "motivo": "m"}')
    entries = json.loads((root / docs_kit.OUT_DIR / log.LOG_JSON).read_text(encoding="utf-8"))
    assert [(e["kind"], e["page"]) for e in entries] == [("peticion", "Despliegue")]


def test_each_code_task_keeps_the_page_it_was_made_for(tmp_path):
    class Done:
        returncode, stdout = 0, "+x"

    pages = _pages(("Alfa", "texto"), ("Beta", "texto"))
    spec = log.RepoSpec(path=tmp_path, url="", refs=())
    first = {"repo": "r", "branch": "b", "hash": "1" * 40, "by": "Ana", "when": "2026-10-01T00:00:00Z",
             "what": "c1", "pages": ["Beta"], "tasks": []}
    second = dict(first, hash="2" * 40, what="c2", pages=["Alfa", "Beta"], tasks=[])
    log._code_tasks(tmp_path, [(spec, first), (spec, second)], pages, None, "", lambda *a, **k: Done())
    assert {title: rel.split("/")[-1].rsplit("-", 1)[0] for rel, title in log.code_task_pages(second).items()} \
        == {"Alfa": "alfa", "Beta": "beta"}


def _fake_ai(triage: str, calls: list):
    def ai(prompt: str) -> str:
        calls.append(prompt)
        if "categoria" in prompt:
            return triage
        if '"page"' in prompt or '"pagina"' in prompt:
            return '{"pagina": "Tabla de tracks", "cambio": "paginar de 50 en 50", "motivo": "m"}'
        return "# Tabla de tracks\n\nPágina propuesta.\n"
    return ai


def _code_workspace(tmp_path, request: bool):
    root = tmp_path / "taller"
    docs_kit.init_workspace(root)
    (root / log.REPOS_FILE).write_text(f"{_repo(tmp_path)}\n", encoding="utf-8")
    _export(root, _p("Tabla de tracks", "Heading1") + _p("Ver track_table.py"), "2026-10-01T10:00:00Z")
    if request:
        (root / log.REQUESTS_FILE).write_text("- Ana: la tabla pagina de 50 en 50\n", encoding="utf-8")
    return root


def test_code_tasks_are_triaged_and_chained_on_the_request_proposal(tmp_path):
    root = _code_workspace(tmp_path, request=True)
    calls = []
    triage = '{"categoria": "actualizar", "motivo": "la tabla ya pagina", "cambios": ["contar la paginación"]}'
    docs_kit.run_workspace(root, ai=_fake_ai(triage, calls))

    [code] = (root / docs_kit.OUT_DIR / log.i18n.name("code_dir")).iterdir()
    verdict = json.loads((code / "TRIAJE.json").read_text(encoding="utf-8"))
    assert verdict["categoria"] == "encadenar" and verdict["cambios"] == ["contar la paginación"]
    assert (code / docs_kit.RESULT).is_file()
    solve = [p for p in calls if "contar la paginación" in p and "categoria" not in p]
    assert solve and "Página propuesta." in solve[-1]  # built on the request's proposal

    before = len(calls)
    docs_kit.run_workspace(root, ai=_fake_ai(triage, calls))
    assert len(calls) == before  # triage and results are kept


def test_noise_is_not_solved(tmp_path):
    root = _code_workspace(tmp_path, request=False)
    calls = []
    docs_kit.run_workspace(root, ai=_fake_ai('{"categoria": "ruido", "motivo": "no cambia nada"}', calls))
    [code] = (root / docs_kit.OUT_DIR / log.i18n.name("code_dir")).iterdir()
    assert json.loads((code / "TRIAJE.json").read_text(encoding="utf-8"))["categoria"] == "ruido"
    assert not (code / docs_kit.RESULT).exists()


def test_deliver_credits_requests_and_lists_doubtful_pages(tmp_path):
    root = _code_workspace(tmp_path, request=True)
    triage = '{"categoria": "dudosa", "motivo": "solo el autor sabe si sigue vigente"}'
    docs_kit.run_workspace(root, ai=_fake_ai(triage, []))
    folder = docs_kit.deliver_workspace(root, today="2026-10-14")
    readme = (folder / "LEEME.md").read_text(encoding="utf-8")
    assert "Tabla de tracks" in readme and "Ana" in readme
    assert "solo el autor sabe si sigue vigente" in readme
    assert (folder / "paginas" / "Tabla de tracks" / docs_kit.RESULT).is_file()


def test_old_logs_match_code_tasks_to_pages_by_folder_name():
    entry = {"tasks": ["codigo/beta-123abc", "codigo/alfa-456def"], "pages": ["Alfa", "Beta", "Gamma"]}
    assert log.code_task_pages(entry) == {"codigo/beta-123abc": "Beta", "codigo/alfa-456def": "Alfa"}


def test_triage_reads_the_page_text_not_only_its_headings(tmp_path):
    (tmp_path / "ACTUAL.md").write_text("# Guía base\n\nEl inyector vive en app-shell.\n", encoding="utf-8")
    (tmp_path / "LOCAL.md").write_text("commit: elimina app-shell\n", encoding="utf-8")
    seen = []
    log.triage_code_task(tmp_path, "Guía base", lambda p: seen.append(p) or '{"categoria": "actualizar"}')
    assert "El inyector vive en app-shell." in seen[0]


def test_triage_always_sees_every_commit_subject(tmp_path):
    (tmp_path / "ACTUAL.md").write_text("# Componentes\n", encoding="utf-8")
    local = ("## tooling · develop · aaaaaaaaaa · Ana\n\nfeat: tooling\n\n" + "+x\n" * log.MAX_TRIAGE_CHARS
             + "\n- components · feature/PROJ-12 · bbbbbbbbbb · Ana: refactor: single package\n")
    (tmp_path / "LOCAL.md").write_text(local, encoding="utf-8")
    seen = []
    log.triage_code_task(tmp_path, "Componentes", lambda p: seen.append(p) or "{}")
    assert "refactor: single package" in seen[0] and len(seen[0]) < 2 * log.MAX_TRIAGE_CHARS
    assert "aaaaaaaaaa · Ana: feat: tooling" in seen[0]
