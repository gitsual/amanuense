"""radiador: catalogue of the packages of a scope across repos, branches, registry and pages."""
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import radiador as rad, taller as docs_kit  # noqa: E402


def _git(repo, *args, when="2026-10-01T10:00:00Z"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-c", "user.name=Ana", "-c", "user.email=ana@example.com", *args],
                   cwd=repo, check=True, capture_output=True, env=env)


def _write(repo, path, data):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(json.dumps(data), encoding="utf-8")


def _capability_repo(tmp_path):
    repo = tmp_path / "hmi_capability_tracks"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    _write(repo, "brick.metadata.json", {"kind": "capability", "technology": "angular",
                                         "classification": {"category": "basic", "audience": "runtime"},
                                         "packages": [{"name": "@acme/tracks", "manifest": "libs/package.json"}]})
    _write(repo, "libs/package.json", {"name": "@acme/tracks", "version": "0.0.5", "description": "Tracks",
                                       "peerDependencies": {"@acme/contracts-capability": "^0.1.0",
                                                            "@angular/core": "^21"}})
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: tracks")
    _git(repo, "checkout", "-q", "-b", "feature/next")
    _write(repo, "libs/package.json", {"name": "@acme/tracks", "version": "0.1.0", "description": "Tracks",
                                       "peerDependencies": {"@acme/contracts-capability": "^0.1.0"}})
    _git(repo, "commit", "-q", "-am", "feat: next", when="2026-10-02T10:00:00Z")
    _write(repo, "package.json", {"name": "workspace", "private": True})
    return repo


def test_catalog_follows_branches_registry_and_pages(tmp_path):
    repo = _capability_repo(tmp_path)
    pages = [docs_kit.Page("Tracks", "Lives in hmi_capability_tracks."), docs_kit.Page("Other", "nothing")]
    config = {"scope": "@acme", "registry": "http://registry", "categories": {"basic": "Basic"},
              "overrides": {"@acme/tracks": {"delivery": "D02"}}}
    catalog = rad.build_catalog([repo], pages, config, fetch=lambda url: b'{"versions": {"0.0.5": {}}}')
    [p] = catalog["packages"]
    assert (p["package"], p["category_label"], p["delivery"]) == ("@acme/tracks", "Basic", "D02")
    assert (p["newest"]["branch"], p["newest"]["version"], p["develop"]) == ("feature/next", "0.1.0", "0.0.5")
    assert p["registry"] == {"status": "published", "versions": ["0.0.5"]}
    assert p["coherence"] == "ahead"
    assert p["contracts"] == ["@acme/contracts-capability ^0.1.0"]
    assert p["pages"] == ["Tracks"]


def test_unreachable_or_missing_registry_is_reported_not_raised():
    def missing(url):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    assert rad.registry_versions("http://r", "@acme/x", missing)["status"] == "unpublished"
    assert rad.registry_versions("http://r", "@acme/x", lambda u: 1 / 0)["status"] == "unreachable"
    assert rad.registry_versions("", "@acme/x")["status"] == "unchecked"


def test_confluence_page_has_tables_and_no_script(tmp_path):
    repo = _capability_repo(tmp_path)
    catalog = rad.build_catalog([repo], [], {"scope": "@acme"})
    index = rad.write_radiator(tmp_path / "ws", catalog)
    paste = (index.parent / "PARA-CONFLUENCE.html").read_text(encoding="utf-8")
    assert "<table>" in paste and "@acme/tracks" in paste and "<script" not in paste
    assert '"@acme/tracks"' in index.read_text(encoding="utf-8")


def test_external_packages_appear_without_repo_and_versionless_manifests_do_not(tmp_path):
    repo = _capability_repo(tmp_path)
    _write(repo, "tools/package.json", {"name": "@acme/generators"})
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "chore: tools", when="2026-10-03T10:00:00Z")
    config = {"scope": "@acme", "overrides": {"@acme/menu": {"external": "0.0.4", "category": "basic"}}}
    catalog = rad.build_catalog([repo], [], config)
    by_name = {p["package"]: p for p in catalog["packages"]}
    assert "@acme/generators" not in by_name
    menu = by_name["@acme/menu"]
    assert (menu["repo"], menu["newest"]["version"], menu["branches"]) == ("", "0.0.4", [])


def test_config_saved_by_notepad_with_a_bom_is_read(tmp_path):
    (tmp_path / "radiador.json").write_text('{"scope": "@acme"}', encoding="utf-8-sig")
    assert rad.load_config(tmp_path)["scope"] == "@acme"
