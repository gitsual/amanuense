#!/usr/bin/env python3
"""Record the intake demo: a messy folder dropped into the review app and compared with Confluence.

Reuses the main demo's take, cards and palette (demo/record.py). The review app runs over an
empty workshop and talks to demo/fakes.py only: the space is read live from the fake Confluence,
the AI answers are scripted. The folder goes in through the app's own folder input; the pointer
and the dragged folder are drawn on the page so the viewer sees the drop. Writes
demo/out/intake/<lang>/take.webm and marks.json; the English take also refreshes
assets/review/intake-*.png.

    python demo/intake/pile.py en && python demo/intake/take.py en
"""
from __future__ import annotations

import html
import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import record as stage  # noqa: E402  (the main demo's helpers; it reads the language from argv too)
import pile  # noqa: E402
import fakes  # noqa: E402
from amanuense import app, i18n, settings  # noqa: E402

LANG = stage.LANG
OUT = pile.OUT / LANG
WS = OUT / pile.WORKSHOP
FOLDER = OUT / "pile" / pile.TEXT[LANG]["folder"]
REPO = "github.com/gitsual/amanuense"

COPY = {
    "en": {
        "intro": "New · add a pile of documentation",
        "question": "Which of these change a page in Confluence?",
        "files": "{n} files · {d} folders",
        "open": "Departures Board deployment",
        "close": "Drop your docs. Get proposals against the Confluence you have today.",
    },
    "es": {
        "intro": "Novedad · añade un montón de documentación",
        "question": "¿Cuáles de estos cambian una página de Confluence?",
        "files": "{n} ficheros · {d} carpetas",
        "open": "Despliegue del panel de salidas",
        "close": "Suelta tus documentos. Recibe propuestas contra el Confluence que tienes hoy.",
    },
}[LANG]

ICON = {"md": "#9fd39a", "txt": "#9fd39a", "docx": "#8fb4e3", "html": "#e3b58f", "pdf": "#e38f8f",
        "log": "#7d8794", "xml": "#7d8794", "json": "#7d8794", "lock": "#7d8794"}


def folder_card(question: bool) -> str:
    """The pile as a file manager would list it: just names, no idea what is in them."""
    p = stage.PALETTE
    files = sorted(f.relative_to(FOLDER).as_posix() for f in FOLDER.rglob("*") if f.is_file())
    folders = {str(Path(f).parent) for f in files if "/" in f}
    rows = []
    for f in files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in Path(f).name else ""
        dot = ICON.get(ext, "#b9b9b9")
        rows.append(f"<div style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                    f"<span style='display:inline-block;width:8px;height:8px;border-radius:2px;background:{dot};"
                    f"margin-right:8px'></span>{html.escape(f)}</div>")
    ask = (f"<p style='font-size:34px;margin:22px 0 0;color:{p['fg']}'>{html.escape(COPY['question'])}</p>"
           if question else "<p style='font-size:34px;margin:22px 0 0'>&nbsp;</p>")
    return stage._base(
        f"<div style='padding:34px 56px'>"
        f"<div style='font:600 15px system-ui;letter-spacing:.08em;text-transform:uppercase;color:{p['accent']}'>"
        f"{html.escape(FOLDER.name)} · {html.escape(COPY['files'].format(n=len(files), d=len(folders)))}</div>"
        f"<div class='mono' style='margin-top:16px;background:{p['term']};border-radius:12px;padding:18px 22px;"
        f"columns:3;column-gap:28px;font-size:12.5px;line-height:1.62;color:{p['dim']};box-shadow:0 10px 30px #0005'>"
        f"{''.join(rows)}</div>{ask}</div>")


# ── The pointer and the dragged folder, drawn over the app ───────────────────
POINTER = """
(() => {
  if (document.getElementById('demo-pointer')) return;
  const p = document.createElement('div');
  p.id = 'demo-pointer';
  p.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18 L12 28 L16 26 L12 16 L21 16 Z" '
    + 'fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  p.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transition:none';
  const g = document.createElement('div');
  g.id = 'demo-ghost';
  g.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483646;pointer-events:none;display:none;'
    + 'background:#2c3e57;color:#e9e9e7;border:1px solid #aaa875;border-radius:10px;padding:10px 14px;'
    + 'font:600 14px system-ui;box-shadow:0 12px 30px #0007;opacity:.95';
  document.body.append(g, p);
})()
"""


def pointer(page, x: float, y: float, ghost: str | None = None) -> None:
    page.evaluate("""([x, y, ghost]) => {
      const p = document.getElementById('demo-pointer'), g = document.getElementById('demo-ghost');
      p.style.transform = `translate(${x}px, ${y}px)`;
      if (ghost === null) { g.style.display = 'none'; return; }
      g.textContent = ghost; g.style.display = 'block';
      g.style.transform = `translate(${x + 18}px, ${y + 22}px)`;
    }""", [x, y, ghost])


def glide(take, page, start, end, seconds: float, ghost: str | None = None) -> None:
    steps = max(1, int(seconds * stage.FPS))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # ease in and out
        pointer(page, start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t, ghost)
        take.hold(page, 1 / stage.FPS)


def drag_files(page, kind: str) -> None:
    """The browser's own drag signals, so the app shows its «drop to add them» layer."""
    page.evaluate("""(kind) => {
      const dt = new DataTransfer();
      dt.items.add(new File([''], 'pile'));
      document.dispatchEvent(new DragEvent(kind, { dataTransfer: dt, bubbles: true }));
    }""", kind)


