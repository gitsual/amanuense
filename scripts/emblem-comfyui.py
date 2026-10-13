#!/usr/bin/env python3
"""Generate the amanuense emblem with Flux on a local ComfyUI.

The palette is Letrávora's (assets/theme.conf): off-white page and silver ink
growing out of a night-blue ground, with sand gold as the only accent.

    python scripts/emblem-comfyui.py [--seeds 4] [--url http://127.0.0.1:8188]

Writes candidates to assets/brand/candidates/; the chosen one is copied by hand
to assets/brand/emblem-flux.png. The prompt travels inside each PNG.
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

PROMPT = (
    "A flat vector emblem logo for a documentation scribe brand, centered on a solid deep night-blue "
    "background (#253850). A circular medallion in dark plum (#43363F) framed by a thin antique sand-gold "
    "ring (#AAA875). Inside the medallion: a minimalist old book lying open, a single quill pen writing on "
    "its right page, and fine mycelium threads growing out of the pages like roots, all drawn in off-white "
    "(#E9E9E7) and silver grey (#B9B9B9) lines, with the quill nib and the book spine in sand gold. "
    "Symmetric, elegant, engraved line art, no text, no letters, no gradients, high contrast, clean edges."
)


def workflow(seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev-fp8.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                                                         "clip_name2": "clip_l.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": PROMPT}},
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": 3.5}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 0],
                                                   "latent_image": ["6", 0], "seed": seed, "steps": 20, "cfg": 1.0,
                                                   "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": f"amanuense_emblem_{seed}"}},
    }


def call(url: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--first-seed", type=int, default=20261013)
    a = ap.parse_args()
    out = Path(__file__).resolve().parents[1] / "assets" / "brand" / "candidates"
    out.mkdir(parents=True, exist_ok=True)
    for seed in range(a.first_seed, a.first_seed + a.seeds):
        pid = call(a.url, "/prompt", {"prompt": workflow(seed)})["prompt_id"]
        while True:
            hist = call(a.url, f"/history/{pid}")
            if pid in hist:
                break
            time.sleep(2)
        for img in hist[pid]["outputs"]["9"]["images"]:
            q = f"/view?filename={img['filename']}&subfolder={img['subfolder']}&type={img['type']}"
            with urllib.request.urlopen(a.url + q, timeout=60) as resp:
                (out / f"emblem-{seed}.png").write_bytes(resp.read())
        print(f"seed {seed} -> {out / f'emblem-{seed}.png'}")


if __name__ == "__main__":
    main()
