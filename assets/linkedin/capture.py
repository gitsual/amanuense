#!/usr/bin/env python3
"""Capture the demo workshop pages at 2x and the bounding boxes of key elements.

Reads the made-up demo world built by `python demo/build.py <lang>`. Writes
shots/<lang>/<name>.png and shots/<lang>/boxes.json (boxes in image pixels).
Run with a Python that has Playwright:

    python3 assets/linkedin/capture.py en
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
LANG = sys.argv[1] if len(sys.argv) > 1 else "en"
OUT = HERE / "shots" / LANG
DSF = 2
if LANG == "en":
    S = HERE.parents[1] / "demo/out/en/workshop/output"
    T1, T2 = S / "tasks/01-update-route-planner-deployment", S / "tasks/02-new-traffic-layer"
    PAGES = {
        "informe": (S / "index.html", {"lista": "Update in Confluence:", "tareas": "Tasks (2/2", "sinfuente": "check"}),
        "c02": (T2 / "CHANGES.html", {"aviso": "Data without a source", "latencia": "latency of 200 ms"}),
        "c01": (T1 / "CHANGES.html", {"puerto": "8443", "timeout": "ROUTE_TIMEOUT"}),
        "pegar": (T1 / "FOR-CONFLUENCE.html", {"tabla": "8443"}),
        "registro": (S / "log.html", {"titulo": "Change log", "codigo": "feat: add ROUTE_TIMEOUT",
                                      "autor": "Luis Pardo", "peticion": "Ana Ruiz"}),
    }
else:
    S = HERE.parents[1] / "demo/out/es/workshop/salida"
    T1, T2 = S / "tareas/01-actualizar-despliegue-de-route-planner", S / "tareas/02-nueva-capa-de-trafico"
    PAGES = {
        "informe": (S / "index.html", {"lista": "Actualizar en Confluence:", "tareas": "Tareas (2/2", "sinfuente": "revisar"}),
        "c02": (T2 / "CAMBIOS.html", {"aviso": "Datos sin fuente", "latencia": "tencia de 200 ms"}),
        "c01": (T1 / "CAMBIOS.html", {"puerto": "8443", "timeout": "ROUTE_TIMEOUT"}),
        "pegar": (T1 / "PARA-CONFLUENCE.html", {"tabla": "8443"}),
        "registro": (S / "registro.html", {"titulo": "Registro de cambios", "codigo": "feat: add ROUTE_TIMEOUT",
                                           "autor": "Luis Pardo", "peticion": "Ana Ruiz"}),
    }
# Smallest visible element whose text contains the needle; for table cells, its row.
FIND = """needle => {
  let best = null;
  for (const el of document.body.querySelectorAll('*')) {
    if (!el.innerText || !el.innerText.replace(/\u00a0/g, ' ').includes(needle)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    if (!best || r.width * r.height < best.width * best.height) best = r;
  }
  if (!best) return null;
  return {x: best.x + scrollX, y: best.y + scrollY, w: best.width, h: best.height};
}"""

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    boxes = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=DSF)
        for name, (path, needles) in PAGES.items():
            pg.goto(path.as_uri())
            pg.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            found = {}
            for key, needle in needles.items():
                r = pg.evaluate(FIND, needle)
                if r is None:
                    raise SystemExit(f"{name}: '{needle}' not found")
                found[key] = [round(v * DSF) for v in (r["x"], r["y"], r["w"], r["h"])]
            boxes[name] = found
        b.close()
    (OUT / "boxes.json").write_text(json.dumps(boxes, indent=1))
    print(json.dumps(boxes))

if __name__ == "__main__":
    main()
