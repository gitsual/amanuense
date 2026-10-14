"""settings: where the Confluence token lives (never in the workshop, never shown again)."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import settings  # noqa: E402

TOKEN = "pat-very-secret-42"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    for k in ("AMANUENSE_CONFLUENCE_URL", "AMANUENSE_CONFLUENCE_TOKEN", "AMANUENSE_CONFLUENCE_SPACE",
              "AMANUENSE_CONFLUENCE_USER", "AMANUENSE_AI_CLI", "AMANUENSE_AI_URL", "AMANUENSE_AI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path / "cfg"


def test_saved_settings_come_back_and_the_summary_hides_the_token(home):
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": TOKEN, "ai_cli": "claude"})
    assert settings.load()["token"] == TOKEN
    summary = settings.summary()
    assert summary["has_token"] and summary["space"] == "WK" and summary["ai_cli"] == "claude"
    assert TOKEN not in json.dumps(summary)


def test_an_empty_token_keeps_the_saved_one(home):
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": TOKEN})
    settings.save({"url": "https://mind.example.org", "space": "OTRO", "token": ""})
    assert settings.load()["token"] == TOKEN and settings.load()["space"] == "OTRO"
    settings.forget_token()
    assert not settings.summary()["has_token"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_the_file_is_private_on_posix(home):
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": TOKEN})
    [path] = home.iterdir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows only")
def test_the_token_is_encrypted_on_windows(home):
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": TOKEN})
    [path] = home.iterdir()
    assert TOKEN not in path.read_text(encoding="utf-8")
    assert settings.load()["token"] == TOKEN


def test_environment_variables_win(home, monkeypatch):
    settings.save({"url": "https://a.example.org", "space": "WK", "token": TOKEN})
    monkeypatch.setenv("AMANUENSE_CONFLUENCE_URL", "https://b.example.org")
    assert settings.load()["url"] == "https://b.example.org"


def test_clients_only_when_configured(home):
    assert settings.mind_client() is None and settings.ai_client() is None
    settings.save({"url": "https://mind.example.org", "space": "WK", "token": TOKEN})
    assert settings.mind_client().space == "WK"
