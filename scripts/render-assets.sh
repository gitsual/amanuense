#!/usr/bin/env bash
# Regenerate every rendered asset under assets/ from its source and the palette
# in assets/theme.conf.
#
#   scripts/render-assets.sh            # everything
#   scripts/render-assets.sh logos      # only the logos
#   scripts/render-assets.sh demo [es]  # the demo video, English by default (needs tramoya, see demo/)
#   scripts/render-assets.sh intake [es]  # the intake demo (a pile of documents dropped in), same needs
#
# The mark is assets/brand/emblem-flux.png, generated with Flux on a local
# ComfyUI by scripts/emblem-comfyui.py from the palette's own colours; the
# wordmark and everything around it are derived from theme.conf at render time.
# Needs: magick (logos); tramoya, ffmpeg and Chromium for Playwright (demo).
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source assets/theme.conf
what=${1:-all}

font_pick() {
  for f in Noto-Serif-Display-Regular Noto-Serif-Regular Liberation-Serif; do
    if magick -list font 2>/dev/null | grep -q "Font: $f\$"; then echo "$f"; return; fi
  done
  echo Liberation-Serif
}

logos() {
  echo "-- logos"
  local emblem=assets/brand/emblem-flux.png font
  font=$(font_pick)
  # Medallion: the emblem cropped to its ring, everything outside the circle
  # made transparent (the generated image carries its own background).
  local medallion mask w h r cx cy; medallion=$(mktemp --suffix=.png); mask=$(mktemp --suffix=.png)
  magick "$emblem" -gravity center -crop 62%x62%+0+0 +repage "$medallion"
  w=$(magick identify -format "%w" "$medallion"); h=$(magick identify -format "%h" "$medallion")
  cx=$((w / 2)); cy=$((h / 2)); r=$((w / 2 - 2))
  magick -size "${w}x${h}" xc:black -fill white -draw "circle $cx,$cy $cx,$((cy - r))" "$mask"
  magick "$medallion" "$mask" -alpha off -compose CopyOpacity -composite -compose Over \
    -bordercolor none -border 6% -resize 360x360 assets/logo-mark.png
  local ring; ring=$(mktemp --suffix=.png)
  magick assets/logo-mark.png -resize 300x300 "$ring"
  wordmark() {  # <fg> <accent> <out>
    magick "$ring" \
      \( -background none -fill "#$1" -font "$font" -pointsize 140 -kerning 4 label:amanuense \
         \( -background none -fill "#$2" -font "$font" -pointsize 28 -kerning 8 \
            label:"MIND · CONFLUENCE · OBSIDIAN" \) \
         -gravity west -append \) \
      -gravity center -background none +smush 32 \
      -bordercolor none -border 24x16 +repage "$3"
  }
  wordmark "$COLOR_FG" "$COLOR_ACCENT" assets/logo-dark.png
  wordmark "$COLOR_BG" "$COLOR_SURFACE" assets/logo-light.png
  rm -f "$ring" "$medallion" "$mask"
}

demo() {  # [en|es], default en; the English take is also the README preview
  local lang=${1:-en}
  echo "-- demo ($lang)"
  python3 demo/build.py "$lang"
  narrate demo "$lang" "demo/out/$lang" demo/script.json demo/record.py
  [[ $lang == en ]] || return 0
  preview_gif "demo/out/$lang/take.webm" assets/video/demo.gif
}

narrate() {  # <name> <lang> <out> <script> <recorder>: voices, the take, then both joined
  local name=$1 lang=$2 out=$3 script=$4 recorder=$5
  local py=${PLAYWRIGHT_PYTHON:-python3} tramoya=${TRAMOYA:-tramoya}
  "$tramoya" tts --script "$script" --lang "$lang" --out-dir "$out/voices"
  "$py" "$recorder" "$lang"
  "$tramoya" assemble --video "$out/take.webm" --marks "$out/marks.json" \
    --voice-dir "$out/voices" --out "$out/$name.mp4" --lang "$lang"
  mkdir -p assets/video
  cp "$out/$name.mp4" "assets/video/$name-$lang.mp4"
}

preview_gif() {  # <take.webm> <out.gif>: silent README preview, double speed, small palette
  ffmpeg -y -loglevel error -i "$1" -vf \
    "setpts=0.5*PTS,fps=6,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer" \
    "$2"
}

intake() {  # [en|es], default en; the English take is also the README preview
  local lang=${1:-en}
  echo "-- intake ($lang)"
  python3 demo/intake/pile.py "$lang"
  narrate intake "$lang" "demo/out/intake/$lang" demo/intake/script.json demo/intake/take.py
  [[ $lang == en ]] || return 0
  preview_gif demo/out/intake/en/take.webm assets/video/intake.gif
}

case $what in
  logos) logos ;;
  demo) demo "${2:-en}" ;;
  intake) intake "${2:-en}" ;;
  all) logos; demo en; demo es; intake en; intake es ;;
  *) echo "unknown target: $what" >&2; exit 2 ;;
esac
