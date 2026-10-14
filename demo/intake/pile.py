#!/usr/bin/env python3
"""Build the intake demo: a messy pile of Quillmere Trams documents and an empty workshop.

The pile is what a team hands over when nobody knows what is in it: notes, Word documents and
HTML pages that change pages of the space, files that say exactly what their page says, drafts
that match no page, copies of copies, test results, logs, lockfiles, a PDF and a few images.
The pages it is compared with are the same made-up space as the main demo (demo/build.py),
served live by demo/fakes.py; the AI answers are scripted.

    python demo/intake/pile.py [en|es]    # writes demo/out/intake/<lang>/ (default en)
"""
from __future__ import annotations

import html
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
ROOT = DEMO.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DEMO))

import build  # noqa: E402
from amanuense import i18n, taller  # noqa: E402

OUT = DEMO / "out" / "intake"
WORKSHOP = "quillmere-docs"  # the app's header shows this name
AI_DELAY = 0.9  # seconds per scripted answer, so the progress can be read on screen


def _md(title: str, *paras: str) -> str:
    return f"# {title}\n\n" + "\n\n".join(paras) + "\n"


def _html(title: str, *paras: str) -> str:
    body = "".join(f"<p>{html.escape(p)}</p>" for p in paras)
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head>" \
           f"<body><h1>{html.escape(title)}</h1>{body}</body></html>\n"


def _docx(title: str, *paras: str) -> tuple:
    return ("docx", [(1, title), *((0, p) for p in paras)])


def _page_paras(lang: str, title: str) -> list[str]:
    """A page's paragraphs as Confluence holds them today (with the edit of the main demo)."""
    world = build.WORLD[lang]
    before, after = world["edit"]
    out, inside = [], False
    for level, text in world["space"]:
        if level:
            inside = text == title
        elif inside:
            out.append(text.replace(before, after))
    return out


# ── The pile, in each language ────────────────────────────────────────────────
# Every entry: relative path → text, or ("docx", blocks), or raw bytes.

