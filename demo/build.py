#!/usr/bin/env python3
"""Build the demo world: a made-up MIND space, a workshop and an Obsidian vault.

Everything here is fictitious (the space, the bricks, the people, the repo) so
the video never shows real documentation. The AI answers are scripted, which
keeps the demo reproducible; with a real engine the flow is the same.

    python demo/build.py [en|es]    # writes demo/out/<lang>/ (default en)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from amanuense import obsidian, taller  # noqa: E402

OUT = HERE / "out"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = {"Heading1": "heading 1", "Heading2": "heading 2", "Heading3": "heading 3"}

# The space as Confluence would export it: H1 brick, H2 page, H3 subpage.
WORLD = {
    "en": {
        "space": [
            (1, "Route Planner"), (0, "Brick that computes routes between two points for the other bricks."),
            (2, "Route Planner overview"), (0, "Computes the shortest route by road."),
            (0, "Maintained by the mobility team."),
            (2, "Route Planner contracts"), (0, "Contracts published in the schema registry."),
            (3, "RouteRequest"), (0, "Origin, destination and transport mode."),
            (3, "RouteResponse"), (0, "List of legs with distance and duration."),
            (2, "Route Planner deployment"), (0, "Repository: route-planner."), (0, "The service listens on port 8080."),
            (1, "Weather Layer"), (0, "Brick that adds the weather to the map."),
            (2, "Weather Layer overview"), (0, "Draws rain, wind and temperature on the map."),
            (2, "Weather Layer deployment"), (0, "Repository: weather-layer."), (0, "Data refreshes every 15 minutes."),
            (1, "Templates"),
            (2, "Brick Template"), (0, "Name: Example Brick"), (0, "Status: in development"), (0, "Owner: example team"),
            (0, "Summary: describe in two lines what the brick does."), (0, "Contracts: link the published contracts."),
        ],
        "edit": ("Computes the shortest route by road.", "Computes the shortest route by road, on foot or by public transport."),
        "local": {
            "Route Planner deployment.md": (
                "# Route Planner deployment\n\n"
                "Update instructions: the port becomes 8443 and the ROUTE_TIMEOUT variable is added "
                "(seconds the computation waits before giving up; 30 by default).\n"),
            "Traffic layer.md": (
                "# Traffic layer\n\nTemplate: yes\n\n"
                "New brick that draws traffic on the map from the city sensors. "
                "Maintained by the mobility team. Publishes the TrafficSnapshot contract.\n"),
        },
        "bible": ("Repo standards.md", "# Repo standards\n\n- Every brick documents its port and its environment variables.\n"
                  "- Contracts are published in the schema registry before deploying.\n"),
        "request": "- Ana Ruiz: Weather Layer data now refreshes every 5 minutes\n",
        "results": {
            "Route Planner deployment": (
                "# Route Planner deployment\n\nRepository: route-planner.\n\n"
                "| Setting | Value |\n| --- | --- |\n| Port | 8443 |\n"
                "| ROUTE_TIMEOUT | Seconds the computation waits before giving up (30 by default) |\n\n"
                "See the page \"Route Planner contracts\".\n\n"
                "## Change log\n\n- Port 8080 → 8443.\n- New ROUTE_TIMEOUT variable.\n"),
            "Traffic layer": (
                "# Traffic layer\n\n## Summary\n\n| Field | Value |\n| --- | --- |\n| Name | Traffic layer |\n"
                "| Status | > PENDING: brick status |\n| Owner | mobility team |\n\n"
                "Draws traffic on the map from the city sensors, with a latency of 200 ms.\n\n"
                "## Contracts\n\n- TrafficSnapshot\n\n## Change log\n\n- New page from the draft.\n"),
            "Weather Layer deployment": (
                "# Weather Layer deployment\n\nRepository: weather-layer.\n\nData refreshes every 5 minutes.\n\n"
                "> CONFLICT: Ana Ruiz asks for 5 minutes, but the weather-layer README still says 15.\n\n"
                "## Change log\n\n- Refresh from 15 to 5 minutes, requested by Ana Ruiz.\n"),
        },
        "route": {"page": "Weather Layer deployment", "change": "data refresh from 15 to 5 minutes",
                  "reason": "the weather provider publishes every 5 minutes"},
        "version": ("Route Planner overview", "adds the walking and public transport modes"),
        "repos": "# Local clones",
    },
    "es": {
        "space": [
            (1, "Route Planner"), (0, "Brick que calcula rutas entre dos puntos para el resto de bricks."),
            (2, "Visión general de Route Planner"), (0, "Calcula la ruta más corta por carretera."),
            (0, "Lo mantiene el equipo de movilidad."),
            (2, "Contratos de Route Planner"), (0, "Contratos publicados en el registro de esquemas."),
            (3, "RouteRequest"), (0, "Origen, destino y modo de transporte."),
            (3, "RouteResponse"), (0, "Lista de tramos con distancia y duración."),
            (2, "Despliegue de Route Planner"), (0, "Repositorio: route-planner."), (0, "El servicio escucha en el puerto 8080."),
            (1, "Weather Layer"), (0, "Brick que añade la meteorología al mapa."),
            (2, "Visión general de Weather Layer"), (0, "Pinta lluvia, viento y temperatura sobre el mapa."),
            (2, "Despliegue de Weather Layer"), (0, "Repositorio: weather-layer."), (0, "Los datos se refrescan cada 15 minutos."),
            (1, "Plantillas"),
            (2, "Brick Template"), (0, "Nombre: Example Brick"), (0, "Estado: en desarrollo"), (0, "Responsable: equipo de ejemplo"),
            (0, "Resumen: describe en dos líneas qué hace el brick."), (0, "Contratos: enlaza los contratos publicados."),
        ],
        "edit": ("Calcula la ruta más corta por carretera.",
                 "Calcula la ruta más corta por carretera, a pie o en transporte público."),
        "local": {
            "Despliegue de Route Planner.md": (
                "# Despliegue de Route Planner\n\n"
                "Instrucciones de actualización: el puerto pasa a ser 8443 y se añade la variable ROUTE_TIMEOUT "
                "(segundos que espera el cálculo antes de rendirse; por defecto 30).\n"),
            "Capa de tráfico.md": (
                "# Capa de tráfico\n\nPlantilla: sí\n\n"
                "Brick nuevo que pinta el estado del tráfico sobre el mapa a partir de los sensores municipales. "
                "Lo mantiene el equipo de movilidad. Publica el contrato TrafficSnapshot.\n"),
        },
        "bible": ("Estándares de repos.md", "# Estándares de repos\n\n- Cada brick documenta su puerto y sus variables de entorno.\n"
                  "- Los contratos se publican en el registro de esquemas antes de desplegar.\n"),
        "request": "- Ana Ruiz: en Weather Layer los datos ahora se refrescan cada 5 minutos\n",
        "results": {
            "Despliegue de Route Planner": (
                "# Despliegue de Route Planner\n\nRepositorio: route-planner.\n\n"
                "| Parámetro | Valor |\n| --- | --- |\n| Puerto | 8443 |\n"
                "| ROUTE_TIMEOUT | Segundos que espera el cálculo antes de rendirse (por defecto 30) |\n\n"
                "Ver la página «Contratos de Route Planner».\n\n"
                "## Registro de cambios\n\n- Puerto 8080 → 8443.\n- Nueva variable ROUTE_TIMEOUT.\n"),
            "Capa de tráfico": (
                "# Capa de tráfico\n\n## Resumen\n\n| Campo | Valor |\n| --- | --- |\n| Nombre | Capa de tráfico |\n"
                "| Estado | > PENDIENTE: estado del brick |\n| Responsable | equipo de movilidad |\n\n"
                "Pinta el estado del tráfico sobre el mapa a partir de los sensores municipales, "
                "con una latencia de 200 ms.\n\n"
                "## Contratos\n\n- TrafficSnapshot\n\n## Registro de cambios\n\n- Página nueva a partir del borrador.\n"),
            "Despliegue de Weather Layer": (
                "# Despliegue de Weather Layer\n\nRepositorio: weather-layer.\n\nLos datos se refrescan cada 5 minutos.\n\n"
                "> CONFLICTO: Ana Ruiz pide 5 minutos, pero el README de weather-layer sigue diciendo 15.\n\n"
                "## Registro de cambios\n\n- Refresco de 15 a 5 minutos, a petición de Ana Ruiz.\n"),
        },
        "route": {"pagina": "Despliegue de Weather Layer", "cambio": "refresco de datos de 15 a 5 minutos",
                  "motivo": "el proveedor meteorológico publica cada 5 minutos"},
        "version": ("Visión general de Route Planner", "añade los modos a pie y transporte público"),
        "repos": "# Clones locales",
    },
}


def docx(path: Path, blocks: list[tuple[int, str]], created: str) -> Path:
    def p(level, text):
        style = f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>' if level else ""
        return f"<w:p>{style}<w:r><w:t>{text}</w:t></w:r></w:p>"
    st = "".join(f'<w:style w:styleId="{k}"><w:name w:val="{v}"/></w:style>' for k, v in STYLES.items())
    core = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created></cp:coreProperties>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f"<w:document {W}><w:body>{''.join(p(l, t) for l, t in blocks)}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{st}</w:styles>")
        z.writestr("docProps/core.xml", core)
    return path


class DemoHistory:
    """What the Confluence API would answer for the pages edited between exports."""

    def __init__(self, world: dict):
        title, message = world["version"]
        self.versions = {title: [{"number": 4, "by": "Luis Pardo", "when": "2026-10-09T11:20:00+02:00",
                                  "message": message}]}

    def changes(self, title: str, since: str) -> list[dict]:
        return self.versions.get(title, [])


def scripted_ai(world: dict):
    def answer(prompt: str) -> str:
        if "\n## Pages\n" in prompt or "\n## Páginas\n" in prompt:  # a request to route
            return json.dumps(world["route"], ensure_ascii=False)
        first = prompt.splitlines()[0]
        return next(text for title, text in world["results"].items() if title in first)
    return answer


def git(repo: Path, *args: str, who: str = "Marta Gil", when: str = "") -> None:
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}
    subprocess.run(["git", "-c", f"user.name={who}", "-c", "user.email=demo@example.com", *args],
                   cwd=repo, check=True, capture_output=True, env={**os.environ, **env})


def main(lang: str = "en") -> Path:
    """Builds demo/out/<lang>/: the workshop after three runs, the code repo and the vault."""
    from amanuense import i18n
    world, out = WORLD[lang], OUT / lang
    os.environ["AMANUENSE_USER"] = "Rosa Vidal"
    shutil.rmtree(out, ignore_errors=True)
    ws = out / "workshop"
    taller.init_workspace(ws, lang)
    n = i18n.name
    for name, text in world["local"].items():
        (ws / n("local") / name).write_text(text, encoding="utf-8")
    bible_name, bible = world["bible"]
    (ws / n("bible") / bible_name).write_text(bible, encoding="utf-8")

    repo = out / "repos" / "route-planner"
    (repo / "config").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "config" / "route_timeout.py").write_text("ROUTE_TIMEOUT = 30\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "feat: add ROUTE_TIMEOUT setting", when="2026-10-07T16:05:00+02:00")
    (ws / n("repos")).write_text(f"{world['repos']}\n{repo}\n", encoding="utf-8")

    ai = scripted_ai(world)
    export = ws / n("export") / "MIND-Bricks.docx"
    docx(export, world["space"], "2026-10-01T09:00:00Z")
    taller.run_workspace(ws, ai=ai)

    before, after = world["edit"]
    docx(export, [(lvl, text.replace(before, after)) for lvl, text in world["space"]], "2026-10-10T09:00:00Z")
    requests = ws / n("requests")
    requests.write_text(requests.read_text(encoding="utf-8") + world["request"], encoding="utf-8")
    history = DemoHistory(world)
    taller.run_workspace(ws, ai=ai, history=history, router=ai)
    taller.run_workspace(ws, ai=ai, history=history, router=ai)  # the request's result

    vault = out / "vault"
    obsidian.export_to_vault(export, vault / "MIND")
    conf = vault / ".obsidian"
    (conf / "snippets").mkdir(parents=True)
    shutil.copy(HERE.parent / "assets" / "obsidian" / "letravora.css", conf / "snippets" / "letravora.css")
    (conf / "appearance.json").write_text(json.dumps({"theme": "obsidian", "enabledCssSnippets": ["letravora"],
                                                      "baseFontSize": 17}), encoding="utf-8")
    (conf / "app.json").write_text(json.dumps({"showInlineTitle": False}), encoding="utf-8")
    print(f"demo world in {out}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "en")
