"""settings v2: declarative key registry, env > settings.json > default, atomic all-or-nothing writes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from amanuense import settings  # noqa: E402

ABS = str(Path(os.path.abspath(os.sep)) / "data" / "ws")  # absolute on POSIX and Windows
CATALOG = [  # wire, env var, kind, owner, restart_required
    ("workspace", "AMANUENSE_WORKSPACE", "path", "amanuense", True),
    ("lang", "AMANUENSE_LANG", "enum", "amanuense", True),
    ("user", "AMANUENSE_USER", "text", "amanuense", False),
    ("ai_cli", "AMANUENSE_AI_CLI", "enum", "amanuense", False),
    ("ai_url", "AMANUENSE_AI_URL", "url", "amanuense", False),
    ("ai_model", "AMANUENSE_AI_MODEL", "text", "amanuense", False),
    ("ai_key", "AMANUENSE_AI_KEY", "secret", "amanuense", False),
    ("mind_url", "AMANUENSE_CONFLUENCE_URL", "url", "amanuense", False),
    ("mind_token", "AMANUENSE_CONFLUENCE_TOKEN", "secret", "amanuense", False),
    ("mind_space", "AMANUENSE_CONFLUENCE_SPACE", "text", "amanuense", False),
    ("mind_user", "AMANUENSE_CONFLUENCE_USER", "text", "amanuense", False),
    ("mind_root_page", "AMANUENSE_CONFLUENCE_ROOT", "text", "amanuense", False),
    ("vault_path", "OBSIDIAN_VAULT_PATH", "path", "host", True),
    ("ollama_api_base", "OLLAMA_API_BASE", "url", "host", True),
    ("notebook_model", "NOTEBOOK_MODEL", "text", "host", True),
    ("documentation_enabled", "OBSIDIAN_SEARCH_DOCUMENTATION", "bool", "host", True),
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for _, var, *_ in CATALOG:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AMANUENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_home", lambda: tmp_path / "home")
    monkeypatch.setattr(settings, "_BOOT", None)
    return tmp_path / "cfg"


def stored(home):
    return json.loads((home / "settings.json").read_text(encoding="utf-8"))


def row(name, **kw):
    return next(f for f in settings.fields(**kw) if f["key"] == name)


def test_a_v1_file_is_read_unchanged(home):
    home.mkdir()
    (home / "settings.json").write_text(json.dumps(
        {"url": "https://m.example.org", "space": "WK", "user": "ana", "token": "t0k", "ai_cli": "claude"}))
    assert settings.value("mind_url") == "https://m.example.org" and settings.value("mind_user") == "ana"
    assert settings.load()["token"] == "t0k" and row("mind_token")["set"] is True


def test_legacy_save_keeps_v2_and_unknown_keys(home):
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"version": 2, "lang": "en", "legacy_x": 1}))
    settings.save({"url": "https://m.example.org", "space": "WK"})
    assert stored(home)["lang"] == "en" and stored(home)["legacy_x"] == 1 and stored(home)["space"] == "WK"


@pytest.mark.parametrize("wire,var,kind,owner,restart", CATALOG)
def test_catalog_row(home, monkeypatch, wire, var, kind, owner, restart):
    f = row(wire)
    assert (f["env_var"], f["kind"], f["owner"], f["restart_required"]) == (var, kind, owner, restart)
    assert f["source"] in ("default", "settings.json") and f["editable"] and f["pending_restart"] is False
    monkeypatch.setenv(var, "0" if kind == "bool" else "from-env")
    f = row(wire)
    assert (f["source"], f["editable"]) == ("environment", False)
    assert f["value"] is None if kind == "secret" else f["value"] in ("from-env", False)


def test_precedence_env_then_file_then_default(home, monkeypatch):
    assert row("ai_model")["source"] == "default"
    settings.update({"ai_model": "from-file"})
    assert (row("ai_model")["value"], row("ai_model")["source"]) == ("from-file", "settings.json")
    monkeypatch.setenv("AMANUENSE_AI_MODEL", "from-env")
    assert (settings.value("ai_model"), row("ai_model")["source"]) == ("from-env", "environment")
    assert stored(home)["ai_model"] == "from-file"


def test_defaults_for_workspace_and_vault(home, tmp_path):
    base = tmp_path / "home" / "Documents" if settings._windows() else tmp_path / "home"  # where Windows users keep files
    assert settings.value("workspace") == str(base / "docs-workshop")
    (base / "taller-docs").mkdir(parents=True)
    assert settings.value("workspace") == str(base / "taller-docs")
    assert settings.value("vault_path") == str(base / "taller-docs" / "vault")
    settings.update({"workspace": ABS})
    assert settings.value("vault_path") == str(Path(ABS) / "vault")


def test_windows_default_lives_in_documents(home, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_windows", lambda: True)
    assert settings.value("workspace") == str(tmp_path / "home" / "Documents" / "docs-workshop")


def test_null_removes_and_absent_keeps(home):
    settings.update({"ai_model": "m", "user": "ana"})
    settings.update({"user": "bob"})
    assert stored(home)["ai_model"] == "m"
    settings.update({"ai_model": None})
    assert "ai_model" not in stored(home) and row("ai_model")["source"] == "default"


def test_secrets_empty_or_absent_keep_and_forget_removes(home):
    settings.update({"ai_key": "k1", "mind_token": "t1"})
    settings.update({"ai_key": "", "user": "ana"})
    assert settings.load()["ai_key"] == "k1" and settings.load()["token"] == "t1"
    settings.forget(["ai_key"])
    assert row("ai_key")["set"] is False and row("mind_token")["set"] is True
    settings.update({"ai_key": "k2"})
    settings.forget(None)
    assert not row("ai_key")["set"] and not row("mind_token")["set"]


def test_all_or_nothing_lists_every_invalid_field(home):
    settings.update({"user": "ana"})
    before = (home / "settings.json").read_bytes()
    with pytest.raises(settings.Invalid) as err:
        settings.update({"user": "bob", "ai_url": "not a url", "workspace": "relative/dir", "lang": "fr",
                         "ai_cli": "nope", "mind_space": "has space", "documentation_enabled": "yes"})
    assert set(err.value.fields) == {"ai_url", "workspace", "lang", "ai_cli", "mind_space", "documentation_enabled"}
    assert (home / "settings.json").read_bytes() == before


def test_valid_values_pass_and_missing_folders_warn(home):
    out = settings.update({"workspace": ABS, "ai_url": "http://127.0.0.1:11434", "ai_cli": "claude", "lang": "es",
                           "documentation_enabled": False})
    assert "workspace" in out["warnings"] and stored(home)["documentation_enabled"] is False
    assert settings.value("documentation_enabled") is False


def test_environment_sourced_key_is_rejected_naming_the_variable(home, monkeypatch):
    monkeypatch.setenv("AMANUENSE_CONFLUENCE_ROOT", "Top")
    with pytest.raises(settings.Invalid) as err:
        settings.update({"mind_root_page": "Other"})
    assert "AMANUENSE_CONFLUENCE_ROOT" in err.value.fields["mind_root_page"]


def test_changing_the_mind_url_needs_a_new_token(home):
    settings.update({"mind_url": "https://a.example.org", "mind_token": "t"})
    with pytest.raises(settings.Invalid) as err:
        settings.update({"mind_url": "https://b.example.org"})
    assert "mind_url" in err.value.fields
    settings.update({"mind_url": "https://b.example.org", "mind_token": "t2"})
    assert settings.load()["token"] == "t2"


def test_stale_revision_conflicts_and_absent_revision_wins(home):
    assert settings.revision() == settings.revision()  # stable for an absent file
    r0 = settings.revision()
    settings.update({"user": "ana"}, revision=r0)
    assert settings.revision() != r0
    with pytest.raises(settings.Conflict) as err:
        settings.update({"ai_model": "m"}, revision=r0)
    assert err.value.revision == settings.revision() and "ai_model" not in stored(home)
    settings.update({"ai_model": "m"})
    assert stored(home)["ai_model"] == "m"


def test_a_failed_replace_leaves_the_file_byte_identical(home, monkeypatch):
    settings.update({"user": "ana"})
    before = (home / "settings.json").read_bytes()

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(settings.os, "replace", boom)
    with pytest.raises(OSError):
        settings.update({"user": "bob"})
    assert (home / "settings.json").read_bytes() == before and [p.name for p in home.iterdir()] == ["settings.json"]


def test_replace_is_retried_on_permission_error(home, monkeypatch):
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked")
        real(a, b)
    monkeypatch.setattr(settings.os, "replace", flaky)
    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    settings.update({"user": "ana"})
    assert len(calls) == 3 and stored(home)["workshop_user"] == "ana"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_the_file_stays_private(home):
    settings.update({"user": "ana"})
    assert (home / "settings.json").stat().st_mode & 0o777 == 0o600


def test_pending_restart_only_on_restart_rows_that_differ_from_boot(home):
    settings.update({"lang": "en"})
    settings.boot_snapshot()
    assert row("lang")["pending_restart"] is False
    settings.update({"lang": "es", "ai_model": "m"})
    assert row("lang")["pending_restart"] is True and row("ai_model")["pending_restart"] is False


def test_dpapi_seals_both_secrets(home, monkeypatch):
    monkeypatch.setattr(settings, "_windows", lambda: True)
    monkeypatch.setattr(settings, "_dpapi", lambda data, protect: data[::-1])
    settings.update({"mind_token": "tok-en", "ai_key": "key-1"})
    raw = (home / "settings.json").read_text(encoding="utf-8")
    assert "tok-en" not in raw and "key-1" not in raw and "token_dpapi" in raw and "ai_key_dpapi" in raw
    assert settings.load()["token"] == "tok-en" and settings.load()["ai_key"] == "key-1"


def test_an_unreadable_blob_is_not_set_and_says_so(home, monkeypatch):
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"ai_key_dpapi": "AAAA"}))

    def bad(data, protect):
        raise OSError("DPAPI")
    monkeypatch.setattr(settings, "_dpapi", bad)
    f = row("ai_key")
    assert f["set"] is False and f["notes"]


def test_notes_from_the_host_are_attached(home):
    assert row("vault_path", notes={"vault_path": ["config.yaml wins"]})["notes"] == ["config.yaml wins"]


def test_cli_prints_the_effective_value(home):
    env = {**os.environ, "PYTHONPATH": str(SRC), "AMANUENSE_CONFIG_DIR": str(home), "AMANUENSE_WORKSPACE": ABS}
    run = subprocess.run([sys.executable, "-m", "amanuense.settings", "get", "workspace"], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout.strip() == ABS



def test_user_lang_and_ai_key_read_through_the_resolver(home, monkeypatch):
    from amanuense import i18n, registro, taller
    settings.update({"user": "from-file", "lang": "es", "ai_url": "http://x.example", "ai_model": "m",
                     "ai_key": "sk-file"})
    monkeypatch.delenv("AMANUENSE_USER", raising=False)
    monkeypatch.setattr(i18n, "_current", i18n._current)  # restored after choose() switches it
    assert registro._user() == "from-file"
    monkeypatch.setenv("AMANUENSE_USER", "from-env")
    assert registro._user() == "from-env"
    assert i18n.choose(None, None, {}) == "es"
    seen = []
    monkeypatch.setattr(taller, "openai_client", lambda url, model, key: seen.append(key))
    settings.ai_client()
    assert seen == ["sk-file"]
