#!/usr/bin/env python3
"""Build the LinkedIn carousel for amanuense (1200x1500, 4:5), one PDF per language.

Every picture is a crop of a real screenshot of the made-up demo workshop
(capture.py) or of the Obsidian take; only the gold boxes are drawn on top.

    python3 build-carousel.py es      # -> amanuense-carousel-es.pdf
    python3 build-carousel.py en
"""
from __future__ import annotations

import sys
from pathlib import Path

import img2pdf
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SHOTS = HERE / "shots"

W, H = 1200, 1500
MARGIN_X = 64
IMG = (58, 400, 1142, 1180)  # x0, y0, x1, y1 of the screenshot card
IW, IH = IMG[2] - IMG[0], IMG[3] - IMG[1]

BG, SURFACE, FG, DIM, ACCENT, BOX = "#253850", "#283536", "#E9E9E7", "#B9B9B9", "#AAA875", "#C9A227"
SERIF = "/usr/share/fonts/noto/NotoSerifDisplay-Regular.ttf"
SANS = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
SANS_B = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
F_KICK = ImageFont.truetype(SANS_B, 28)
F_BODY = ImageFont.truetype(SANS, 36)
F_FOOT = ImageFont.truetype(SANS, 28)
F_ARROW = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf", 28)  # Noto Sans has no →
F_URL = ImageFont.truetype(SANS_B, 40)
URL = "github.com/gitsual/amanuense"

# Shot slides: image, crop rect (x, y, w; h derived from the card), boxes.
SHOT = {
    "hook": ("c02.png", (0, 0, 1400), [(6, 22, 1320, 50)]),
    "informe": ("informe.png", (120, 150, 1500), [(1020, 1040, 400, 145)]),
    "cambios": ("c01.png", (0, 10, 1350), [(40, 160, 760, 44), (840, 262, 360, 56), (840, 550, 640, 56)]),
    "dato": ("c02.png", (1768, 335, 950), [(1790, 560, 420, 52)]),
    "pegar": ("pegar.png", (120, 60, 1450), [(430, 343, 1050, 90)]),
    "registro": ("registro.png", (100, 650, 1980), [(130, 720, 1940, 300), (130, 1000, 1940, 290)]),
    "obsidian": ("obs-71.5.png", (380, 90, 760), []),
}

