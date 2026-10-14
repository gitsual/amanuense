# LinkedIn carousel

Ten slides at 1200x1500 (4:5), one PDF per language, plus the post text.

| File | What it is |
|---|---|
| `amanuense-carousel-en.pdf` | Carousel, English |
| `amanuense-carousel-es.pdf` | Carousel, Spanish |
| `post-en.md`, `post-es.md` | Post text to go with each carousel |
| `preview.png` | Slides 1, 4, 5 and 6 in a row, shown in the main README |
| `shots/<lang>/` | Screenshots of the made-up demo workshop and the Obsidian take, per language |
| `capture.py` | Takes the workshop screenshots from `demo/out/<lang>/` |
| `build-carousel.py` | Builds the slides and the PDF from `shots/<lang>/` |

Every picture is a crop of a real screenshot of the workshop in the carousel's own
language; only the gold boxes are drawn on top.

## Rebuild

Needs Pillow, img2pdf and the Noto fonts (`noto-fonts` on Arch). The screenshots
need Playwright and the demo world (`python3 demo/build.py en`); `obs.png` is a
frame of the Obsidian scene of `assets/video/demo-<lang>.mp4`.

```sh
python3 assets/linkedin/capture.py en
python3 assets/linkedin/build-carousel.py en
python3 assets/linkedin/build-carousel.py es
```

Each run writes `slides-<lang>/` (ignored by git) and the PDF next to the script.

`preview.png` is not built by the script: it is four of the English slides at
300x375, side by side with a 16 px gap, on a transparent background.
