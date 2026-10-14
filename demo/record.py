#!/usr/bin/env python3
"""Record the demo take: the workshop pages and the review app in Chromium, the vault in Obsidian.

Needs Playwright (with Chromium) and Obsidian. Obsidian runs headless on its own profile, so
the recording never touches your desktop or your vaults. The review app publishes to
demo/fakes.py, never to a real Confluence. Writes demo/out/<lang>/take.webm and marks.json,
ready for `tramoya assemble`. If the voices are already in demo/out/<lang>/voices, each scene
lasts as long as its narration. The English take also refreshes the README screenshots.

    python demo/build.py en && python demo/record.py en
"""
from __future__ import annotations

import base64
import html
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import build  # noqa: E402
import fakes  # noqa: E402
from amanuense import i18n  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "en"
i18n.use(LANG)
n = i18n.name
OUT = HERE / "out" / LANG
TEAM = OUT / "team"
WS = TEAM / "docs-workshop"
WS_OUT = WS / n("out")
FRAMES = OUT / "frames"
VOICES = OUT / "voices"
SHOTS = ROOT / "assets" / "review" if LANG == "en" else None
WORLD = build.WORLD[LANG]
FPS = 10
SIZE = {"width": 1280, "height": 720}
OBSIDIAN = ["electron43", "/usr/lib/obsidian/app.asar"]
CDP_PORT = 9333
REVEAL = ("app.workspace.getLeavesOfType('file-explorer')[0].view.revealInFolder("
          "app.workspace.getActiveFile())")
SHOWN_HOME = "~/quillmere-docs"  # the team repo as the terminal shows it

COPY = {
    "en": {
        "intro": "Keeps a team's Confluence in step with its drafts and its code",
        "close": "All on your machine · you choose the AI · a person approves every change",
        "problem_title": "Documentation drifts",
        "wiki": "Confluence · Service Alerts deployment", "wiki_line": "Alerts are kept for 24 hours.",
        "code": "service-alerts · main", "code_line": "feat: keep alerts for 72 hours",
        "code_by": "Priya Nair · 12 Oct",
        "chat": "In the team chat", "chat_line": "“Alerts must reach the boards within 30 seconds, not 2 minutes.”",
        "chat_by": "Samir Haddad",
        "pages": ("Departures Board", "Departures Board contracts", "Departures Board deployment"),
        "titles": {"inbox": "Departures Board deployment", "why": "Service Alerts deployment",
                   "decide": "Service Alerts overview", "unsourced": "02-new-night-service"},
    },
    "es": {
        "intro": "Mantiene el Confluence de un equipo al día con sus borradores y su código",
        "close": "Todo en tu máquina · tú eliges la IA · una persona aprueba cada cambio",
        "problem_title": "La documentación se queda atrás",
        "wiki": "Confluence · Despliegue de los avisos", "wiki_line": "Los avisos se guardan 24 horas.",
        "code": "service-alerts · main", "code_line": "feat: keep alerts for 72 hours",
        "code_by": "Priya Nair · 12 oct",
        "chat": "En el chat del equipo", "chat_line": "«Los avisos tienen que llegar a los paneles en 30 segundos, no en 2 minutos.»",
        "chat_by": "Samir Haddad",
        "pages": ("Panel de salidas", "Contratos del panel de salidas", "Despliegue del panel de salidas"),
        "titles": {"inbox": "Despliegue del panel de salidas", "why": "Despliegue de los avisos",
                   "decide": "Visión general de los avisos", "unsourced": "02-nueva-servicio-nocturno"},
    },
}[LANG]

PALETTE = {"bg": "#253850", "alt": "#283536", "surface": "#43363F", "fg": "#E9E9E7", "dim": "#B9B9B9",
           "accent": "#AAA875", "term": "#1E2D40"}


