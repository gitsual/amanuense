"""taller: workspace for rewriting Confluence pages from a Word export + a local folder.

Everything here runs on the standard library only (no embeddings, no LLM), which is
the mode a first-time user gets with a plain Python install.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import taller as docs_kit  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"}


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _docx(path, body):
    st = "".join(f'<w:style w:styleId="{k}"><w:name w:val="{v}"/></w:style>' for k, v in STYLES.items())
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
    return path


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _workspace(tmp_path) -> Path:
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws)
    body = (
        _p("Brick IHM", "Heading1")
        + _p("Convenciones de nomenclatura", "Heading2")
        + _p("Las ramas usan el prefijo feature/.")
        + _p("Los commits siguen conventional commits.")
        + _p("Plantilla de capacidad", "Heading2")
        + _p("Resumen", "Heading3") + _p("Qué hace la capacidad.")
        + _p("Contratos", "Heading3") + _p("Entradas y salidas.")
        + _p("Página antigua", "Heading2")
        + _p("Contenido que nadie migró.")
    )
    _docx(ws / docs_kit.EXPORT_DIR / "export.docx", body)
    local = ws / docs_kit.LOCAL_DIR
    _docx(local / "Convenciones de nomenclatura.docx",
          _p("Convenciones de nomenclatura", "Heading1")
          + _p("Instrucciones de actualización: las ramas pasan a usar el prefijo PROJ-."))
    (local / "nuevas").mkdir()
    (local / "nuevas" / "capacidad-mapas.md").write_text(
        "# Capacidad de mapas\n\nPlantilla: capacidad\n\nMuestra capas tácticas sobre el mapa.\n",
        encoding="utf-8")
    (ws / docs_kit.BIBLE_DIR / "estandares-repos.md").write_text(
        "# Estándares de repos\n\nUn repo por componente.\n", encoding="utf-8")
    return ws


def test_init_creates_the_folders_and_keeps_an_edited_guide(tmp_path):
    ws = tmp_path / "ws"
    docs_kit.init_workspace(ws)
    for name in (docs_kit.EXPORT_DIR, docs_kit.LOCAL_DIR, docs_kit.BIBLE_DIR):
        assert (ws / name).is_dir()
    guide = ws / docs_kit.GUIDE
    assert "Instrucciones de actualización" in guide.read_text(encoding="utf-8")
    guide.write_text("mine", encoding="utf-8")
    docs_kit.init_workspace(ws)
    assert guide.read_text(encoding="utf-8") == "mine"


def test_run_writes_report_tasks_and_index_without_touching_inputs(tmp_path):
    ws = _workspace(tmp_path)
    inputs = {d: _snapshot(ws / d) for d in (docs_kit.EXPORT_DIR, docs_kit.LOCAL_DIR, docs_kit.BIBLE_DIR)}

    summary = docs_kit.run_workspace(ws)

    assert summary["page_level"] == 2
    out = ws / docs_kit.OUT_DIR
    report = (out / "informe.md").read_text(encoding="utf-8")
    assert "Actualizar en Confluence: **1**" in report
    assert "Página antigua" in report

    tasks = sorted(p.name for p in (out / "tareas").iterdir())
    assert tasks == ["01-actualizar-convenciones-de-nomenclatura", "02-nueva-capacidad-de-mapas"]

    update = (out / "tareas" / tasks[0] / "TAREA.md").read_text(encoding="utf-8")
    assert "prefijo PROJ-" in update            # the update instructions
    assert "prefijo feature/" in update          # the current page
    assert "Un repo por componente" in update    # the reference set
    assert "Responde SOLO con la página" in update and "RESULTADO.md" not in update
    current = (out / "tareas" / tasks[0] / "ACTUAL.md").read_text(encoding="utf-8")
    assert current.startswith("# Convenciones de nomenclatura")

    new = (out / "tareas" / tasks[1] / "TAREA.md").read_text(encoding="utf-8")
    assert "capas tácticas" in new
    assert "## Resumen" in new and "## Contratos" in new  # template found in the export

    index = (out / "index.html").read_text(encoding="utf-8")
    assert "informe.md" in index and tasks[0] in index and "pendiente" in index

    for name, snap in inputs.items():
        assert _snapshot(ws / name) == snap


def test_results_survive_a_rerun_and_get_published(tmp_path):
    ws = _workspace(tmp_path)
    docs_kit.run_workspace(ws)
    task = ws / docs_kit.OUT_DIR / "tareas" / "01-actualizar-convenciones-de-nomenclatura"
    (task / "RESULTADO.md").write_text(
        "# Convenciones de nomenclatura\n\nLas ramas usan el prefijo PROJ-.\n\n"
        "| Tipo | Prefijo |\n| --- | --- |\n| feat | PROJ- |\n", encoding="utf-8")

    docs_kit.run_workspace(ws)

    assert (task / "RESULTADO.md").is_file()
    html = (task / "PARA-CONFLUENCE.html").read_text(encoding="utf-8")
    assert "<h1>Convenciones de nomenclatura</h1>" in html
    assert "<table>" in html and "<td>PROJ-</td>" in html
    diff = (task / "CAMBIOS.html").read_text(encoding="utf-8")
    assert "feature/" in diff and "PROJ-" in diff
    index = (ws / docs_kit.OUT_DIR / "index.html").read_text(encoding="utf-8")
    assert "PARA-CONFLUENCE.html" in index and "listo" in index


def test_an_ai_fills_only_the_missing_results(tmp_path):
    ws = _workspace(tmp_path)
    docs_kit.run_workspace(ws)
    tasks = ws / docs_kit.OUT_DIR / "tareas"
    kept = tasks / "01-actualizar-convenciones-de-nomenclatura" / "RESULTADO.md"
    kept.write_text("# Mine\n", encoding="utf-8")
    prompts = []

    def ai(prompt: str) -> str:
        prompts.append(prompt)
        return "# Capacidad de mapas\n\nTexto nuevo.\n"

    docs_kit.run_workspace(ws, ai=ai)

    assert len(prompts) == 1 and "capas tácticas" in prompts[0]
    assert kept.read_text(encoding="utf-8") == "# Mine\n"
    written = tasks / "02-nueva-capacidad-de-mapas" / "RESULTADO.md"
    assert written.read_text(encoding="utf-8").startswith("# Capacidad de mapas")


def test_openai_compatible_client_sends_the_prompt(tmp_path):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "# Hecho\n"}}]}).encode()

    def opener(req, timeout):
        seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
        seen["body"], seen["timeout"] = json.loads(req.data), timeout
        return Response()

    ai = docs_kit.openai_client("http://localhost:11434/v1/", "qwen3", key="", opener=opener)
    assert ai("hola") == "# Hecho\n"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"]["model"] == "qwen3"
    assert seen["body"]["messages"][-1] == {"role": "user", "content": "hola"}
    assert "Authorization" not in seen["headers"]

    docs_kit.openai_client("https://x/v1", "m", key="sk-1", opener=opener)("q")
    assert seen["headers"]["Authorization"] == "Bearer sk-1"


def test_markdown_to_html_covers_confluence_basics():
    html = docs_kit.markdown_to_html(
        "# Título\n\nUn **dato** y `código` <script>.\n\n- uno\n- dos\n\n1. a\n2. b\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```\nx < y\n```\n\n> nota\n")
    assert "<h1>Título</h1>" in html
    assert "<strong>dato</strong>" in html and "<code>código</code>" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "<ul><li>uno</li><li>dos</li></ul>" in html
    assert "<ol><li>a</li><li>b</li></ol>" in html
    assert "<th>A</th>" in html and "<td>2</td>" in html
    assert "<pre><code>x &lt; y</code></pre>" in html
    assert "<blockquote>nota</blockquote>" in html


def test_template_keeps_its_child_sections_at_a_deeper_page_level(tmp_path):
    ws = _workspace(tmp_path)
    _docx(ws / docs_kit.EXPORT_DIR / "export.docx",
          _p("Brick Template", "Heading1") + _p("Intro de plantilla")
          + _p("Resumen", "Heading2") + _p("r") + _p("Seguridad", "Heading2") + _p("s")
          + _p("Brick IHM", "Heading1") + _p("Coordinación", "Heading2")
          + _p("Convenciones de nomenclatura", "Heading3") + _p("Las ramas usan feature/."))
    summary = docs_kit.run_workspace(ws)
    assert summary["page_level"] == 3 and summary["template"] == "Brick Template"
    new = (ws / docs_kit.OUT_DIR / "tareas" / "02-nueva-capacidad-de-mapas" / "TAREA.md").read_text(encoding="utf-8")
    assert "## Resumen" in new and "## Seguridad" in new


def test_a_template_in_the_bible_wins_over_the_export(tmp_path):
    ws = _workspace(tmp_path)
    (ws / docs_kit.BIBLE_DIR / "plantilla-capacidad.md").write_text(
        "# Plantilla de capacidad Appearance\n\n## Propósito\n\n## Consumer Guide\n", encoding="utf-8")
    summary = docs_kit.run_workspace(ws)
    assert summary["template"] == "Plantilla de capacidad Appearance"
    new = (ws / docs_kit.OUT_DIR / "tareas" / "02-nueva-capacidad-de-mapas" / "TAREA.md").read_text(encoding="utf-8")
    assert "## Consumer Guide" in new and "## Contratos" not in new


def test_index_warns_about_tasks_too_big_for_a_chat(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setattr(docs_kit, "CHAT_LIMIT_CHARS", 500)
    docs_kit.run_workspace(ws)
    index = (ws / docs_kit.OUT_DIR / "index.html").read_text(encoding="utf-8")
    assert "grande" in index


def test_instructions_without_a_page_stay_in_the_report_not_as_new_pages(tmp_path):
    ws = _workspace(tmp_path)
    (ws / docs_kit.LOCAL_DIR / "huerfana.md").write_text(
        "# Página que ya no existe\n\nInstrucciones de actualización: cambiar algo.\n", encoding="utf-8")
    summary = docs_kit.run_workspace(ws)
    assert not any("existe" in t for t in summary["tasks"])
    report = (ws / docs_kit.OUT_DIR / "informe.md").read_text(encoding="utf-8")
    assert "Página que ya no existe" in report


def test_only_drafts_that_ask_for_it_get_the_template(tmp_path):
    ws = _workspace(tmp_path)
    (ws / docs_kit.LOCAL_DIR / "guia.md").write_text(
        "# Guía de validación\n\nCada capacidad la valida otra persona.\n", encoding="utf-8")
    docs_kit.run_workspace(ws)
    tasks = ws / docs_kit.OUT_DIR / "tareas"
    guide = next(tasks.glob("*-nueva-guia-de-validacion")).joinpath("TAREA.md").read_text(encoding="utf-8")
    assert "## Plantilla" not in guide and "## Contratos" not in guide
    cap = next(tasks.glob("*-nueva-capacidad-de-mapas")).joinpath("TAREA.md").read_text(encoding="utf-8")
    assert "## Plantilla" in cap and "«…» marca dónde va contenido" in cap
    assert "no añadas contenido" in cap.lower()


def test_table_cells_keep_line_breaks():
    html = docs_kit.markdown_to_html("| A |\n| --- |\n| uno<br>dos |\n")
    assert "<td>uno<br>dos</td>" in html


def test_template_skeleton_drops_example_values():
    skeleton = docs_kit.template_skeleton(
        "# Brick Template\n\nEjemplo de relleno.\n\n## Resumen\n\n| 🟦 Resumen |\n| --- |\n"
        "| Nombre: Route Planner<br>Estado:  industrialized |\n\n"
        "| Permite planificar rutas. |\n| --- |\n\n"
        "### Cuándo usarlo\n\n- Integración multimodal\n- Correlación\n\nVersión: 2.1.0\n")
    assert "## Resumen" in skeleton and "### Cuándo usarlo" in skeleton
    assert "| 🟦 Resumen |" in skeleton
    assert "Nombre: …<br>Estado: …" in skeleton
    assert "Versión: …" in skeleton
    assert docs_kit.template_skeleton("| Contratos de entrada:<br>RouteRequest<br>Ver https://x |\n") \
        == "| Contratos de entrada: … |\n"
    for example in ("Route Planner", "industrialized", "planificar", "multimodal", "2.1.0", "relleno"):
        assert example not in skeleton


def test_unsupported_terms_flags_data_missing_from_the_sources():
    sources = "Tecnologías: … Versión: … La capa usa el mapa base. PROJ-1 está documentado."
    result = ("Permite ver capas.<br>Tecnologías: React, TypeScript<br>Versión: 1.0.0\n"
              "Lo mantiene el Equipo de Mapas con PROJ-12 y PROJ-1. Ver el mapa base.")
    assert docs_kit.unsupported_terms(result, sources) == ["1.0.0", "Equipo", "Mapas", "PROJ-12", "React", "TypeScript"]
    assert docs_kit.unsupported_terms("Ver el mapa base.", sources) == []
    assert docs_kit.unsupported_terms("- Para ver\n✅ Visualización\n(Opcional) x", sources) == []
    assert docs_kit.unsupported_terms("Añadida la sección «Ramas» y “Mapa”.", sources) == []


def test_review_flags_invented_data_in_changes_and_index(tmp_path):
    ws = _workspace(tmp_path)
    docs_kit.run_workspace(ws)
    task = ws / docs_kit.OUT_DIR / "tareas" / "01-actualizar-convenciones-de-nomenclatura"
    (task / "RESULTADO.md").write_text("# Convenciones de nomenclatura\n\nRamas con PROJ- según Kubernetes.\n",
                                       encoding="utf-8")
    docs_kit.run_workspace(ws)
    assert "Kubernetes" in (task / "CAMBIOS.html").read_text(encoding="utf-8")
    index = (ws / docs_kit.OUT_DIR / "index.html").read_text(encoding="utf-8")
    assert "1 dato sin fuente" in index


class FakeRun:
    """Stands in for subprocess.run: records the call, answers like the real CLI."""

    def __init__(self, stdout="# Hecho\n", returncode=0, write_last=None):
        self.calls, self.stdout, self.returncode, self.write_last = [], stdout, returncode, write_last

    def __call__(self, args, **kw):
        import subprocess
        self.calls.append((args, kw))
        if self.write_last and "--output-last-message" in args:
            Path(args[args.index("--output-last-message") + 1]).write_text(self.write_last, encoding="utf-8")
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "boom")


def test_bible_rule_only_when_there_is_a_bible(tmp_path):
    ws = _workspace(tmp_path)
    (ws / docs_kit.BIBLE_DIR / "estandares-repos.md").unlink()
    docs_kit.run_workspace(ws)
    task = (ws / docs_kit.OUT_DIR / "tareas" / "01-actualizar-convenciones-de-nomenclatura" / "TAREA.md")
    assert "Biblia" not in task.read_text(encoding="utf-8")


def test_copilot_reads_stdin_so_it_must_not_get_a_prompt_flag():
    run = FakeRun()
    docs_kit.cli_client("copilot", run=run, which=lambda name: name)("tarea")
    assert "-p" not in run.calls[0][0] and "--prompt" not in run.calls[0][0]


def test_cli_engines_take_the_prompt_on_stdin():
    for engine in ("claude", "codex", "gemini", "copilot"):
        run = FakeRun(write_last="# Hecho\n")
        ai = docs_kit.cli_client(engine, run=run, which=lambda name: f"/bin/{name}")
        assert ai("x" * 50_000) == "# Hecho\n"
        args, kw = run.calls[0]
        assert args[0] == f"/bin/{engine}"
        assert kw["input"] == "x" * 50_000 and all("x" * 100 not in a for a in args)
        assert kw["encoding"] == "utf-8" and kw["timeout"] > 0


def test_cli_engine_reports_missing_tool_and_failures():
    import pytest
    with pytest.raises(RuntimeError, match="no está instalado"):
        docs_kit.cli_client("codex", run=FakeRun(), which=lambda name: None)
    with pytest.raises(ValueError):
        docs_kit.cli_client("notepad", run=FakeRun(), which=lambda name: name)
    ai = docs_kit.cli_client("claude", run=FakeRun(returncode=1), which=lambda name: name)
    with pytest.raises(RuntimeError, match="boom"):
        ai("hola")


def test_one_failing_task_does_not_stop_the_others(tmp_path):
    ws = _workspace(tmp_path)

    def ai(prompt):
        if "capas tácticas" in prompt:
            raise RuntimeError("cuota agotada")
        return "# Convenciones de nomenclatura\n\nRamas con PROJ-.\n"

    summary = docs_kit.run_workspace(ws, ai=ai)
    assert summary["ready"] == ["01-actualizar-convenciones-de-nomenclatura"]
    index = (ws / docs_kit.OUT_DIR / "index.html").read_text(encoding="utf-8")
    assert "cuota agotada" in index


def test_cli_init_and_run(tmp_path, capsys):
    ws = _workspace(tmp_path)
    docs_kit.main(["run", str(ws), "--no-open"])
    assert (ws / docs_kit.OUT_DIR / "index.html").is_file()
    assert "index.html" in capsys.readouterr().out


def test_cli_flag_picks_an_agent_cli(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    picked = []
    monkeypatch.setattr(docs_kit, "cli_client", lambda engine: picked.append(engine) or (lambda p: "# Ok\n"))
    docs_kit.main(["run", str(ws), "--ai-cli", "codex", "--no-open"])
    assert picked == ["codex"]
    assert len(list((ws / docs_kit.OUT_DIR / "tareas").glob("*/RESULTADO.md"))) == 2


SKELETONS = Path(__file__).resolve().parents[1] / "src" / "amanuense" / "skeleton"
SKELETON = SKELETONS / "es"
SKILLS = ("actualizar-pagina-confluence", "auditar-documentacion", "nueva-pagina-confluence")


def _frontmatter(path: Path) -> dict:
    head = path.read_text(encoding="utf-8").split("---")[1]
    return dict(line.split(":", 1) for line in head.strip().splitlines() if ":" in line and not line.startswith(" "))


def test_export_agents_writes_native_files_for_every_tool(tmp_path):
    import tomllib
    docs_kit.export_agents(SKELETON, tmp_path)
    for name in SKILLS:
        source = (SKELETON / "skills" / name / "SKILL.md").read_bytes()
        assert (tmp_path / ".claude" / "skills" / name / "SKILL.md").read_bytes() == source
        assert (tmp_path / ".agents" / "skills" / name / "SKILL.md").read_bytes() == source
    agent = "curador-documentacion"
    claude = _frontmatter(tmp_path / ".claude" / "agents" / f"{agent}.md")
    assert claude["name"].strip() == agent and claude["description"].strip()
    assert "skills" in claude
    for tool in (".github", ".gemini"):
        fm = _frontmatter(tmp_path / tool / "agents" / f"{agent}.md")
        assert fm["description"].strip() and "skills" not in fm
    codex = tomllib.loads((tmp_path / ".codex" / "agents" / f"{agent}.toml").read_text(encoding="utf-8"))
    assert codex["name"] == agent and codex["description"]
    assert "# Curador de documentación" in codex["developer_instructions"]
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert "AGENTS.md" in settings["context"]["fileName"]
    assert (tmp_path / "AGENTS.md").read_bytes() == (SKELETON / "AGENTS.md").read_bytes()


@pytest.mark.parametrize("lang", ["en", "es"])
def test_skeleton_ships_its_native_files_in_sync(tmp_path, lang):
    skeleton = SKELETONS / lang
    written = docs_kit.export_agents(skeleton, tmp_path)
    assert written
    for path in written:
        rel = path.relative_to(tmp_path)
        shipped, fresh = ((skeleton / rel).read_bytes(), path.read_bytes())  # a Windows checkout may add CR
        assert shipped.replace(b"\r\n", b"\n") == fresh.replace(b"\r\n", b"\n"), f"run: amanuense agents {rel}"
