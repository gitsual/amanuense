#!/usr/bin/env python3
"""Print the review screens' labels as vue-i18n messages under `docs.ui|status|origin`.

    python scripts/export_ui_texts.py                  # every label
    python scripts/export_ui_texts.py --keys keys.txt  # only the keys listed (one `docs.ui.title` per line)

The output is `{"es": {"docs": {...}}, "en": {"docs": {...}}}`, ready to merge into the host's
locale files; the host owns those files afterwards. `{name}` placeholders mean the same in
vue-i18n, so they are kept; `@` and `|`, which vue-i18n reads as syntax, become literals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n  # noqa: E402

GROUPS = ("ui", "status", "origin")
LANGS = ("es", "en")


def message(text: str) -> str:
    """One label as a vue-i18n message."""
    return text.replace("@", "{'@'}").replace("|", "{'|'}")


def labels() -> dict[str, dict[str, str]]:
    """Every exportable label by its output key (`docs.ui.title`), then by language."""
    found = {}
    for key, texts in i18n.TEXT.items():
        group, _, rest = key.partition("_")
        if group in GROUPS:
            found[f"docs.{group}.{rest}"] = texts
    return found


def export(only: list[str] | None = None) -> dict:
    available = labels()
    if only is not None:
        unknown = [k for k in only if k not in available]
        if unknown:
            raise KeyError(", ".join(unknown))
        available = {k: available[k] for k in only}
    out: dict = {lang: {"docs": {}} for lang in LANGS}
    for key, texts in available.items():
        _, group, rest = key.split(".", 2)
        for lang in LANGS:
            out[lang]["docs"].setdefault(group, {})[rest] = message(texts[lang])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keys", type=Path, help="file with the keys to export, one per line (# comments allowed)")
    args = parser.parse_args(argv)
    only = None
    if args.keys:
        lines = args.keys.read_text(encoding="utf-8").splitlines()
        only = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    try:
        out = export(only)
    except KeyError as exc:
        print(f"unknown keys: {exc.args[0]}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