TEXT = {
    "es": {
        "cover": ("La IA se inventó\nun dato.",
                  "Escribió «200 ms». No estaba en ninguna de sus fuentes.\n"
                  "Amanuense lo marcó antes de aprobar nada."),
        "problem": ("La documentación\nse queda atrás.",
                    "El código cambia y Confluence no.\n\n"
                    "Si le pides a una IA que la ponga al día, rellena huecos con datos "
                    "que nadie le dio. Y suenan igual de seguros que los reales."),
        "informe": ("Confluence contra\ntus borradores",
                    "Le das el export y tus borradores. Te dice qué páginas actualizar, "
                    "cuáles son nuevas y cuáles están duplicadas."),
        "cambios": ("Cada cambio,\nlínea a línea",
                    "Cada página recibe una tarea para la IA que uses. Su propuesta vuelve "
                    "como un diff contra lo publicado."),
        "dato": ("Lo que no tiene fuente,\nse marca",
                 "Cada dato se contrasta con lo que se le dio a la IA. "
                 "Si no aparece en ninguna parte, lo ves antes de aprobar."),
        "pegar": ("Tú apruebas.\nTú pegas.",
                  "Lo que apruebas sale listo para pegar en Confluence. Nada se publica solo."),
        "registro": ("Quién cambió qué",
                     "Ediciones en Confluence, commits que dejan una página desfasada "
                     "y peticiones del equipo, en un solo registro."),
        "obsidian": ("Todo el espacio,\nen Obsidian",
                     "Con un comando, el export entero pasa a un vault que se lee y se enlaza sin conexión."),
        "close": ("Tu máquina.\nTu IA.\nTu aprobación.",
                  ["Corre en local, en Linux y en Windows.",
                   "Claude, Codex, Gemini, Copilot u Ollama.\nO sin IA: pegas tú la tarea en un chat.",
                   "Nada llega a Confluence sin que una\npersona lo revise y lo pegue."]),
        "cta": ("Código abierto · licencia MIT",
                "Los datos y las respuestas de la IA de esta demo son inventados.\nLa interfaz del taller está en español."),
        "swipe": "Desliza →",
    },
    "en": {
        "cover": ("The AI made up\na number.",
                  "It wrote “200 ms”. That number was in none of its sources.\n"
                  "Amanuense flagged it before anything was approved."),
        "problem": ("Docs fall\nbehind.",
                    "The code changes. Confluence doesn't.\n\n"
                    "Ask an AI to catch it up and it fills gaps with numbers nobody "
                    "gave it. They sound just as sure as the real ones."),
        "informe": ("Confluence vs.\nyour drafts",
                    "Give it the export and your drafts. It tells you which pages to "
                    "update, which are new and which are duplicates."),
        "cambios": ("Every change,\nline by line",
                    "Each page gets a task for whichever AI you use. Its proposal comes "
                    "back as a diff against what is published."),
        "dato": ("No source?\nIt gets flagged.",
                 "Every figure is checked against what the AI was given. "
                 "If it appears nowhere, you see it before you approve."),
        "pegar": ("You approve.\nYou paste.",
                  "What you approve comes out ready to paste into Confluence. Nothing publishes itself."),
        "registro": ("Who changed what",
                     "Edits in Confluence, commits that leave a page out of date and "
                     "requests from the team, in one log."),
        "obsidian": ("The whole space,\nin Obsidian",
                     "One command turns the whole export into a vault you can read and link offline."),
        "close": ("Your machine.\nYour AI.\nYour sign-off.",
                  ["Runs locally, on Linux and Windows.",
                   "Claude, Codex, Gemini, Copilot or Ollama.\nOr no AI: paste the task into a chat.",
                   "Nothing reaches Confluence until a\nperson reviews it and pastes it."]),
        "cta": ("Open source · MIT licensed",
                "The data and the AI answers in this demo are made up.\nThe workshop UI is in Spanish."),
        "swipe": "Swipe →",
    },
}


def wrap(draw, text, fnt, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=fnt) <= width:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def header(d, im, idx, total):
    mark = Image.open(REPO / "assets/logo-mark.png").convert("RGBA").resize((72, 72), Image.LANCZOS)
    im.paste(mark, (MARGIN_X, 48), mark)
    d.text((MARGIN_X + 92, 70), "AMANUENSE", font=F_KICK, fill=ACCENT)
    d.text((W - MARGIN_X, 70), f"{idx}/{total}", font=F_KICK, fill=DIM, anchor="ra")


def title(d, text, y, size=68):
    fnt = ImageFont.truetype(SERIF, size)
    for ln in text.split("\n"):
        d.text((MARGIN_X, y), ln, font=fnt, fill=FG)
        y += int(size * 1.18)
    return y


def body(d, text, y, fnt=F_BODY, fill=FG, step=50):
    for ln in wrap(d, text, fnt, W - 2 * MARGIN_X):
        d.text((MARGIN_X, y), ln, font=fnt, fill=fill)
        y += step if ln else step // 2
    return y


def footer(d, text):
    word, arrow = text.rsplit(" ", 1)
    d.text((W - MARGIN_X, H - 72), arrow, font=F_ARROW, fill=ACCENT, anchor="ra")
    aw = d.textlength(arrow, font=F_ARROW) + d.textlength(" ", font=F_FOOT)
    d.text((W - MARGIN_X - aw, H - 72), word, font=F_FOOT, fill=ACCENT, anchor="ra")