class Take:
    """Screenshots at a fixed rate; scene marks are frame counts over FPS."""

    def __init__(self):
        shutil.rmtree(FRAMES, ignore_errors=True)
        FRAMES.mkdir(parents=True)
        self.n, self.marks = 0, []

    def hold(self, page, seconds: float) -> None:
        for _ in range(max(0, int(seconds * FPS))):
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
            spoken = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                           "csv=p=0", str(voice)], capture_output=True, text=True, check=True).stdout)
            self.hold(page, spoken + 0.8 - (self.n / FPS - start))
        self.scene(name, "end")

    def scroll(self, page, dy: int, seconds: float = 1.6, selector: str | None = None) -> None:
        target = f"document.querySelector('{selector}')" if selector else "window"
        page.evaluate(f"{target}.scrollBy({{top: {dy}, behavior: 'smooth'}})")
        self.hold(page, seconds)

    def save(self) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FRAMES / "%05d.png"),
                        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p", str(OUT / "take.webm")],
                       check=True)
        (OUT / "marks.json").write_text(json.dumps(self.marks, indent=1), encoding="utf-8")
        shutil.rmtree(FRAMES)


def shot(page, name: str) -> None:
    """A README screenshot (English take only): 1280 wide, optimised when optipng is there."""
    if not SHOTS:
        return
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path))
    if shutil.which("optipng"):
        subprocess.run(["optipng", "-quiet", "-o2", str(path)], check=False)


# ── Cards and the terminal ────────────────────────────────────────────────────

def _base(body: str) -> str:
    p = PALETTE
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"body{{margin:0;height:100vh;background:{p['bg']};color:{p['fg']};font-family:Georgia,serif}}"
            f".mono{{font-family:'JetBrains Mono','DejaVu Sans Mono',monospace}}"
            f"</style></head><body>{body}</body></html>")


def card(line: str) -> str:
    logo = base64.b64encode((ROOT / "assets" / "logo-dark.png").read_bytes()).decode()
    return _base(f"<div style='height:100vh;display:grid;place-items:center'><div style='text-align:center'>"
                 f"<img src='data:image/png;base64,{logo}' style='width:620px'>"
                 f"<p style='font-size:27px;margin-top:28px;color:{PALETTE['dim']}'>{html.escape(line)}</p>"
                 f"</div></div>")


def problem(step: int) -> str:
    c, p = COPY, PALETTE
    box = (f"background:{p['alt']};border:1px solid #3c4f66;border-radius:14px;padding:26px 30px;"
           f"box-shadow:0 10px 30px #0004")
    label = f"font:600 15px system-ui;letter-spacing:.08em;text-transform:uppercase;color:{p['accent']}"
    cols = [f"<div style='{box}'><div style='{label}'>{html.escape(c['wiki'])}</div>"
            f"<p style='font-size:30px;margin:18px 0 0'>{html.escape(c['wiki_line'])}</p></div>"]
    if step >= 1:
        cols.append(f"<div style='{box}'><div style='{label}'>{html.escape(c['code'])}</div>"
                    f"<p class='mono' style='font-size:24px;margin:18px 0 6px;color:#9fd39a'>{html.escape(c['code_line'])}</p>"
                    f"<p style='font:16px system-ui;color:{p['dim']};margin:0'>{html.escape(c['code_by'])}</p></div>")
    chat = ""
    if step >= 2:
        chat = (f"<div style='{box};margin-top:28px'><div style='{label}'>{html.escape(c['chat'])}</div>"
                f"<p style='font-size:26px;margin:16px 0 6px'>{html.escape(c['chat_line'])}</p>"
                f"<p style='font:16px system-ui;color:{p['dim']};margin:0'>{html.escape(c['chat_by'])}</p></div>")
    return _base(f"<div style='padding:70px 90px'><h1 style='font-weight:400;font-size:44px;margin:0 0 34px'>"
                 f"{html.escape(c['problem_title'])}</h1><div style='display:grid;grid-template-columns:1fr 1fr;"
                 f"gap:28px'>{''.join(cols)}</div>{chat}</div>")


