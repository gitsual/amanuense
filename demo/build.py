#!/usr/bin/env python3
"""Build the demo world: a made-up team, its Confluence space, its code, and three radar passes.

Quillmere Trams is fictitious, and so are its people, repos and pages: the video never shows
real documentation. The world is built by the real tools: scripts/radar.sh runs the workshop
three mornings in a row against demo/fakes.py, a local stand-in for Confluence, the AI and
the npm registry. The AI answers are scripted, which keeps the take reproducible; with a real
engine the flow is the same. Only the clock of the radar passes is staged.

    python demo/build.py [en|es]    # writes demo/out/<lang>/ (default en); needs git and bash
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import fakes  # noqa: E402
from amanuense import i18n, obsidian  # noqa: E402

OUT = HERE / "out"
STAGE_PORT = 47110  # fixed, so the registry address the radiator shows is the same every take
USER = "Clara Ortega"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"}
EXPORTS = ("2026-10-01T09:00:00Z", "2026-10-12T18:00:00Z")
# The radar runs at 07:30 UTC; the third morning finds nothing new.
PASSES = ("2026-10-12 07:30 UTC", "2026-10-13 07:30 UTC", "2026-10-14 07:30 UTC")

# ── The world, in each language ───────────────────────────────────────────────
# "space" is the space as Confluence exports it: H1 capability, H2 page, H3 subpage.
WORLD = {
    "en": {
        "space": [
            (1, "Departures Board"), (0, "Capability that shows the next trams at every stop."),
            (2, "Departures Board overview"), (0, "Shows the next three trams per platform."),
            (0, "Maintained by the passenger information team."),
            (2, "Departures Board contracts"), (0, "Contracts published in the schema registry."),
            (3, "DepartureList"), (0, "Stop, line, destination and minutes to arrival."),
            (3, "StopId"), (0, "Identifier of a stop, shared with the journey planner."),
            (2, "Departures Board deployment"), (0, "Repository: departures-board."),
            (0, "The service listens on port 8080."), (0, "Departures refresh every 30 seconds."),
            (1, "Service Alerts"), (0, "Capability that tells passengers about disruptions."),
            (2, "Service Alerts overview"), (0, "Capability that tells passengers about disruptions on the boards and in the app."),
            (0, "Alerts reach the boards within 2 minutes."), (0, "The alert feed is polled every 60 seconds."),
            (2, "Service Alerts deployment"), (0, "Repository: service-alerts."), (0, "Alerts are kept for 24 hours."),
            (1, "Fare Engine"), (0, "Capability that prices every journey."),
            (2, "Fare Engine overview"), (0, "Computes the fare of a journey from zones and passenger type."),
            (2, "Fare Engine deployment"), (0, "Repository: fare-engine."), (0, "The service listens on port 8090."),
            (1, "Templates"),
            (2, "Capability Template"), (0, "Name: Example capability"), (0, "Status: in development"),
            (0, "Owner: example team"), (0, "Summary: two lines on what the capability does."),
            (0, "Contracts: link the published contracts."),
        ],
        "edit": ("Computes the fare of a journey from zones and passenger type.",
                 "Computes the fare of a journey from zones and passenger type, and applies the off-peak discount."),
        "edited": ("Fare Engine overview", "Adds the off-peak discount"),
        "local": {
            "Departures Board deployment.md": (
                "# Departures Board deployment\n\n"
                "Update instructions: the port becomes 8443 and the DEPARTURES_TIMEOUT variable is added "
                "(seconds the board waits for the timetable service before it shows cached departures; "
                "8 by default).\n"),
            "Night Service.md": (
                "# Night Service\n\nTemplate: yes\n\n"
                "New capability that shows the night trams on the boards, from 00:30 to 05:00. "
                "Maintained by the passenger information team. Publishes the NightTimetable contract.\n"),
        },
        "bible": ("Release standards.md", "# Release standards\n\n"
                  "- Every capability documents its port and its environment variables.\n"
                  "- Contracts are published in the schema registry before deploying.\n"),
        "request": "- Samir Haddad: alerts must reach the boards within 30 seconds, not 2 minutes\n",
        "route": {"page": "Service Alerts overview", "change": "delivery target from 2 minutes to 30 seconds",
                  "reason": "this page states the 2-minute target that the request replaces"},
        "triage": {
            "Service Alerts deployment": {
                "categoria": "actualizar", "motivo": "The page says alerts are kept for 24 hours; the commit keeps them for 72.",
                "cambios": ["Deployment: alerts are kept for 72 hours, not 24."]},
            "Fare Engine deployment": {
                "categoria": "ruido", "motivo": "It only fixes a typo in the README; nothing the page says changes.",
                "cambios": []},
        },
        "results": {
            "Departures Board deployment": (
                "# Departures Board deployment\n\nRepository: departures-board.\n\n"
                "| Setting | Value |\n| --- | --- |\n| Port | 8443 |\n"
                "| DEPARTURES_TIMEOUT | Seconds the board waits for the timetable service before it shows "
                "cached departures (8 by default) |\n\n"
                "Departures refresh every 30 seconds.\n\n"
                "## Change log\n\n- Port 8080 → 8443.\n- New DEPARTURES_TIMEOUT variable.\n"),
            "Night Service": (
                "# Night Service\n\n## Summary\n\n| Field | Value |\n| --- | --- |\n| Name | Night Service |\n"
                "| Owner | passenger information team |\n\n"
                "> PENDING: the status of the capability.\n\n"
                "Shows the night trams on the boards from 00:30 to 05:00, with a tram every 20 minutes.\n\n"
                "## Contracts\n\n- NightTimetable\n\n## Change log\n\n- New page from the draft.\n"),
            "Service Alerts overview": (
                "# Service Alerts overview\n\n"
                "Capability that tells passengers about disruptions on the boards and in the app.\n\n"
                "Alerts reach the boards within 30 seconds.\n\n"
                "> CONFLICT: Samir Haddad asks for 30 seconds, but this page says the alert feed is polled "
                "every 60 seconds.\n\n"
                "## Change log\n\n- Delivery target from 2 minutes to 30 seconds, requested by Samir Haddad.\n"),
            "Service Alerts deployment": (
                "# Service Alerts deployment\n\nRepository: service-alerts.\n\n"
                "Alerts are kept for 72 hours.\n\n"
                "## Change log\n\n- Alerts are kept for 72 hours instead of 24, as the code now does.\n"),
        },
        "decision": "Alerts reach the boards within 30 seconds; the feed is polled every 10 seconds from release 4.2.",
        "vault": "Quillmere",
    },
    "es": {
        "space": [
            (1, "Panel de salidas"), (0, "Capacidad que muestra los próximos tranvías en cada parada."),
            (2, "Visión general del panel de salidas"), (0, "Muestra los tres próximos tranvías de cada andén."),
            (0, "Lo mantiene el equipo de información al viajero."),
            (2, "Contratos del panel de salidas"), (0, "Contratos publicados en el registro de esquemas."),
            (3, "DepartureList"), (0, "Parada, línea, destino y minutos para la llegada."),
            (3, "StopId"), (0, "Identificador de una parada, compartido con el planificador de viajes."),
            (2, "Despliegue del panel de salidas"), (0, "Repositorio: departures-board."),
            (0, "El servicio escucha en el puerto 8080."), (0, "Las salidas se refrescan cada 30 segundos."),
            (1, "Avisos de servicio"), (0, "Capacidad que informa a los viajeros de las incidencias."),
            (2, "Visión general de los avisos"), (0, "Capacidad que informa a los viajeros de las incidencias en los paneles y en la app."),
            (0, "Los avisos llegan a los paneles en menos de 2 minutos."), (0, "El canal de avisos se consulta cada 60 segundos."),
            (2, "Despliegue de los avisos"), (0, "Repositorio: service-alerts."), (0, "Los avisos se guardan 24 horas."),
            (1, "Motor de tarifas"), (0, "Capacidad que pone precio a cada viaje."),
            (2, "Visión general del motor de tarifas"), (0, "Calcula la tarifa de un viaje según las zonas y el tipo de viajero."),
            (2, "Despliegue del motor de tarifas"), (0, "Repositorio: fare-engine."), (0, "El servicio escucha en el puerto 8090."),
            (1, "Plantillas"),
            (2, "Plantilla de capacidad"), (0, "Nombre: Capacidad de ejemplo"), (0, "Estado: en desarrollo"),
            (0, "Responsable: equipo de ejemplo"), (0, "Resumen: dos líneas sobre qué hace la capacidad."),
            (0, "Contratos: enlaza los contratos publicados."),
        ],
        "edit": ("Calcula la tarifa de un viaje según las zonas y el tipo de viajero.",
                 "Calcula la tarifa de un viaje según las zonas y el tipo de viajero, y aplica el descuento de horas valle."),
        "edited": ("Visión general del motor de tarifas", "Añade el descuento de horas valle"),
        "local": {
            "Despliegue del panel de salidas.md": (
                "# Despliegue del panel de salidas\n\n"
                "Instrucciones de actualización: el puerto pasa a ser 8443 y se añade la variable DEPARTURES_TIMEOUT "
                "(segundos que espera el panel al servicio de horarios antes de mostrar las salidas en caché; "
                "por defecto 8).\n"),
            "Servicio nocturno.md": (
                "# Servicio nocturno\n\nPlantilla: sí\n\n"
                "Capacidad nueva que muestra los tranvías nocturnos en los paneles, de 00:30 a 05:00. "
                "La mantiene el equipo de información al viajero. Publica el contrato NightTimetable.\n"),
        },
        "bible": ("Normas de publicación.md", "# Normas de publicación\n\n"
                  "- Cada capacidad documenta su puerto y sus variables de entorno.\n"
                  "- Los contratos se publican en el registro de esquemas antes de desplegar.\n"),
        "request": "- Samir Haddad: los avisos tienen que llegar a los paneles en 30 segundos, no en 2 minutos\n",
        "route": {"pagina": "Visión general de los avisos", "cambio": "objetivo de entrega de 2 minutos a 30 segundos",
                  "motivo": "esta página fija el objetivo de 2 minutos que la petición sustituye"},
        "triage": {
            "Despliegue de los avisos": {
                "categoria": "actualizar", "motivo": "La página dice que los avisos se guardan 24 horas; el commit los guarda 72.",
                "cambios": ["Despliegue: los avisos se guardan 72 horas, no 24."]},
            "Despliegue del motor de tarifas": {
                "categoria": "ruido", "motivo": "Sólo corrige una errata del README; no cambia nada de lo que dice la página.",
                "cambios": []},
        },
        "results": {
            "Despliegue del panel de salidas": (
                "# Despliegue del panel de salidas\n\nRepositorio: departures-board.\n\n"
                "| Parámetro | Valor |\n| --- | --- |\n| Puerto | 8443 |\n"
                "| DEPARTURES_TIMEOUT | Segundos que espera el panel al servicio de horarios antes de mostrar "
                "las salidas en caché (por defecto 8) |\n\n"
                "Las salidas se refrescan cada 30 segundos.\n\n"
                "## Registro de cambios\n\n- Puerto 8080 → 8443.\n- Nueva variable DEPARTURES_TIMEOUT.\n"),
            "Servicio nocturno": (
                "# Servicio nocturno\n\n## Resumen\n\n| Campo | Valor |\n| --- | --- |\n| Nombre | Servicio nocturno |\n"
                "| Responsable | equipo de información al viajero |\n\n"
                "> PENDIENTE: el estado de la capacidad.\n\n"
                "Muestra los tranvías nocturnos en los paneles de 00:30 a 05:00, con un tranvía cada 20 minutos.\n\n"
                "## Contratos\n\n- NightTimetable\n\n## Registro de cambios\n\n- Página nueva a partir del borrador.\n"),
            "Visión general de los avisos": (
                "# Visión general de los avisos\n\n"
                "Capacidad que informa a los viajeros de las incidencias en los paneles y en la app.\n\n"
                "Los avisos llegan a los paneles en menos de 30 segundos.\n\n"
                "> CONFLICTO: Samir Haddad pide 30 segundos, pero esta página dice que el canal de avisos se "
                "consulta cada 60 segundos.\n\n"
                "## Registro de cambios\n\n- Objetivo de entrega de 2 minutos a 30 segundos, a petición de Samir Haddad.\n"),
            "Despliegue de los avisos": (
                "# Despliegue de los avisos\n\nRepositorio: service-alerts.\n\n"
                "Los avisos se guardan 72 horas.\n\n"
                "## Registro de cambios\n\n- Los avisos se guardan 72 horas en vez de 24, como ya hace el código.\n"),
        },
        "decision": "Los avisos llegan a los paneles en menos de 30 segundos; desde la versión 4.2 el canal se consulta cada 10 segundos.",
        "vault": "Quillmere",
    },
}

# The code: three repos with npm packages, on main and develop. Commit messages stay in English.
REPOS = {
    "departures-board": {"package": "@quillmere/departures-board", "main": "2.3.0", "develop": "2.4.0-rc.1",
                         "category": "passenger", "description": "Next trams at every stop, on boards and in the app."},
    "service-alerts": {"package": "@quillmere/service-alerts", "main": "1.8.0", "develop": "1.9.0-rc.1",
                       "category": "passenger", "description": "Disruption alerts for boards and the app."},
    "fare-engine": {"package": "@quillmere/fare-engine", "main": "0.9.0", "develop": "0.10.0-beta.2",
                    "category": "payments", "description": "Prices every journey from zones and passenger type."},
}
REGISTRY = {"@quillmere/departures-board": ["2.2.0", "2.3.0"], "@quillmere/service-alerts": ["1.7.1", "1.8.0"]}
# Pushed between the first and the second morning.
NEW_COMMITS = [
    ("service-alerts", "Priya Nair", "2026-10-12T16:40:00+02:00", "config/retention.py",
     "ALERT_RETENTION_HOURS = 72\n", "feat: keep alerts for 72 hours"),
    ("fare-engine", "Tomás Reyes", "2026-10-12T17:05:00+02:00", "README.md",
     "# fare-engine\n\nPrices every journey.\n", "docs: fix a typo in the README"),
]


def stage_world(lang: str) -> dict:
    """What the fake services need: the scripted answers, the registry and the pages in Confluence."""
    world = WORLD[lang]
    edited_title, message = world["edited"]
    titles = [text for level, text in world["space"] if level]
    confluence = []
    for title in titles:
        body = _storage(world, title)
        if title == edited_title:
            history = [(1, "2026-06-03T10:00:00.000+02:00", "Jonas Weber", ""),
                       (2, "2026-09-20T12:30:00.000+02:00", "Jonas Weber", ""),
                       (3, "2026-10-12T15:10:00.000+02:00", "Jonas Weber", message)]
        else:
            history = [(1, "2026-06-03T10:00:00.000+02:00", "Jonas Weber", ""),
                       (2, "2026-10-02T11:00:00.000+02:00", "Jonas Weber", "")]
        confluence.append((title, history, body))
    return {**world, "registry": REGISTRY, "confluence": confluence, "editor": USER,
            "now": "2026-10-14T09:12:00.000+02:00"}


def _storage(world: dict, title: str) -> str:
    """The page body as Confluence stores it: its paragraphs of the latest export."""
    blocks, inside = [], False
    before, after = world["edit"]
    for level, text in world["space"]:
        if level:
            inside = text == title
        elif inside:
            blocks.append(f"<p>{html.escape(text.replace(before, after))}</p>")
    return "".join(blocks) or "<p></p>"


def docx(path: Path, blocks: list[tuple[int, str]], created: str) -> Path:
    def p(level, text):
        style = f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>' if level else ""
        return f"<w:p>{style}<w:r><w:t>{html.escape(text)}</w:t></w:r></w:p>"
    st = "".join(f'<w:style w:styleId="{k}"><w:name w:val="{v}"/></w:style>' for k, v in STYLES.items())
    core = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created></cp:coreProperties>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f"<w:document {W}><w:body>{''.join(p(lv, t) for lv, t in blocks)}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
        z.writestr("docProps/core.xml", core)
    return path


def git(repo: Path, *args: str, who: str = "Priya Nair", when: str = "2025-03-03T10:00:00+01:00") -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": who,
           "GIT_COMMITTER_NAME": who, "GIT_AUTHOR_EMAIL": "dev@quillmere.example",
           "GIT_COMMITTER_EMAIL": "dev@quillmere.example"}
    return subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                          cwd=repo, check=True, capture_output=True, text=True, env=env).stdout


def code_repo(path: Path, name: str, spec: dict) -> None:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    meta = {"classification": {"category": spec["category"], "audience": "riders"}}

    def manifest(version: str) -> None:
        (path / "package.json").write_text(json.dumps(
            {"name": spec["package"], "version": version, "description": spec["description"],
             "dependencies": {"@quillmere/stop-contract": "^1.2.0"}}, indent=2) + "\n")
        (path / "brick.metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    manifest(spec["main"])
    (path / "README.md").write_text(f"# {name}\n\nPrices every jounrey.\n" if name == "fare-engine" else f"# {name}\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", f"feat: first release of {name}")
    git(path, "checkout", "-qb", "develop")
    manifest(spec["develop"])
    git(path, "commit", "-qam", f"chore: start {spec['develop']}", when="2025-04-07T10:00:00+02:00")
    git(path, "checkout", "-q", "main")


def radar_pass(team: Path, ws: Path, when: str, server, lang: str, shim: Path) -> str:
    """One real scripts/radar.sh pass, its clock staged at `when`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AMANUENSE_")}
    stamp = f"{when[:10]}T{when[11:16]}:00+00:00"
    env.update(AMANUENSE_USER=USER, AMANUENSE_LANG=lang, FAKE_NOW=when, PATH=f"{shim}{os.pathsep}{env['PATH']}",
               GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp,
               AMANUENSE_CONFLUENCE_URL=server.base, AMANUENSE_CONFLUENCE_TOKEN=fakes.TOKEN,
               AMANUENSE_CONFLUENCE_SPACE=fakes.SPACE)
    empty = team.parent / "radar.env"
    empty.write_text("", encoding="utf-8")
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "radar.sh"), "--workspace", str(ws), "--env", str(empty),
                           "--commit", "--", "--ai-url", f"{server.base}/v1", "--ai-model", fakes.MODEL],
                          cwd=team, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"radar pass failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def main(lang: str = "en") -> Path:
    """Builds demo/out/<lang>/: the code repos, the team repo with its workshop, and the vault."""
    i18n.use(lang)
    n = i18n.name
    world, out = WORLD[lang], OUT / lang
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    repos = out / "code"
    for name, spec in REPOS.items():
        code_repo(repos / name, name, spec)

    # The team repo; the workshop lives in it, so the radar's snapshots are its history.
    team = out / "team"
    team.mkdir()
    git(team, "init", "-q")
    git(team, "config", "user.name", "Quillmere radar")
    git(team, "config", "user.email", "radar@quillmere.example")
    (team / "README.md").write_text("# Quillmere Trams · documentation\n\nThe workshop lives in docs-workshop/.\n")
    git(team, "add", ".")
    git(team, "commit", "-qm", "chore: start the documentation repo", who=USER, when="2026-10-09T09:00:00+02:00")
    ws = team / "docs-workshop"
    from amanuense import taller
    taller.init_workspace(ws, lang)
    for name, text in world["local"].items():
        (ws / n("local") / name).write_text(text, encoding="utf-8")
    bible_name, bible = world["bible"]
    (ws / n("bible") / bible_name).write_text(bible, encoding="utf-8")
    (ws / n("repos")).write_text("".join(f"{repos / name} @ *\n" for name in REPOS), encoding="utf-8")
    (ws / "radiador.json").write_text(json.dumps(
        {"scope": "@quillmere", "registry": f"http://localhost:{STAGE_PORT}/npm",
         "categories": {"passenger": "Passenger information" if lang == "en" else "Información al viajero",
                        "payments": "Payments" if lang == "en" else "Pagos"}}, indent=2) + "\n", encoding="utf-8")
    export = ws / n("export") / "Quillmere-Trams.docx"
    docx(export, world["space"], EXPORTS[0])

    shim = out / "shim"  # the staged clock for the radar's own messages
    shim.mkdir()
    (shim / "date").write_text('#!/bin/sh\nexec /usr/bin/date -d "$FAKE_NOW" "$@"\n')
    (shim / "date").chmod(0o755)

    server = fakes.start(stage_world(lang), port=STAGE_PORT)
    try:
        passes = [radar_pass(team, ws, PASSES[0], server, lang, shim)]
        # During the day: an edit in Confluence, two commits, a request and a fresh export.
        before, after = world["edit"]
        docx(export, [(lvl, text.replace(before, after)) for lvl, text in world["space"]], EXPORTS[1])
        for name, who, when, path, text, subject in NEW_COMMITS:
            repo = repos / name
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
            git(repo, "add", ".")
            git(repo, "commit", "-qm", subject, who=who, when=when)
        requests = ws / n("requests")
        requests.write_text(requests.read_text(encoding="utf-8") + world["request"], encoding="utf-8")
        passes.append(radar_pass(team, ws, PASSES[1], server, lang, shim))
        passes.append(radar_pass(team, ws, PASSES[2], server, lang, shim))
    finally:
        server.shutdown()
        server.server_close()
    (out / "radar-passes.json").write_text(json.dumps(passes, ensure_ascii=False, indent=1), encoding="utf-8")

    vault = out / "vault"
    obsidian.export_to_vault(export, vault / world["vault"])
    conf = vault / ".obsidian"
    (conf / "snippets").mkdir(parents=True)
    shutil.copy(ROOT / "assets" / "obsidian" / "letravora.css", conf / "snippets" / "letravora.css")
    (conf / "appearance.json").write_text(json.dumps({"theme": "obsidian", "enabledCssSnippets": ["letravora"],
                                                      "baseFontSize": 17}), encoding="utf-8")
    (conf / "app.json").write_text(json.dumps({"showInlineTitle": False}), encoding="utf-8")
    print(f"demo world in {out}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "en")