def card(im, key):
    name, (x, y, w), boxes = SHOT[key]
    h = w * IH / IW
    src = Image.open(SHOTS / name).convert("RGB")
    canvas = Image.new("RGB", (src.width + 2000, src.height + 2000), "white")
    canvas.paste(src, (1000, 1000))
    crop = canvas.crop((int(x + 1000), int(y + 1000), int(x + w + 1000), int(y + h + 1000)))
    crop = crop.resize((IW, IH), Image.LANCZOS)
    cd = ImageDraw.Draw(crop)
    s = IW / w
    for bx, by, bw, bh in boxes:
        rx, ry = (bx - x) * s, (by - y) * s
        cd.rounded_rectangle((rx - 6, ry - 6, rx + bw * s + 6, ry + bh * s + 6), 10, outline=BOX, width=6)
    mask = Image.new("L", (IW, IH), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, IW - 1, IH - 1), 24, fill=255)
    im.paste(crop, IMG[:2], mask)


def shot_slide(t, key, idx, total, ttl, txt, foot=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, im, idx, total)
    title(d, ttl, 150, 64 if ttl.count("\n") else 68)
    card(im, key)
    body(d, txt, IMG[3] + 36)
    if foot:
        footer(d, foot)
    return im


def build(lang):
    t = TEXT[lang]
    order = ["cover", "problem", "informe", "cambios", "dato", "pegar", "registro", "obsidian", "close", "cta"]
    total = len(order)
    slides = []
    for idx, key in enumerate(order, 1):
        if key == "cover":
            im = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(im)
            header(d, im, idx, total)
            title(d, t["cover"][0], 150, 84)
            card(im, "hook")
            body(d, t["cover"][1], IMG[3] + 36)
            footer(d, t["swipe"])
        elif key == "problem":
            im = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(im)
            header(d, im, idx, total)
            y = title(d, t["problem"][0], 360, 96)
            d.line((MARGIN_X, y + 40, MARGIN_X + 160, y + 40), fill=ACCENT, width=6)
            body(d, t["problem"][1], y + 110, ImageFont.truetype(SANS, 44), FG, 62)
        elif key == "close":
            im = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(im)
            header(d, im, idx, total)
            y = title(d, t["close"][0], 230, 96) + 70
            f = ImageFont.truetype(SANS, 40)
            for item in t["close"][1]:
                d.rectangle((MARGIN_X, y + 14, MARGIN_X + 14, y + 28), fill=ACCENT)
                for ln in item.split("\n"):
                    d.text((MARGIN_X + 44, y), ln, font=f, fill=FG)
                    y += 54
                y += 44
        elif key == "cta":
            im = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(im)
            logo = Image.open(REPO / "assets/logo-dark.png").convert("RGBA")
            # Drop the tagline under the wordmark; the LinkedIn post only says "Confluence".
            ImageDraw.Draw(logo).rectangle((300, 240, logo.width, 285), fill=(0, 0, 0, 0))
            logo = logo.resize((960, int(logo.height * 960 / logo.width)), Image.LANCZOS)
            im.paste(logo, ((W - logo.width) // 2, 430), logo)
            d.text((W // 2, 780), URL, font=F_URL, fill=ACCENT, anchor="ma")
            d.text((W // 2, 860), t["cta"][0], font=ImageFont.truetype(SANS, 38), fill=FG, anchor="ma")
            y = 1240
            for ln in t["cta"][1].split("\n"):
                d.text((W // 2, y), ln, font=F_FOOT, fill=DIM, anchor="ma")
                y += 42
        else:
            ttl, txt = t[key]
            im = shot_slide(t, key, idx, total, ttl, txt)
        slides.append(im)
    out = HERE / f"slides-{lang}"
    out.mkdir(exist_ok=True)
    paths = []
    for i, im in enumerate(slides, 1):
        p = out / f"{i:02d}.png"
        im.save(p)
        paths.append(str(p))
    pdf = HERE / f"amanuense-carousel-{lang}.pdf"
    pdf.write_bytes(img2pdf.convert(paths))
    print(pdf)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "es")
