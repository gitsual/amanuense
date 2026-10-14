"""
settings — Confluence address and token, and which AI to use, for the review app.

They live in the user's own folder (%APPDATA%\\amanuense or ~/.config/amanuense), never in
the workshop: the workshop is zipped and shared. On Windows the token is encrypted with
DPAPI (only this Windows user can read it back); elsewhere the file is readable by its
owner only. Environment variables (AMANUENSE_CONFLUENCE_*, AMANUENSE_AI_*) win over the file.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

FILE = "settings.json"
FIELDS = ("url", "space", "user", "ai_cli", "ai_url", "ai_model")
ENV = {"url": "AMANUENSE_CONFLUENCE_URL", "space": "AMANUENSE_CONFLUENCE_SPACE", "user": "AMANUENSE_CONFLUENCE_USER",
       "token": "AMANUENSE_CONFLUENCE_TOKEN", "ai_cli": "AMANUENSE_AI_CLI", "ai_url": "AMANUENSE_AI_URL",
       "ai_model": "AMANUENSE_AI_MODEL"}


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


def _seal(token: str) -> dict:
    if not token:
        return {}
    if os.name == "nt":
        return {"token_dpapi": base64.b64encode(_dpapi(token.encode("utf-8"), True)).decode()}
    return {"token": token}


def _open(stored: dict) -> str:
    if stored.get("token_dpapi"):
        return _dpapi(base64.b64decode(stored["token_dpapi"]), False).decode("utf-8")
    return stored.get("token", "")


# ── Read and write ─────────────────────────────────────────────────────────────

def _stored() -> dict:
    try:
        return json.loads((config_dir() / FILE).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if os.name != "nt":
        os.chmod(path, 0o600)


def load() -> dict:
    stored = _stored()
    data = {k: stored.get(k, "") for k in FIELDS}
    try:
        data["token"] = _open(stored)
    except OSError:  # encrypted by another Windows user or machine
        data["token"] = ""
    for key, var in ENV.items():
        if os.environ.get(var):
            data[key] = os.environ[var]
    return data


def save(values: dict) -> None:
    """Saves the given fields; an empty token keeps the one already saved."""
    stored = _stored()
    data = {k: str(values.get(k, stored.get(k, ""))).strip() for k in FIELDS}
    token = str(values.get("token") or "").strip()
    secret = _seal(token) if token else {k: stored[k] for k in ("token", "token_dpapi") if k in stored}
    _write({**data, **secret})


def forget_token() -> None:
    stored = _stored()
    _write({k: v for k, v in stored.items() if k not in ("token", "token_dpapi")})


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
        return kit.openai_client(data["ai_url"], data["ai_model"], os.environ.get("AMANUENSE_AI_KEY", ""))
    return None
