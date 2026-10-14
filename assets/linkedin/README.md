# LinkedIn carousel

Ten slides at 1200x1500 (4:5), one PDF per language, plus the post text.

| File | What it is |
|---|---|
| `amanuense-carousel-en.pdf` | Carousel, English |
| `amanuense-carousel-es.pdf` | Carousel, Spanish |
| `post-en.md`, `post-es.md` | Post text to go with each carousel |
| `preview.png` | Slides 1, 4, 5 and 6 in a row, shown in the main README |
| `shots/` | Screenshots of the made-up demo workshop and the Obsidian take |
| `build-carousel.py` | Builds the slides and the PDF from `shots/` |

Every picture is a crop of a real screenshot; only the gold boxes are drawn on
top. The workshop UI is in Spanish, so the screenshots are too, in both
languages; the last slide says so.

## Rebuild

Needs Pillow, img2pdf and the Noto fonts (`noto-fonts` on Arch).

```sh
python3 assets/linkedin/build-carousel.py en
python3 assets/linkedin/build-carousel.py es
```

Each run writes `slides-<lang>/` (ignored by git) and the PDF next to the script.

`preview.png` is not built by the script: it is four of the English slides at
300x375, side by side with a 16 px gap, on a transparent background.