TEXT = {
    "en": {
        "folder": "quillmere-handover",
        "updates": {
            "ops/Departures Board deployment.md": _md(
                "Departures Board deployment", "Repository: departures-board.",
                "Since release 2.4 the service listens on port 8443.",
                "New variable DEPARTURES_TIMEOUT: seconds the board waits for the timetable service before it "
                "shows cached departures (8 by default).", "Departures refresh every 30 seconds."),
            "alerts/Service Alerts overview.md": _md(
                "Service Alerts overview",
                "Capability that tells passengers about disruptions on the boards and in the app.",
                "From release 4.2 alerts reach the boards within 30 seconds."),
            "alerts/notes/Service Alerts overview notes.txt": _md(
                "Service Alerts overview notes",
                "Agreed with the operations room on 9 October: from release 4.2 the alert feed is polled every "
                "10 seconds, so the 30-second target holds."),
            "alerts/Service Alerts deployment.docx": _docx(
                "Service Alerts deployment", "Repository: service-alerts.",
                "Alerts are kept for 72 hours since the October release."),
            "fares/Fare Engine overview.html": _html(
                "Fare Engine overview",
                "Computes the fare of a journey from zones and passenger type, and applies the off-peak discount.",
                "Children under 12 travel free when they ride with an adult."),
            "contracts/StopId.md": _md(
                "StopId", "Identifier of a stop, shared with the journey planner.",
                "Format: QM- followed by four digits, for example QM-0412."),
        },
        "identical": {"ops/Fare Engine deployment.md": ("md", "Fare Engine deployment"),
                      "boards/Departures Board overview.docx": ("docx", "Departures Board overview"),
                      "contracts/DepartureList.txt": ("md", "DepartureList")},
        "copies": {"ops/old/backup/Departures Board deployment.md": "ops/Departures Board deployment.md",
                   "alerts/Service Alerts overview (2).md": "alerts/Service Alerts overview.md",
                   "fares/archive/Fare Engine overview.html": "fares/Fare Engine overview.html",
                   "handbook/Copy of Glossary.md": "handbook/Glossary.md",
                   "runbooks/old/Night Service runbook.md": "runbooks/Night Service runbook.md"},
        "drafts": [
            ("runbooks/Night Service runbook.md", "Night Service runbook", [
                "## Hours", "Night trams run from 00:30 to 05:00, one every 20 minutes on lines 1 and 4.",
                "## Before the first tram", "The control room switches the boards to the night timetable and "
                "checks that every stop shows the night lines. If a board still shows the day lines after 00:40, "
                "restart its player from the depot console.", "## Escalation",
                "Call the duty engineer of the passenger information team. Log every restart in the night book."]),
            ("handbook/Glossary.md", "Glossary", [
                "Board: the screen at a stop that lists the next trams.", "Headway: minutes between two trams "
                "of the same line.", "Turnback: a tram that ends its run before the terminus and returns.",
                "Duty: the work of one driver for one day, from sign-on to sign-off."]),
            ("standards/Tram stop naming rules.md", "Tram stop naming rules", [
                "## Names", "A stop takes the name of the street or the place a passenger would ask for, never "
                "the name of a company. Two stops never share a name, even on different lines.", "## Length",
                "Names fit in 22 characters so every board can show them on one line. Longer names get an "
                "approved short form, listed in the stop register.", "## Changes",
                "A renamed stop keeps its identifier, and its old name stays as an alias for a year."]),
            ("planning/Winter timetable 2026.docx", "Winter timetable 2026", [
                "From 14 December lines 1 and 2 run every 6 minutes at peak and every 10 minutes off peak.",
                "Line 4 runs every 12 minutes all day. The first trams leave the depot at 05:10.",
                "On 24 and 31 December the last trams leave the city centre at 21:30."]),
            ("reviews/Incident review - board outage of 3 August.html", "Incident review: board outage of 3 August", [
                "From 07:12 to 07:58 the boards of 31 stops showed no departures.",
                "Cause: a certificate expired on the timetable gateway and the boards could not read it.",
                "Actions: renew certificates 30 days before they expire, and show cached departures when the "
                "gateway does not answer."]),
            ("research/Real-time feed vendors compared.md", "Real-time feed vendors compared", [
                "## Scope", "We compared three vendors of real-time vehicle positions for the boards and the app.",
                "## Findings", "All three publish GTFS Realtime. Only two keep positions for replay, and only one "
                "offers a test feed we can run on a laptop.", "## Recommendation",
                "Run a three-month trial with the vendor that offers the test feed, on lines 1 and 4."]),
            ("standards/Accessibility review of the stop displays.docx", "Accessibility review of the stop displays", [
                "Contrast meets the guidance on 41 of 48 displays; the seven oldest need new panels.",
                "Every display reads out the next tram when the help button is pressed, except at the depot stop.",
                "Text size is fine at three metres, too small at six."]),
            ("ops/Depot Wi-Fi for the players.md", "Depot Wi-Fi for the players", [
                "The players behind every screen download the night timetable over the depot Wi-Fi.",
                "Use the network named after the depot, never the guest one. Passwords rotate every quarter "
                "and are kept by the depot manager."]),
            ("planning/Timetable import format.txt", "Timetable import format", [
                "Timetables arrive as GTFS zip files from the planning office every Friday.",
                "The import refuses a file whose calendar does not cover the next 30 days, and keeps the last "
                "good one."]),
            ("ops/On-call rota.md", "On-call rota", [
                "One engineer of the passenger information team is on call each week, Monday to Monday.",
                "Swaps are agreed in the team chat and written here."]),
            ("ops/Ticket machine error codes.html", "Ticket machine error codes", [
                "E12: the card reader did not answer. E31: no paper. E44: the fare table is out of date."]),
            ("research/Passenger survey draft.md", "Draft: passenger survey", [
                "Questions about the boards: are the minutes right, can you read them from the shelter?"]),
            ("ops/Screen brightness at night.txt", "Screen brightness at night", [
                "Boards dim to 40 percent from 23:00 to 06:00, except at stops without street lights."]),
            ("onboarding/Onboarding for new team members.md", "Onboarding for new team members", [
                "Week one: read the glossary, shadow the control room for a morning, ride line 4 end to end."]),
            ("meetings/Meeting notes 2026-09-14.md", "Meeting notes 2026-09-14", [
                "Present: the passenger information team. Agreed to review the night boards in October."]),
            ("meetings/Meeting notes 2026-09-21.md", "Meeting notes 2026-09-21", [
                "Short meeting. Nothing decided."]),
            ("meetings/Meeting notes 2026-09-28.md", "Meeting notes 2026-09-28", [
                "Talked about the winter timetable. Waiting for planning."]),
            ("README.md", "README", ["Things we had on the shared drive."]),
            ("notes.txt", None, ["ask about the depot stop", "check brightness on line 4"]),
            ("misc/todo.md", "TODO", ["- tidy this folder"]),
        ],
        "results": {
            "Departures Board deployment": build.WORLD["en"]["results"]["Departures Board deployment"],
            "Service Alerts deployment": build.WORLD["en"]["results"]["Service Alerts deployment"],
            "Service Alerts overview": _md(
                "Service Alerts overview",
                "Capability that tells passengers about disruptions on the boards and in the app.",
                "Alerts reach the boards within 30 seconds.", "The alert feed is polled every 10 seconds.",
                "## Change log\n\n- Delivery target from 2 minutes to 30 seconds, from release 4.2.\n"
                "- The feed is polled every 10 seconds instead of 60."),
            "Fare Engine overview": _md(
                "Fare Engine overview",
                "Computes the fare of a journey from zones and passenger type, and applies the off-peak discount.",
                "Children under 12 travel free when they ride with an adult.",
                "## Change log\n\n- Children under 12 travel free with an adult."),
            "StopId": _md(
                "StopId", "Identifier of a stop, shared with the journey planner.",
                "Format: `QM-` followed by four digits, for example `QM-0412`.",
                "## Change log\n\n- Documents the format of the identifier."),
        },
    },
    "es": {
        "folder": "traspaso-quillmere",
        "updates": {
            "ops/Despliegue del panel de salidas.md": _md(
                "Despliegue del panel de salidas", "Repositorio: departures-board.",
                "Desde la versión 2.4 el servicio escucha en el puerto 8443.",
                "Nueva variable DEPARTURES_TIMEOUT: segundos que espera el panel al servicio de horarios antes de "
                "mostrar las salidas en caché (por defecto 8).", "Las salidas se refrescan cada 30 segundos."),
            "avisos/Visión general de los avisos.md": _md(
                "Visión general de los avisos",
                "Capacidad que informa a los viajeros de las incidencias en los paneles y en la app.",
                "Desde la versión 4.2 los avisos llegan a los paneles en menos de 30 segundos."),
            "avisos/notas/Visión general de los avisos notas.txt": _md(
                "Visión general de los avisos notas",
                "Acordado con la sala de operaciones el 9 de octubre: desde la versión 4.2 el canal de avisos se "
                "consulta cada 10 segundos, así que el objetivo de 30 segundos se cumple."),
            "avisos/Despliegue de los avisos.docx": _docx(
                "Despliegue de los avisos", "Repositorio: service-alerts.",
                "Desde la versión de octubre los avisos se guardan 72 horas."),
            "tarifas/Visión general del motor de tarifas.html": _html(
                "Visión general del motor de tarifas",
                "Calcula la tarifa de un viaje según las zonas y el tipo de viajero, y aplica el descuento de horas valle.",
                "Los menores de 12 años viajan gratis si van con un adulto."),
            "contratos/StopId.md": _md(
                "StopId", "Identificador de una parada, compartido con el planificador de viajes.",
                "Formato: QM- seguido de cuatro cifras, por ejemplo QM-0412."),
        },
        "identical": {"ops/Despliegue del motor de tarifas.md": ("md", "Despliegue del motor de tarifas"),
                      "paneles/Visión general del panel de salidas.docx": ("docx", "Visión general del panel de salidas"),
                      "contratos/DepartureList.txt": ("md", "DepartureList")},
        "copies": {"ops/viejo/backup/Despliegue del panel de salidas.md": "ops/Despliegue del panel de salidas.md",
                   "avisos/Visión general de los avisos (2).md": "avisos/Visión general de los avisos.md",
                   "tarifas/archivo/Visión general del motor de tarifas.html":
                       "tarifas/Visión general del motor de tarifas.html",
                   "manual/Copia de Glosario.md": "manual/Glosario.md",
                   "procedimientos/viejo/Procedimiento del servicio nocturno.md":
                       "procedimientos/Procedimiento del servicio nocturno.md"},
        "drafts": [
            ("procedimientos/Procedimiento del servicio nocturno.md", "Procedimiento del servicio nocturno", [
                "## Horario", "Los tranvías nocturnos circulan de 00:30 a 05:00, uno cada 20 minutos en las líneas 1 y 4.",
                "## Antes del primer tranvía", "La sala de control pasa los paneles al horario nocturno y comprueba "
                "que todas las paradas muestran las líneas nocturnas. Si a las 00:40 un panel sigue con las líneas "
                "de día, se reinicia su reproductor desde la consola de cocheras.", "## Escalado",
                "Llama al ingeniero de guardia del equipo de información al viajero. Anota cada reinicio en el "
                "libro de noche."]),
            ("manual/Glosario.md", "Glosario", [
                "Panel: la pantalla de una parada que lista los próximos tranvías.", "Frecuencia: minutos entre dos "
                "tranvías de la misma línea.", "Vuelta corta: un tranvía que acaba antes de la cabecera y regresa.",
                "Turno: el trabajo de un conductor en un día, de la toma al deje."]),
            ("normas/Normas para nombrar paradas.md", "Normas para nombrar paradas", [
                "## Nombres", "Una parada lleva el nombre de la calle o del lugar por el que preguntaría un viajero, "
                "nunca el de una empresa. Dos paradas nunca comparten nombre, aunque estén en líneas distintas.",
                "## Longitud", "Los nombres caben en 22 caracteres para que todos los paneles los muestren en una "
                "línea. Los más largos tienen una forma corta aprobada, en el registro de paradas.", "## Cambios",
                "Una parada renombrada conserva su identificador, y su nombre antiguo sigue como alias un año."]),
            ("planificacion/Horario de invierno 2026.docx", "Horario de invierno 2026", [
                "Desde el 14 de diciembre las líneas 1 y 2 pasan cada 6 minutos en hora punta y cada 10 en hora valle.",
                "La línea 4 pasa cada 12 minutos todo el día. Los primeros tranvías salen de cocheras a las 05:10.",
                "El 24 y el 31 de diciembre los últimos tranvías salen del centro a las 21:30."]),
            ("revisiones/Revisión de incidente - caída de paneles del 3 de agosto.html",
             "Revisión de incidente: caída de paneles del 3 de agosto", [
                "De 07:12 a 07:58 los paneles de 31 paradas no mostraron salidas.",
                "Causa: caducó un certificado de la pasarela de horarios y los paneles no pudieron leerla.",
                "Acciones: renovar los certificados 30 días antes de que caduquen y mostrar las salidas en caché "
                "cuando la pasarela no responde."]),
            ("estudios/Comparativa de proveedores de tiempo real.md", "Comparativa de proveedores de tiempo real", [
                "## Alcance", "Comparamos tres proveedores de posiciones en tiempo real para los paneles y la app.",
                "## Hallazgos", "Los tres publican GTFS Realtime. Sólo dos guardan las posiciones para repetirlas, "
                "y sólo uno ofrece un canal de pruebas que se puede ejecutar en un portátil.", "## Recomendación",
                "Hacer una prueba de tres meses con el proveedor del canal de pruebas, en las líneas 1 y 4."]),
            ("normas/Revisión de accesibilidad de las pantallas.docx", "Revisión de accesibilidad de las pantallas", [
                "El contraste cumple la guía en 41 de 48 pantallas; las siete más antiguas necesitan paneles nuevos.",
                "Todas las pantallas leen en voz alta el próximo tranvía al pulsar el botón de ayuda, salvo la de "
                "la parada de cocheras.", "El texto se lee bien a tres metros y es pequeño a seis."]),
            ("ops/Wi-Fi de cocheras para los reproductores.md", "Wi-Fi de cocheras para los reproductores", [
                "Los reproductores de cada pantalla descargan el horario nocturno por la Wi-Fi de cocheras.",
                "Usa la red con el nombre de la cochera, nunca la de invitados. Las contraseñas cambian cada "
                "trimestre y las guarda el jefe de cocheras."]),
            ("planificacion/Formato de importación de horarios.txt", "Formato de importación de horarios", [
                "Los horarios llegan cada viernes de la oficina de planificación como ficheros zip GTFS.",
                "La importación rechaza un fichero cuyo calendario no cubre los próximos 30 días y conserva el "
                "último bueno."]),
            ("ops/Guardias.md", "Guardias", [
                "Cada semana hay un ingeniero de guardia del equipo de información al viajero, de lunes a lunes.",
                "Los cambios se acuerdan en el chat del equipo y se anotan aquí."]),
            ("ops/Códigos de error de las máquinas de billetes.html", "Códigos de error de las máquinas de billetes", [
                "E12: el lector de tarjetas no respondió. E31: sin papel. E44: la tabla de tarifas está desfasada."]),
            ("estudios/Encuesta a viajeros borrador.md", "Borrador: encuesta a viajeros", [
                "Preguntas sobre los paneles: ¿son correctos los minutos?, ¿se leen desde la marquesina?"]),
            ("ops/Brillo de las pantallas de noche.txt", "Brillo de las pantallas de noche", [
                "Los paneles bajan al 40 por ciento de 23:00 a 06:00, salvo en paradas sin alumbrado."]),
            ("acogida/Acogida de personas nuevas.md", "Acogida de personas nuevas", [
                "Semana uno: leer el glosario, acompañar a la sala de control una mañana, recorrer la línea 4 entera."]),
            ("reuniones/Notas de reunión 2026-09-14.md", "Notas de reunión 2026-09-14", [
                "Presentes: el equipo de información al viajero. Se acuerda revisar los paneles nocturnos en octubre."]),
            ("reuniones/Notas de reunión 2026-09-21.md", "Notas de reunión 2026-09-21", [
                "Reunión corta. No se decide nada."]),
            ("reuniones/Notas de reunión 2026-09-28.md", "Notas de reunión 2026-09-28", [
                "Hablamos del horario de invierno. Esperamos a planificación."]),
            ("README.md", "README", ["Cosas que teníamos en la unidad compartida."]),
            ("notas.txt", None, ["preguntar por la parada de cocheras", "mirar el brillo en la línea 4"]),
            ("varios/pendiente.md", "Pendiente", ["- ordenar esta carpeta"]),
        ],
        "results": {
            "Despliegue del panel de salidas": build.WORLD["es"]["results"]["Despliegue del panel de salidas"],
            "Despliegue de los avisos": build.WORLD["es"]["results"]["Despliegue de los avisos"],
            "Visión general de los avisos": _md(
                "Visión general de los avisos",
                "Capacidad que informa a los viajeros de las incidencias en los paneles y en la app.",
                "Los avisos llegan a los paneles en menos de 30 segundos.",
                "El canal de avisos se consulta cada 10 segundos.",
                "## Registro de cambios\n\n- Objetivo de entrega de 2 minutos a 30 segundos, desde la versión 4.2.\n"
                "- El canal se consulta cada 10 segundos en vez de cada 60."),
            "Visión general del motor de tarifas": _md(
                "Visión general del motor de tarifas",
                "Calcula la tarifa de un viaje según las zonas y el tipo de viajero, y aplica el descuento de horas valle.",
                "Los menores de 12 años viajan gratis si van con un adulto.",
                "## Registro de cambios\n\n- Los menores de 12 años viajan gratis con un adulto."),
            "StopId": _md(
                "StopId", "Identificador de una parada, compartido con el planificador de viajes.",
                "Formato: `QM-` seguido de cuatro cifras, por ejemplo `QM-0412`.",
                "## Registro de cambios\n\n- Documenta el formato del identificador."),
        },
    },
}

