"""scripts/export_ui_texts.py: the review screens' labels as vue-i18n messages under docs.*"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_ui_texts.py"
sys.path.insert(0, str(ROOT / "src"))

from amanuense import i18n  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("export_ui_texts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_label_is_exported_under_docs_in_both_languages():
    run = _run()
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert set(out) == {"es", "en"}
    wanted = [k for k in i18n.TEXT if k.startswith(("ui_", "status_", "origin_"))]
    for lang in ("es", "en"):
        assert set(out[lang]["docs"]) == {"ui", "status", "origin"}
        count = sum(len(group) for group in out[lang]["docs"].values())
        assert count == len(wanted) > 100  # nothing dropped; the real catalogue is big
    assert out["es"]["docs"]["ui"]["title"] == i18n.TEXT["ui_title"]["es"]
    assert out["en"]["docs"]["ui"]["title"] == i18n.TEXT["ui_title"]["en"]
    status = next(k for k in i18n.TEXT if k.startswith("status_"))
    assert out["en"]["docs"]["status"][status.removeprefix("status_")] == i18n.TEXT[status]["en"]


def test_placeholders_are_kept_as_they_are():
    out = json.loads(_run().stdout)
    assert out["es"]["docs"]["ui"]["you_are"] == "Eres {user}"
    assert out["en"]["docs"]["ui"]["missing"] == "Missing: {fields}"


def test_the_keys_file_limits_the_export(tmp_path):
    keys = tmp_path / "keys.txt"
    keys.write_text("# slice 1\ndocs.ui.title\n\ndocs.ui.you_are\n", encoding="utf-8")
    run = _run("--keys", str(keys))
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out["es"] == {"docs": {"ui": {"title": i18n.TEXT["ui_title"]["es"], "you_are": "Eres {user}"}}}
    assert set(out["en"]["docs"]["ui"]) == {"title", "you_are"}


def test_a_key_that_does_not_exist_is_an_error_not_a_silent_gap(tmp_path):
    keys = tmp_path / "keys.txt"
    keys.write_text("docs.ui.title\ndocs.ui.no_such_label\n", encoding="utf-8")
    run = _run("--keys", str(keys))
    assert run.returncode != 0 and "docs.ui.no_such_label" in run.stderr and run.stdout == ""


@pytest.mark.parametrize("text, message", [
    ("plain {name}", "plain {name}"),
    ("mail me@here", "mail me{'@'}here"),
    ("a | b", "a {'|'} b"),
])
def test_characters_vue_i18n_treats_as_syntax_are_escaped(text, message):
    assert _module().message(text) == message
