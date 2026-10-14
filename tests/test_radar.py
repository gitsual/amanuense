"""scripts/radar.sh: one unattended pass, a snapshot commit only when something really changed."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

RADAR = Path(__file__).resolve().parents[1] / "scripts" / "radar.sh"


def _bash() -> str | None:
    if os.name == "nt":  # never WSL's bash.exe: Git Bash is what the radar targets on Windows
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramW6432", ""),
                     os.environ.get("LOCALAPPDATA", "") + "\\Programs"):
            candidate = Path(base) / "Git" / "bin" / "bash.exe"
            if base and candidate.is_file():
                return str(candidate)
        return None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="needs bash and git")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    """A code repo to follow and a team repo holding the workshop, wired with a file:// URL."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AMANUENSE_", "GIT_"))}
    env.update(HOME=str(tmp_path / "home"), PATH=os.path.dirname(sys.executable) + os.pathsep + env["PATH"],
               GIT_CONFIG_NOSYSTEM="1")
    (tmp_path / "home").mkdir()
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True, env=env)
    for key, value in (("user.name", "Dev One"), ("user.email", "dev@example.com")):
        subprocess.run(["git", "config", key, value], cwd=source, check=True, env=env)
    (source / "service.py").write_text("PORT = 8080\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "feat: add the service"], cwd=source, check=True, env=env)

    team = tmp_path / "team"
    ws = team / "docs"
    ws.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=team, check=True, env=env)
    git(team, "config", "user.name", "Radar Bot")
    git(team, "config", "user.email", "radar@example.com")
    (ws / "repos.txt").write_text(f"{source.as_uri()} @ *\n", encoding="utf-8")
    git(team, "add", ".")
    git(team, "commit", "-qm", "chore: start the workshop")
    dotenv = tmp_path / "radar.env"
    dotenv.write_text("", encoding="utf-8")
    return {"env": env, "source": source, "team": team, "ws": ws, "dotenv": dotenv}


def radar(w: dict, *args: str) -> subprocess.CompletedProcess:
    cmd = [BASH, RADAR.as_posix(), "--workspace", w["ws"].as_posix(), "--env", w["dotenv"].as_posix(), *args]
    return subprocess.run(cmd, env=w["env"], capture_output=True, text=True, encoding="utf-8", timeout=300)


def snapshots(team: Path) -> list[str]:
    return [s for s in git(team, "log", "--format=%s").splitlines() if s.startswith("chore(radar)")]


def test_first_pass_commits_a_snapshot_and_a_quiet_one_does_not(world):
    first = radar(world, "--commit")
    assert first.returncode == 0, first.stdout + first.stderr
    assert len(snapshots(world["team"])) == 1
    tracked = git(world["team"], "ls-files")
    assert "docs/output/log.json" in tracked
    assert "docs/repos/" not in tracked and "radar.log" not in tracked  # clones and the log stay out

    time.sleep(1.1)  # timestamps written by the pass (when it compared, when it read) are not changes
    again = radar(world, "--commit")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "no changes since the last pass" in again.stdout
    assert len(snapshots(world["team"])) == 1
    assert git(world["team"], "status", "--porcelain", "--untracked-files=no") == ""


def test_a_new_upstream_commit_produces_a_snapshot(world):
    assert radar(world, "--commit").returncode == 0
    (world["source"] / "service.py").write_text("PORT = 8443\n")
    subprocess.run(["git", "commit", "-qam", "feat: move the service to 8443"], cwd=world["source"], check=True,
                   env=world["env"])
    done = radar(world, "--commit")
    assert done.returncode == 0, done.stdout + done.stderr
    assert len(snapshots(world["team"])) == 2
    assert "move the service to 8443" in (world["ws"] / "output" / "log.json").read_text(encoding="utf-8")
    assert git(world["team"], "log", "-1", "--format=%an") == "Radar Bot\n"


def test_unreachable_repo_stops_early_without_touching_the_workshop(world):
    (world["ws"] / "repos.txt").write_text((world["source"].parent / "gone").as_uri() + "\n", encoding="utf-8")
    start = time.monotonic()
    done = radar(world, "--commit")
    assert done.returncode == 4
    assert time.monotonic() - start < 30
    assert "cannot reach" in done.stdout + done.stderr
    assert not (world["ws"] / "output").exists()
    assert snapshots(world["team"]) == []


def test_a_running_pass_blocks_another(world):
    (world["ws"] / ".radar.lock").mkdir()
    done = radar(world)
    assert done.returncode == 3
    assert (world["ws"] / ".radar.lock").is_dir()  # someone else's lock is never removed


def test_settings_come_from_the_env_file_even_with_windows_line_ends(world):
    world["dotenv"].write_bytes(b"AMANUENSE_LANG=es\r\nAMANUENSE_USER=Ana Ruiz\r\n")
    done = radar(world)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (world["ws"] / "salida" / "registro.json").is_file()  # "es\r" would not be a language
    assert snapshots(world["team"]) == []  # without --commit nothing is committed


def test_no_name_no_pass(world):
    git(world["team"], "config", "--unset", "user.name")
    done = radar(world)
    assert done.returncode == 1
    assert "AMANUENSE_USER" in done.stdout + done.stderr