# What a pile also carries, the same in every language: noise, PDFs, other formats, an empty file.
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
JUNIT = ('<?xml version="1.0"?>\n<testsuite name="{}" tests="42" failures="0">'
         '<testcase name="renders the next three trams"/></testsuite>\n')
LOG = "2026-10-{:02d}T07:30:00Z INFO run {} finished: 42 passed\n"
EXTRA = {
    "test-results/junit-departures.xml": JUNIT.format("departures"),
    "test-results/junit-alerts.xml": JUNIT.format("alerts"),
    "test-results/report.html": "<html><body><h1>Test report</h1><p>42 passed</p></body></html>\n",
    **{f"test-results/run-2026-10-{d:02d}.log": LOG.format(d, d) for d in range(1, 7)},
    **{f"logs/sync-2026-10-{d:02d}.log": LOG.format(d, d) for d in range(10, 14)},
    "package-lock.json": '{\n "name": "board-sim",\n "lockfileVersion": 3\n}\n',
    "tools/board-sim/yarn.lock": "# yarn lockfile v1\n",
    "build/site/index.html": "<html><body><h1>Generated site</h1></body></html>\n",
    "node_modules/marked/README.md": "# marked\n\nA markdown parser.\n",
    "Tram fleet brochure.pdf": PDF,
    "contracts/Signed SLA 2026.pdf": PDF,
    "diagrams/network-map.png": PNG,
    "budget-2026.xlsx": b"PK\x03\x04 not a document we read\n",
    "slides/kickoff.pptx": b"PK\x03\x04 not a document we read either\n",
    "untitled.md": b"",
}


