#!/usr/bin/env python3
"""Record the demo take: the workshop pages in Chromium and the vault in Obsidian.

Needs Playwright (with Chromium) and Obsidian. Obsidian runs headless on its own
profile, so the recording never touches your desktop or your vaults. Writes
demo/out/<lang>/take.webm and marks.json, ready for `tramoya assemble`. If the
voices are already in demo/out/<lang>/voices, each scene lasts as long as its narration.

    python demo/build.py en && python demo/record.py en
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from amanuense import i18n  # noqa: E402

import fake_mind  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "en"
i18n.use(LANG)
OUT = HERE / "out" / LANG
WORKSHOP_OUT = OUT / "workshop" / i18n.name("out")
FRAMES = OUT / "frames"
VOICES = OUT / "voices"
CARDS = {
    "en": ("From MIND to Obsidian, without losing who changed what",
           "All on your machine · you approve every change"),
    "es": ("De MIND a Obsidian, sin perder quién cambió qué",
           "Todo en tu máquina · tú apruebas cada cambio"),
}[LANG]
DECISION = {
    "en": "Refresh every 5 minutes. The weather-layer README changes in the same release.",
    "es": "Refrescar cada 5 minutos. El README de weather-layer cambia en la misma versión.",
}[LANG]
VAULT_PAGES = {
    "en": ("Route Planner contracts", "Route Planner deployment"),
    "es": ("Contratos de Route Planner", "Despliegue de Route Planner"),
}[LANG]
FPS = 10
SIZE = {"width": 1280, "height": 720}
OBSIDIAN = ["electron43", "/usr/lib/obsidian/app.asar"]
CDP_PORT = 9333
REVEAL = ("app.workspace.getLeavesOfType('file-explorer')[0].view.revealInFolder("
          "app.workspace.getActiveFile())")


class Take:
    """Screenshots at a fixed rate; scene marks are frame counts over FPS."""

    def __init__(self):
        shutil.rmtree(FRAMES, ignore_errors=True)
        FRAMES.mkdir(parents=True)
        self.n, self.marks = 0, []

    def hold(self, page, seconds: float) -> None:
        for _ in range(int(seconds * FPS)):
            t0 = time.monotonic()
            page.screenshot(path=str(FRAMES / f"{self.n:05d}.png"))
            self.n += 1
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - t0)))

    def scene(self, name: str, edge: str) -> None:
        self.marks.append({"t": round(self.n / FPS, 3), "key": f"scene:{name}:{edge}", "label": name})

    def end(self, page, name: str) -> None:
        """Holds the last frame until the scene is as long as its narration, if there is one."""
        voice = VOICES / f"scene-{name}.wav"
        if voice.exists():
            start = next(m["t"] for m in self.marks if m["key"] == f"scene:{name}:start")
            spoken = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                           str(voice)], capture_output=True, text=True, check=True).stdout)
            self.hold(page, spoken + 0.8 - (self.n / FPS - start))
        self.scene(name, "end")

    def scroll(self, page, dy: int, seconds: float = 1.6) -> None:
        page.evaluate(f"window.scrollBy({{top: {dy}, behavior: 'smooth'}})")
        self.hold(page, seconds)

    def save(self) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FRAMES / "%05d.png"),
                        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p", str(OUT / "take.webm")],
                       check=True)
        (OUT / "marks.json").write_text(json.dumps(self.marks, indent=1), encoding="utf-8")
        shutil.rmtree(FRAMES)


def card(logo: Path, line: str) -> str:
    return (f"<body style='margin:0;height:100vh;display:grid;place-items:center;background:#253850;"
            f"font-family:Georgia,serif;color:#B9B9B9'><div style='text-align:center'>"
            f"<img src='data:image/png;base64,{base64.b64encode(logo.read_bytes()).decode()}' style='width:620px'><p style='font-size:26px;margin-top:28px'>{line}</p>"
            f"</div></body>")


def open_page(page, path: Path, zoom: float = 1.45) -> None:
    page.goto(path.as_uri())
    page.evaluate(f"document.body.style.zoom = {zoom}")


def workshop(take: Take, browser) -> None:
    page = browser.new_page(viewport=SIZE)
    logo = HERE.parent / "assets" / "logo-dark.png"

    take.scene("intro", "start")
    page.set_content(card(logo, CARDS[0]))
    take.hold(page, 4)
    take.end(page, "intro")

    take.scene("informe", "start")
    open_page(page, WORKSHOP_OUT / "index.html")
    take.hold(page, 3)
    take.scroll(page, 380)
    take.scroll(page, 380)
    take.hold(page, 1)
    take.end(page, "informe")

    n = i18n.name
    task = next((WORKSHOP_OUT / n("tasks")).glob(f"01-{n('verb_update')}-*"))
    take.scene("cambios", "start")
    open_page(page, task / n("changes"), 1.3)
    take.hold(page, 3)
    take.scroll(page, 360)
    take.hold(page, 1)
    take.end(page, "cambios")

    page.close()


def review(take: Take, browser) -> None:
    """The review app over the made-up workshop, publishing to a made-up MIND."""
    from amanuense import app, settings

    config = OUT / "config"
    shutil.rmtree(config, ignore_errors=True)
    os.environ.update(AMANUENSE_CONFIG_DIR=str(config), AMANUENSE_USER=fake_mind.EDITOR)
    snapshot = json.loads((WORKSHOP_OUT / i18n.name("snapshot")).read_text(encoding="utf-8"))
    mind = fake_mind.start(list(snapshot["pages"]))
    settings.save({"url": mind.base, "space": fake_mind.SPACE, "token": fake_mind.TOKEN})
    server = app.serve(OUT / "workshop", lang=LANG)
    label = lambda key: i18n.TEXT[key][LANG]  # noqa: E731
    page = browser.new_page(viewport=SIZE)
    try:
        page.goto(server.url)
        page.wait_for_selector(".page-row")

        take.scene("revisar", "start")
        take.hold(page, 2.5)
        page.locator(".page-row").first.click()
        take.hold(page, 2.5)
        if LANG == "en":
            page.screenshot(path=str(HERE.parent / "assets" / "review" / "inbox.png"))
        take.end(page, "revisar")

        take.scene("decidir", "start")
        page.get_by_role("button", name=label("ui_decide"), exact=True).click()
        take.hold(page, 1)
        area = page.locator("form.decide textarea")
        for word in DECISION.split(" "):
            area.press_sequentially(word + " ")
            take.hold(page, 0.1)
        take.hold(page, 1)
        page.get_by_role("button", name=label("ui_save_decision")).click()
        take.hold(page, 2)
        page.get_by_role("button", name=label("ui_approve"), exact=True).click()
        take.hold(page, 2)
        take.end(page, "decidir")

        take.scene("publicar", "start")
        page.get_by_role("button", name=label("ui_publish"), exact=True).click()
        page.get_by_role("button", name=label("ui_publish_now")).wait_for()
        take.hold(page, 3.5)
        page.get_by_role("button", name=label("ui_publish_now")).click()
        page.wait_for_selector(".published")
        take.hold(page, 3)
        take.end(page, "publicar")
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        mind.shutdown()
        mind.server_close()
        shutil.rmtree(config, ignore_errors=True)


def log(take: Take, browser) -> None:
    page = browser.new_page(viewport=SIZE)
    take.scene("registro", "start")
    open_page(page, WORKSHOP_OUT / i18n.name("log_html"), 1.25)
    take.hold(page, 3)
    take.scroll(page, 360)
    take.scroll(page, 360)
    take.hold(page, 1)
    take.end(page, "registro")
    page.close()


def obsidian(take: Take, p, vault: Path) -> None:
    data = OUT / "obsidian-profile"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir()
    (data / "obsidian.json").write_text(json.dumps({"vaults": {"demo": {"path": str(vault), "ts": 1, "open": True}}}))
    proc = subprocess.Popen([*OBSIDIAN, f"--user-data-dir={data}", "--ozone-platform=headless",
                             f"--remote-debugging-port={CDP_PORT}", "--window-size=1280,720"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        page = [pg for c in browser.contexts for pg in c.pages][-1]
        page.set_viewport_size(SIZE)
        page.evaluate("app.workspace.openLinkText('MIND/_index', '', false)")
        time.sleep(2)
        take.scene("obsidian", "start")
        take.hold(page, 3)
        page.evaluate("app.workspace.openLinkText('MIND/Route Planner/_index', '', false)")
        take.hold(page, 3)
        page.evaluate(f"app.workspace.openLinkText('MIND/Route Planner/{VAULT_PAGES[0]}/_index', '', false)")
        take.hold(page, 3)
        page.evaluate(f"app.workspace.openLinkText('MIND/Route Planner/{VAULT_PAGES[1]}', '', false)")
        time.sleep(1)
        page.evaluate(REVEAL)
        time.sleep(0.5)
        take.hold(page, 4)
        take.end(page, "obsidian")
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(data, ignore_errors=True)


def main() -> None:
    take = Take()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        workshop(take, browser)
        review(take, browser)
        log(take, browser)
        obsidian(take, p, OUT / "vault")
        page = browser.new_page(viewport=SIZE)
        take.scene("cierre", "start")
        page.set_content(card(HERE.parent / "assets" / "logo-dark.png", CARDS[1]))
        take.hold(page, 4)
        take.end(page, "cierre")
        browser.close()
    take.save()
    print(f"{take.n} frames, {take.n / FPS:.1f} s → {OUT / 'take.webm'}")


if __name__ == "__main__":
    main()
