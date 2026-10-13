#!/usr/bin/env python3
"""Build the demo world: a made-up MIND space, a workshop and an Obsidian vault.

Everything here is fictitious (the space, the bricks, the people, the repo) so
the video never shows real documentation. The AI answers are scripted, which
keeps the demo reproducible; with a real engine the flow is the same.

    python demo/build.py            # writes demo/out/
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
SPACE_V1 = [
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
]
SPACE_V2 = [(lvl, text.replace("Calcula la ruta más corta por carretera.",
                               "Calcula la ruta más corta por carretera, a pie o en transporte público."))
            for lvl, text in SPACE_V1]

LOCAL = {
    "Despliegue de Route Planner.md": (
        "# Despliegue de Route Planner\n\n"
        "Instrucciones de actualización: el puerto pasa a ser 8443 y se añade la variable ROUTE_TIMEOUT "
        "(segundos que espera el cálculo antes de rendirse; por defecto 30).\n"),
    "Capa de tráfico.md": (
        "# Capa de tráfico\n\nPlantilla: sí\n\n"
        "Brick nuevo que pinta el estado del tráfico sobre el mapa a partir de los sensores municipales. "
        "Lo mantiene el equipo de movilidad. Publica el contrato TrafficSnapshot.\n"),
}
BIBLE = ("# Estándares de repos\n\n- Cada brick documenta su puerto y sus variables de entorno.\n"
         "- Los contratos se publican en el registro de esquemas antes de desplegar.\n")
REQUEST = "- Ana Ruiz: en Weather Layer los datos ahora se refrescan cada 5 minutos\n"

RESULTS = {
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
        "## Registro de cambios\n\n- Refresco de 15 a 5 minutos, a petición de Ana Ruiz.\n"),
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

    VERSIONS = {"Visión general de Route Planner": [
        {"number": 4, "by": "Luis Pardo", "when": "2026-10-09T11:20:00+02:00", "message": "añade los modos a pie y transporte público"}]}

    def changes(self, title: str, since: str) -> list[dict]:
        return self.VERSIONS.get(title, [])


def scripted_ai(prompt: str) -> str:
    if prompt.startswith("Eres el curador"):
        return json.dumps({"pagina": "Despliegue de Weather Layer", "cambio": "refresco de datos de 15 a 5 minutos",
                           "motivo": "el proveedor meteorológico publica cada 5 minutos"}, ensure_ascii=False)
    title = prompt.split("«", 1)[1].split("»", 1)[0]
    return RESULTS[title]


def git(repo: Path, *args: str, who: str = "Marta Gil", when: str = "") -> None:
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}
    subprocess.run(["git", "-c", f"user.name={who}", "-c", "user.email=demo@example.com", *args],
                   cwd=repo, check=True, capture_output=True, env={**os.environ, **env})


def main() -> None:
    os.environ["AMANUENSE_USER"] = "Rosa Vidal"
    for part in ("taller", "repos", "vault"):
        shutil.rmtree(OUT / part, ignore_errors=True)
    ws = OUT / "taller"
    taller.init_workspace(ws)
    for name, text in LOCAL.items():
        (ws / taller.LOCAL_DIR / name).write_text(text, encoding="utf-8")
    (ws / taller.BIBLE_DIR / "Estándares de repos.md").write_text(BIBLE, encoding="utf-8")

    repo = OUT / "repos" / "route-planner"
    (repo / "config").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "config" / "route_timeout.py").write_text("ROUTE_TIMEOUT = 30\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "feat: add ROUTE_TIMEOUT setting", when="2026-10-07T16:05:00+02:00")
    (ws / "repos.txt").write_text(f"# Clones locales\n{repo}\n", encoding="utf-8")

    export = ws / taller.EXPORT_DIR / "MIND-Bricks.docx"
    docx(export, SPACE_V1, "2026-10-01T09:00:00Z")
    taller.run_workspace(ws, ai=scripted_ai)

    docx(export, SPACE_V2, "2026-10-10T09:00:00Z")
    (ws / "peticiones.md").write_text((ws / "peticiones.md").read_text(encoding="utf-8") + REQUEST, encoding="utf-8")
    taller.run_workspace(ws, ai=scripted_ai, history=DemoHistory(), router=scripted_ai)
    taller.run_workspace(ws, ai=scripted_ai, history=DemoHistory(), router=scripted_ai)  # request result

    vault = OUT / "vault"
    obsidian.export_to_vault(export, vault / "MIND")
    conf = vault / ".obsidian"
    (conf / "snippets").mkdir(parents=True)
    shutil.copy(HERE.parent / "assets" / "obsidian" / "letravora.css", conf / "snippets" / "letravora.css")
    (conf / "appearance.json").write_text(json.dumps({"theme": "obsidian", "enabledCssSnippets": ["letravora"],
                                                      "baseFontSize": 17}), encoding="utf-8")
    (conf / "app.json").write_text(json.dumps({"showInlineTitle": False}), encoding="utf-8")
    print(f"demo world in {OUT}")


if __name__ == "__main__":
    main()