def terminal(title: str, lines: list[str]) -> str:
    p = PALETTE
    rows = []
    for line in lines:
        text = html.escape(line)
        if line.startswith("$ "):
            text = f"<span style='color:{p['accent']}'>$</span> <b>{html.escape(line[2:])}</b>"
        elif line.startswith("✓"):
            text = f"<span style='color:#9fd39a'>{text}</span>"
        elif line.startswith(("·", "#", "──")):
            text = f"<span style='color:{p['dim']}'>{text}</span>"
        rows.append(f"<div>{text or '&nbsp;'}</div>")
    return _base(
        f"<div style='padding:44px 56px;height:100vh;box-sizing:border-box'>"
        f"<div style='background:{p['term']};border-radius:12px;height:100%;box-shadow:0 14px 40px #0006;"
        f"display:flex;flex-direction:column;overflow:hidden'>"
        f"<div style='padding:12px 18px;background:#16222f;font:14px system-ui;color:{p['dim']};display:flex;gap:8px;"
        f"align-items:center'><span style='width:12px;height:12px;border-radius:50%;background:#c96b5c'></span>"
        f"<span style='width:12px;height:12px;border-radius:50%;background:#d8b56a'></span>"
        f"<span style='width:12px;height:12px;border-radius:50%;background:#7fae76'></span>"
        f"<span style='margin-left:10px'>{html.escape(title)}</span></div>"
        f"<div class='mono' style='padding:20px 24px;font-size:17px;line-height:1.55;white-space:pre;"
        f"color:{p['fg']}'>{''.join(rows)}</div></div></div>")


def type_out(take: Take, page, title: str, blocks: list[tuple[str, list[str]]], pause: float = 0.5) -> None:
    """Shows each command as typed, then its output line by line."""
    shown: list[str] = []
    for command, output in blocks:
        for i in range(0, len(command) + 1, 3):
            page.set_content(terminal(title, shown + ["$ " + command[:i]]))
            take.hold(page, 0.1)
        shown.append("$ " + command)
        page.set_content(terminal(title, shown))
        take.hold(page, 0.4)
        for line in output:
            shown.append(line)
            page.set_content(terminal(title, shown))
            take.hold(page, 0.12)
        take.hold(page, pause)


def _shown(text: str) -> str:
    return text.replace(str(TEAM), SHOWN_HOME).replace(str(ROOT), "~/amanuense")


def open_page(page, path: Path, zoom: float = 1.4) -> None:
    page.goto(path.as_uri())
    page.evaluate(f"document.body.style.zoom = {zoom}")


# ── Scenes ────────────────────────────────────────────────────────────────────

def opening(take: Take, browser) -> None:
    page = browser.new_page(viewport=SIZE)
    take.scene("intro", "start")
    page.set_content(card(COPY["intro"]))
    take.hold(page, 4)
    take.end(page, "intro")

    take.scene("problem", "start")
    for step in range(3):
        page.set_content(problem(step))
        take.hold(page, 2.5)
    take.end(page, "problem")

    take.scene("report", "start")
    open_page(page, WS_OUT / "index.html", 1.45)
    take.hold(page, 2.5)
    shot(page, "report")
    take.scroll(page, 300)
    take.hold(page, 1)
    take.end(page, "report")

    take.scene("unsourced", "start")
    open_page(page, WS_OUT / n("tasks") / COPY["titles"]["unsourced"] / n("changes"), 1.35)
    take.hold(page, 2)
    shot(page, "unsourced")
    take.scroll(page, 260)
    take.end(page, "unsourced")
    page.close()


