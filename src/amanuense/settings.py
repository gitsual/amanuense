"""
settings — every user-editable setting of the review app, with one precedence rule.

They live in the user's own folder (%APPDATA%\\amanuense or ~/.config/amanuense), never in
the workshop: the workshop is zipped and shared. Each key resolves environment variable >
settings.json > default. Secrets are sealed with DPAPI on Windows (only this Windows user can
read them back); elsewhere the file is readable by its owner only. Writes are all-or-nothing
and atomic. The file stays flat and additive: unknown keys are always preserved, and a v1
file (no "version") is read as is. Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse

FILE = "settings.json"
SCHEMA_VERSION = 2
FIELDS = ("url", "space", "user", "root_page", "ai_cli", "ai_url", "ai_model")  # legacy (v1) file keys
ENV = {"url": "AMANUENSE_CONFLUENCE_URL", "space": "AMANUENSE_CONFLUENCE_SPACE", "user": "AMANUENSE_CONFLUENCE_USER",
       "root_page": "AMANUENSE_CONFLUENCE_ROOT",
       "token": "AMANUENSE_CONFLUENCE_TOKEN", "ai_cli": "AMANUENSE_AI_CLI", "ai_url": "AMANUENSE_AI_URL",
       "ai_model": "AMANUENSE_AI_MODEL"}
LEGACY = {"url": "mind_url", "space": "mind_space", "user": "mind_user", "root_page": "mind_root_page",
          "token": "mind_token", "ai_cli": "ai_cli", "ai_url": "ai_url", "ai_model": "ai_model", "ai_key": "ai_key"}


@dataclass(frozen=True)
class Key:
    wire: str                      # name on the wire and in the form
    file: str                      # name in settings.json (secrets also get `<file>_dpapi`)
    env: str | None
    group: str
    kind: str                      # path | url | text | enum | bool | secret
    owner: str                     # amanuense | host
    restart: bool = False
    choices: tuple[str, ...] = ()
    default: Callable[[dict], object] = lambda resolved: ""

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


def _home() -> Path:
    return Path.home()


def _windows() -> bool:
    return os.name == "nt"


def _workspace(_resolved: dict) -> str:
    base = _home() / "Documents" if _windows() else _home()
    legacy = base / "taller-docs"
    return str(legacy if legacy.exists() else base / "docs-workshop")


def _user_default(_resolved: dict) -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "?"


KEYS: tuple[Key, ...] = (
    Key("workspace", "workspace", "AMANUENSE_WORKSPACE", "workshop", "path", "amanuense", True, default=_workspace),
    Key("lang", "lang", "AMANUENSE_LANG", "workshop", "enum", "amanuense", True, ("en", "es"), lambda r: "en"),
    Key("user", "workshop_user", "AMANUENSE_USER", "workshop", "text", "amanuense", default=_user_default),
    Key("ai_cli", "ai_cli", "AMANUENSE_AI_CLI", "ai", "enum", "amanuense"),
    Key("ai_url", "ai_url", "AMANUENSE_AI_URL", "ai", "url", "amanuense"),
    Key("ai_model", "ai_model", "AMANUENSE_AI_MODEL", "ai", "text", "amanuense"),
    Key("ai_key", "ai_key", "AMANUENSE_AI_KEY", "ai", "secret", "amanuense"),
    Key("mind_url", "url", "AMANUENSE_CONFLUENCE_URL", "mind", "url", "amanuense"),
    Key("mind_token", "token", "AMANUENSE_CONFLUENCE_TOKEN", "mind", "secret", "amanuense"),
    Key("mind_space", "space", "AMANUENSE_CONFLUENCE_SPACE", "mind", "text", "amanuense"),
    Key("mind_user", "user", "AMANUENSE_CONFLUENCE_USER", "mind", "text", "amanuense"),
    Key("mind_root_page", "root_page", "AMANUENSE_CONFLUENCE_ROOT", "mind", "text", "amanuense"),
    Key("vault_path", "vault_path", "OBSIDIAN_VAULT_PATH", "search", "path", "host", True,
        default=lambda r: str(Path(r["workspace"]) / "vault")),
    Key("ollama_api_base", "ollama_api_base", "OLLAMA_API_BASE", "search", "url", "host", True,
        default=lambda r: "http://127.0.0.1:11434"),
    Key("notebook_model", "notebook_model", "NOTEBOOK_MODEL", "search", "text", "host", True),
    Key("documentation_enabled", "documentation_enabled", "OBSIDIAN_SEARCH_DOCUMENTATION", "search", "bool",
        "host", True, default=lambda r: True),
)
BY_WIRE = {k.wire: k for k in KEYS}


class Invalid(ValueError):
    """One or more submitted fields are not acceptable; nothing was written."""

    def __init__(self, fields: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = fields


class Conflict(Exception):
    """The file changed since the caller read it."""

    def __init__(self, revision: str):
        super().__init__("settings changed")
        self.revision = revision


def config_dir() -> Path:
    if os.environ.get("AMANUENSE_CONFIG_DIR"):
        return Path(os.environ["AMANUENSE_CONFIG_DIR"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "amanuense"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "amanuense"


# ── DPAPI (Windows) ────────────────────────────────────────────────────────────

def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = Blob(len(data), buf), Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):  # UI_FORBIDDEN
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _seal(name: str, value: str) -> dict:
    """The file entry that stores a secret under `name`: DPAPI-sealed on Windows, plain elsewhere."""
    if not value:
        return {}
    if _windows():
        return {f"{name}_dpapi": base64.b64encode(_dpapi(value.encode("utf-8"), True)).decode()}
    return {name: value}


def _open(stored: dict, name: str) -> str:
    if stored.get(f"{name}_dpapi"):
        return _dpapi(base64.b64decode(stored[f"{name}_dpapi"]), False).decode("utf-8")
    return stored.get(name, "")


# ── Read and write ─────────────────────────────────────────────────────────────

_LOCK = threading.Lock()
_BOOT: dict | None = None


def _path() -> Path:
    return config_dir() / FILE


def _stored() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def revision() -> str:
    """Identifies the file content; stable while it is unchanged, also when the file is absent."""
    try:
        return hashlib.sha256(_path().read_bytes()).hexdigest()
    except FileNotFoundError:
        return hashlib.sha256(b"").hexdigest()


def _write(data: dict) -> None:
    """Temp file in the same folder, then os.replace: a failure leaves the old file untouched."""
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".settings-", suffix=".tmp")  # mkstemp: 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        for attempt in range(3):  # an editor or antivirus may hold the file for a moment on Windows
            try:
                os.replace(tmp, _path())
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _modify(change: Callable[[dict], object], revision_: str | None = None):
    """Read-modify-write under the process lock; `change` edits the dict in place."""
    with _LOCK:
        if revision_ is not None and revision_ != revision():
            raise Conflict(revision())
        data = _stored()
        result = change(data)
        _write(data)
        return result


# ── Resolver ───────────────────────────────────────────────────────────────────

def _truthy(text: str) -> bool:
    return text.strip().lower() not in ("0", "false", "no", "off")


def _resolve(env: Mapping[str, str]) -> dict[str, dict]:
    """wire -> {value, source, set?, note?} following environment > settings.json > default."""
    stored, out = _stored(), {}
    for k in KEYS:
        from_env = env.get(k.env) if k.env else None
        entry: dict = {}
        if from_env:
            entry.update(value=_truthy(from_env) if k.kind == "bool" else from_env, source="environment")
        elif k.secret:
            entry.update(value="", source="default")
            if stored.get(k.file) or stored.get(f"{k.file}_dpapi"):
                try:
                    entry.update(value=_open(stored, k.file), source="settings.json")
                except (OSError, ValueError):  # encrypted by another Windows user or machine
                    entry["note"] = "Stored value cannot be read by this user or machine; enter it again."
        elif stored.get(k.file) not in (None, ""):
            entry.update(value=stored[k.file], source="settings.json")
        else:
            entry.update(value=k.default({w: r["value"] for w, r in out.items()}), source="default")
        if k.secret:
            entry["set"] = bool(entry["value"])
        out[k.wire] = entry
    return out


def value(wire: str, env: Mapping[str, str] = os.environ):
    """The effective value of one key."""
    return _resolve(env)[wire]["value"]


def fields(env: Mapping[str, str] = os.environ, *, notes: Mapping[str, list[str]] = {}) -> list[dict]:
    resolved, out = _resolve(env), []
    for k in KEYS:
        r = resolved[k.wire]
        shown = None if k.secret else r["value"]
        row = {"key": k.wire, "env_var": k.env, "group": k.group, "kind": k.kind, "owner": k.owner, "value": shown,
               "source": r["source"], "editable": r["source"] != "environment", "restart_required": k.restart,
               "pending_restart": bool(k.restart and _BOOT is not None and _BOOT.get(k.wire) != r["value"])}
        if k.kind == "enum":
            row["choices"] = list(_choices(k))
        if k.secret:
            row["set"] = r["set"]
        found = [*notes.get(k.wire, []), *([r["note"]] if r.get("note") else [])]
        if found:
            row["notes"] = found
        out.append(row)
    return out


def boot_snapshot(env: Mapping[str, str] = os.environ) -> None:
    """Remembers the values this process starts with, to flag saved-but-not-active restart keys."""
    global _BOOT
    resolved = _resolve(env)
    _BOOT = {k.wire: resolved[k.wire]["value"] for k in KEYS if k.restart}


# ── Validation and updates ─────────────────────────────────────────────────────

def _choices(key: Key) -> tuple[str, ...]:
    if key.wire == "ai_cli":
        from . import taller
        return ("", *sorted(taller.ENGINES))
    return key.choices


def _problem(key: Key, val) -> str | None:
    """Why `val` is not acceptable for `key`, or None."""
    if key.kind == "bool":
        return None if isinstance(val, bool) else "must be true or false"
    if not isinstance(val, str):
        return "must be text"
    text = val.strip()
    if key.kind == "path" and not (text and Path(text).is_absolute()):
        return "must be an absolute path"
    if key.kind == "url":
        parts = urlparse(text)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "must be an http or https URL"
    if key.kind == "enum" and text not in _choices(key):
        return "must be one of: " + ", ".join(c or "(empty)" for c in _choices(key))
    if key.wire == "mind_space" and (not text or any(c.isspace() for c in text)):
        return "must be non-empty and contain no spaces"
    return None


def update(values: Mapping[str, object], *, revision: str | None = None, env: Mapping[str, str] = os.environ) -> dict:
    """Validates every submitted field, then writes them all or none. Returns {"warnings": {...}}.

    Absent keys keep their value; None removes a non-secret (default applies); an empty or absent
    secret keeps the stored one (use forget() to remove it)."""
    errors: dict[str, str] = {}
    changes: dict[str, object] = {}
    for wire, val in values.items():
        key = BY_WIRE.get(wire)
        if key is None:
            errors[wire] = "unknown setting"
        elif key.env and env.get(key.env):
            errors[wire] = f"set by environment variable {key.env}; remove it there to edit it here"
        elif key.secret:
            if isinstance(val, str) and val:
                changes[wire] = val
            elif val not in (None, ""):
                errors[wire] = "must be text"
        elif val is None or (val == "" and key.kind in ("text", "enum")):
            changes[wire] = None
        elif (bad := _problem(key, val)):
            errors[wire] = bad
        else:
            changes[wire] = val.strip() if isinstance(val, str) else val
    stored = _stored()
    sealed = stored.get("token") or stored.get("token_dpapi")
    if ("mind_url" in changes and "mind_url" not in errors and sealed and "mind_token" not in changes
            and (changes["mind_url"] or "") != stored.get("url", "")):
        errors["mind_url"] = "changing the MIND address needs the token entered again"
    if errors:
        raise Invalid(errors)

    def apply(data: dict) -> None:
        for wire, val in changes.items():
            key = BY_WIRE[wire]
            if key.secret:
                for name in (key.file, f"{key.file}_dpapi"):
                    data.pop(name, None)
                data.update(_seal(key.file, val))
            elif val is None:
                data.pop(key.file, None)
            else:
                data[key.file] = val
        data["version"] = SCHEMA_VERSION

    _modify(apply, revision)
    return {"warnings": {w: "folder does not exist" for w, v in changes.items()
                         if BY_WIRE[w].kind == "path" and v and not Path(v).is_dir()}}


def forget(names: Iterable[str] | None = None) -> None:
    """Removes stored secrets by wire name; None removes every one."""
    wanted = [k for k in KEYS if k.secret] if names is None else [BY_WIRE.get(n) for n in names]
    bad = {n: "not a secret" for n, k in zip(names or (), wanted) if k is None or not k.secret}
    if bad:
        raise Invalid(bad)
    _modify(lambda data: [data.pop(n, None) for k in wanted for n in (k.file, f"{k.file}_dpapi")])


# ── Legacy API (v1 callers: the stdlib review app and the clients below) ───────

def load() -> dict:
    resolved = _resolve(os.environ)
    return {legacy: resolved[wire]["value"] for legacy, wire in LEGACY.items()}


def save(values: dict) -> None:
    """Saves the given fields; an empty token keeps the one already saved. Unknown keys survive."""
    token = str(values.get("token") or "").strip()

    def apply(data: dict) -> None:
        for k in FIELDS:
            data[k] = str(values.get(k, data.get(k, ""))).strip()
        if token:
            for name in ("token", "token_dpapi"):
                data.pop(name, None)
            data.update(_seal("token", token))

    _modify(apply)


def forget_token() -> None:
    forget(["mind_token"])


def summary() -> dict:
    """What the browser may see: everything but the token."""
    data = load()
    return {**{k: data[k] for k in FIELDS}, "has_token": bool(data["token"]),
            "from_env": sorted(k for k, var in ENV.items() if os.environ.get(var))}


def mind_client():
    data = load()
    if not (data["url"] and data["token"] and data["space"]):
        return None
    from .mind import Mind
    return Mind(data["url"], data["token"], data["space"], data["user"])


def ai_client():
    data = load()
    from . import taller as kit
    if data["ai_cli"]:
        return kit.cli_client(data["ai_cli"])
    if data["ai_url"] and data["ai_model"]:
        return kit.openai_client(data["ai_url"], data["ai_model"], data["ai_key"])
    return None


def main(argv: list[str]) -> int:
    """`python -m amanuense.settings get <key>` prints one effective value (for launchers)."""
    if len(argv) == 2 and argv[0] == "get" and argv[1] in BY_WIRE:
        shown = value(argv[1])
        print(str(shown).lower() if isinstance(shown, bool) else shown)
        return 0
    print("usage: python -m amanuense.settings get <" + "|".join(BY_WIRE) + ">", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