def centre(page, selector: str) -> tuple[float, float]:
    box = page.locator(selector).first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


# ── Scenes ────────────────────────────────────────────────────────────────────

def opening(take, browser) -> None:
    page = browser.new_page(viewport=stage.SIZE)
    take.scene("intro", "start")
    page.set_content(stage.card(COPY["intro"]))
    take.hold(page, 3)
    take.end(page, "intro")

    take.scene("problem", "start")
    page.set_content(folder_card(False))
    take.hold(page, 3)
    page.set_content(folder_card(True))
    take.hold(page, 2)
    take.end(page, "problem")
    page.close()


def review(take, browser) -> None:
    config = OUT / "config"
    shutil.rmtree(config, ignore_errors=True)
    for key in [k for k in os.environ if k.startswith("AMANUENSE_")]:
        del os.environ[key]
    os.environ.update(AMANUENSE_CONFIG_DIR=str(config), AMANUENSE_USER=stage.build.USER)
    world = fakes.start(pile.stage_world(LANG))
    settings.save({"url": world.base, "space": fakes.SPACE, "token": fakes.TOKEN,
                   "ai_url": f"{world.base}/v1", "ai_model": fakes.MODEL})
    server = app.serve(WS, lang=LANG)
    label = lambda key: i18n.TEXT[key][LANG]  # noqa: E731
    page = browser.new_page(viewport=stage.SIZE)
    n_files = sum(1 for f in FOLDER.rglob("*") if f.is_file())
    try:
        page.goto(server.url)
        page.wait_for_selector("section.drop")
        page.evaluate(POINTER)
        pointer(page, 1180, 660)

        take.scene("drop", "start")
        take.hold(page, 1.5)
        target = centre(page, "section.drop")
        ghost = f"▸ {FOLDER.name} · {n_files}"
        glide(take, page, (1180, 660), (1060, 560), 0.6, ghost)
        drag_files(page, "dragenter")
        glide(take, page, (1060, 560), target, 1.6, ghost)
        take.hold(page, 0.6)
        drag_files(page, "dragleave")  # the drop itself goes through the folder input, with its folders
        page.locator("input[webkitdirectory]").set_input_files(str(FOLDER))
        pointer(page, *target)
        page.wait_for_selector(".tiles")
        glide(take, page, target, (1180, 690), 0.8)
        take.end(page, "drop")

        take.scene("plan", "start")
        take.hold(page, 3)
        skipped = page.locator("button.tab", has_text=label("ui_in_tab_skipped").split("(")[0].strip()).first
        glide(take, page, (1180, 690), centre(page, "button.tab >> nth=1"), 0.8)
        skipped.click()
        take.hold(page, 1)
        stage.shot(page, "intake-plan")
        take.hold(page, 2.5)
        take.end(page, "plan")

        take.scene("compare", "start")
        button = page.get_by_role("button", name=label("ui_in_compare"))
        button.scroll_into_view_if_needed()
        take.hold(page, 0.5)
        glide(take, page, centre(page, "button.tab >> nth=1"), centre(page, "footer.intake-actions button.primary"), 0.8)
        button.click()
        pointer(page, 1180, 690)
        for _ in range(600):
            if page.locator(".card.done").count():
                break
            take.hold(page, 0.1)
        take.end(page, "compare")

        take.scene("results", "start")
        take.hold(page, 3)
        stage.shot(page, "intake-results")
        page.evaluate("document.querySelector('.candidates')?.scrollIntoView({behavior: 'smooth', block: 'start'})")
        take.hold(page, 3)
        take.end(page, "results")

        take.scene("proposal", "start")
        page.evaluate("window.scrollTo({top: 0})")
        page.get_by_role("button", name=label("ui_in_go_review")).click()
        page.wait_for_selector(".page-row")
        take.hold(page, 1.2)
        row = page.locator(".page-row", has_text=COPY["open"]).first
        glide(take, page, (1180, 690), centre(page, f".page-row:has-text('{COPY['open']}')"), 0.8)
        row.click()
        pointer(page, 1180, 690)
        take.hold(page, 3)
        take.end(page, "proposal")

        take.scene("publish", "start")
        page.get_by_role("button", name=label("ui_approve"), exact=True).click()
        take.hold(page, 1.2)
        page.get_by_role("button", name=label("ui_publish"), exact=True).click()
        page.get_by_role("button", name=label("ui_publish_now")).wait_for()
        take.hold(page, 1.5)
        page.get_by_role("button", name=label("ui_publish_now")).click()
        page.wait_for_selector(".published")
        take.hold(page, 2)
        take.end(page, "publish")
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        world.shutdown()
        world.server_close()
        shutil.rmtree(config, ignore_errors=True)


def main() -> None:
    take = stage.Take(OUT)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        opening(take, browser)
        review(take, browser)
        page = browser.new_page(viewport=stage.SIZE)
        take.scene("close", "start")
        page.set_content(stage.card(COPY["close"], REPO))
        take.hold(page, 4)
        take.end(page, "close")
        browser.close()
    take.save()
    print(f"{take.n} frames, {take.n / stage.FPS:.1f} s → {OUT / 'take.webm'}")


if __name__ == "__main__":
    main()