def review(take: Take, browser) -> None:
    """The review app over the workshop, publishing to the fake Confluence."""
    from amanuense import app, settings

    config = OUT / "config"
    shutil.rmtree(config, ignore_errors=True)
    for key in [k for k in os.environ if k.startswith("AMANUENSE_")]:
        del os.environ[key]
    os.environ.update(AMANUENSE_CONFIG_DIR=str(config), AMANUENSE_USER=build.USER)
    stage = fakes.start(build.stage_world(LANG))
    settings.save({"url": stage.base, "space": fakes.SPACE, "token": fakes.TOKEN})
    server = app.serve(WS, lang=LANG)
    label = lambda key: i18n.TEXT[key][LANG]  # noqa: E731
    page = browser.new_page(viewport=SIZE)
    titles = COPY["titles"]

    def row(title: str):
        return page.locator(".page-row", has_text=title).first

    def tab(key: str):
        return page.locator("button.tab", has_text=label(key).split("{")[0].strip()).first

    try:
        page.goto(server.url)
        page.wait_for_selector(".page-row")

        take.scene("inbox", "start")
        take.hold(page, 2)
        page.locator("details.aside summary").click()
        take.hold(page, 2)
        row(titles["inbox"]).click()
        take.hold(page, 2.5)
        shot(page, "inbox")
        take.end(page, "inbox")

        take.scene("why", "start")
        row(titles["why"]).click()
        take.hold(page, 3)
        shot(page, "diff")
        tab("ui_tab_origin").click()
        take.hold(page, 3)
        shot(page, "why")
        take.end(page, "why")

        take.scene("decide", "start")
        row(titles["decide"]).click()
        take.hold(page, 2)
        page.get_by_role("button", name=label("ui_decide"), exact=True).click()
        take.hold(page, 0.8)
        area = page.locator("form.decide textarea")
        for word in WORLD["decision"].split(" "):
            area.press_sequentially(word + " ")
            take.hold(page, 0.1)
        take.hold(page, 0.8)
        shot(page, "conflict")
        page.get_by_role("button", name=label("ui_save_decision")).click()
        take.hold(page, 2)
        page.get_by_role("button", name=label("ui_approve"), exact=True).click()
        take.hold(page, 2)
        take.end(page, "decide")

        take.scene("publish", "start")
        page.get_by_role("button", name=label("ui_publish"), exact=True).click()
        page.get_by_role("button", name=label("ui_publish_now")).wait_for()
        take.hold(page, 3.5)
        shot(page, "publish")
        page.get_by_role("button", name=label("ui_publish_now")).click()
        page.wait_for_selector(".published")
        take.hold(page, 3.5)
        shot(page, "published")
        take.end(page, "publish")

        take.scene("undo", "start")
        page.locator(".published button").click()
        take.hold(page, 1.5)
        page.locator("dialog[open] button.primary").click()
        page.wait_for_selector(".published", state="detached")
        take.hold(page, 2.5)
        take.end(page, "undo")
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        stage.shutdown()
        stage.server_close()
        shutil.rmtree(config, ignore_errors=True)