def pile_files(lang: str) -> dict[str, object]:
    """Every file of the pile: relative path → text, raw bytes or ("docx", blocks)."""
    text = TEXT[lang]
    files: dict[str, object] = dict(text["updates"])
    for rel, (kind, title) in text["identical"].items():
        paras = _page_paras(lang, title)
        files[rel] = _docx(title, *paras) if kind == "docx" else _md(title, *paras)
    for rel, title, paras in text["drafts"]:
        files[rel] = "\n".join(paras) + "\n" if title is None else (
            _docx(title, *paras) if rel.endswith(".docx") else
            _html(title, *paras) if rel.endswith(".html") else _md(title, *paras))
    for copy, original in text["copies"].items():
        files[copy] = files[original]
    files.update(EXTRA)
    return files


def write_pile(folder: Path, lang: str) -> int:
    files = pile_files(lang)
    for rel, content in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, tuple):
            build.docx(path, content[1], "2026-09-30T10:00:00Z")
        elif isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return len(files)


def stage_world(lang: str) -> dict:
    """The main demo's space, with the scripted answers for the pages this pile updates."""
    return {**build.stage_world(lang), "results": TEXT[lang]["results"], "ai_delay": AI_DELAY}


def main(lang: str = "en") -> Path:
    i18n.use(lang)
    out = OUT / lang
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    n = write_pile(out / "pile" / TEXT[lang]["folder"], lang)
    taller.init_workspace(out / WORKSHOP, lang)
    print(f"intake demo: a pile of {n} files and an empty workshop in {out}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "en")