def records(take: Take, browser) -> None:
    """The change log, the radiator, the delivery and the radar."""
    page = browser.new_page(viewport=SIZE)
    take.scene("log", "start")
    open_page(page, WS_OUT / n("log_html"), 1.2)
    take.hold(page, 2.5)
    shot(page, "log")
    take.scroll(page, 330, 2.2)
    take.scroll(page, 330, 2.2)
    take.scroll(page, 330, 2.2)
    take.end(page, "log")

    take.scene("radiator", "start")
    open_page(page, WS_OUT / "radiador" / "index.html", 1.15)
    take.hold(page, 2.5)
    page.locator(".item").first.click()
    take.hold(page, 3)
    shot(page, "radiator")
    take.end(page, "radiator")

    from amanuense import taller
    folder = taller.deliver_workspace(WS, make_zip=True, today="2026-10-14", lang=LANG)
    files = sorted(p.relative_to(folder.parent).as_posix() for p in folder.rglob("*") if p.is_file())
    readme = (folder / n("readme")).read_text(encoding="utf-8").splitlines()
    take.scene("deliver", "start")
    type_out(take, page, f"{SHOWN_HOME}/docs-workshop", [
        ("~/amanuense/amanuense.sh deliver --zip --no-open", [_shown(str(folder))]),
        (f"find {n('out')}/{folder.name} -type f | sort | head -n 11", [f"{n('out')}/{f}" for f in files[:11]]),
        (f"head -n 8 {n('out')}/{folder.name}/{n('readme')}", readme[:8]),
    ], pause=1.2)
    take.end(page, "deliver")

    radar_log = (WS / "radar.log").read_text(encoding="utf-8").splitlines()
    locale = {**os.environ, "LC_ALL": "C.UTF-8" if LANG == "en" else "es_ES.UTF-8"}
    log = subprocess.run(["git", "log", "--format=%h %ad %s", "--date=format:%a %d %b", "--", "docs-workshop"],
                         cwd=TEAM, capture_output=True, text=True, check=True, env=locale).stdout.splitlines()
    stat = subprocess.run(["git", "show", "--stat=100", "--format=", "HEAD", "--", "docs-workshop"],
                          cwd=TEAM, capture_output=True, text=True, check=True).stdout.rstrip().splitlines()
    take.scene("radar", "start")
    type_out(take, page, SHOWN_HOME, [
        ("crontab -l", [f"30 7 * * 1-5  ~/amanuense/scripts/radar.sh --workspace {SHOWN_HOME}/docs-workshop --commit"]),
        ("tail -n 5 docs-workshop/radar.log", [_shown(x) for x in radar_log[-5:]]),
        ("git log --oneline --format='%h %ad %s' -- docs-workshop", log),
        ("git show --stat HEAD -- docs-workshop", [x.strip() for x in stat][-5:]),
    ], pause=0.8)
    shot(page, "radar")
    take.end(page, "radar")
    page.close()


def obsidian(take: Take, p, vault: Path) -> None:
    data = OUT / "obsidian-profile"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir()
    (data / "obsidian.json").write_text(json.dumps({"vaults": {"demo": {"path": str(vault), "ts": 1, "open": True}}}))
    proc = subprocess.Popen([*OBSIDIAN, f"--user-data-dir={data}", "--ozone-platform=headless",
                             f"--remote-debugging-port={CDP_PORT}", "--window-size=1280,720"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    root = WORLD["vault"]
    cap, contracts, deployment = COPY["pages"]
    try:
        time.sleep(8)
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        page = [pg for c in browser.contexts for pg in c.pages][-1]
        page.set_viewport_size(SIZE)
        page.evaluate(f"app.workspace.openLinkText('{root}/_index', '', false)")
        time.sleep(2)
        take.scene("obsidian", "start")
        take.hold(page, 3)
        page.evaluate(f"app.workspace.openLinkText('{root}/{cap}/_index', '', false)")
        take.hold(page, 3)
        page.evaluate(f"app.workspace.openLinkText('{root}/{cap}/{contracts}/_index', '', false)")
        take.hold(page, 3)
        page.evaluate(f"app.workspace.openLinkText('{root}/{cap}/{deployment}', '', false)")
        time.sleep(1)
        page.evaluate(REVEAL)
        time.sleep(0.5)
        take.hold(page, 2)
        shot(page, "obsidian")
        take.end(page, "obsidian")
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(data, ignore_errors=True)


def main() -> None:
    take = Take()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        opening(take, browser)
        review(take, browser)
        records(take, browser)
        obsidian(take, p, OUT / "vault")
        page = browser.new_page(viewport=SIZE)
        take.scene("close", "start")
        page.set_content(card(COPY["close"]))
        take.hold(page, 4)
        take.end(page, "close")
        browser.close()
    take.save()
    print(f"{take.n} frames, {take.n / FPS:.1f} s → {OUT / 'take.webm'}")


if __name__ == "__main__":
    main()
