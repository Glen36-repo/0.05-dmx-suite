"""Show folder location: source checkout, environment override, installed app seeding."""

import sys
from pathlib import Path

from dmx_suite import paths
from dmx_suite.cli import build_parser, resolve_shows

REPO_SHOWS = Path(__file__).resolve().parents[1] / "shows"


def test_source_checkout_uses_repo_shows(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.default_shows() == REPO_SHOWS


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.default_shows() == tmp_path


def test_cli_flag_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "env"))
    args = build_parser().parse_args(["--shows", str(tmp_path / "flag"), "check"])
    assert resolve_shows(args).shows == tmp_path / "flag"


def test_installed_app_seeds_documents_once(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Documents").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO_SHOWS.parent), raising=False)

    target = paths.default_shows()
    assert target == tmp_path / "Documents" / "0.05 DMX Suite" / "shows"
    assert (target / "fixtures.yaml").read_text() == (REPO_SHOWS / "fixtures.yaml").read_text()

    # the band's edits survive the next start (and upgrades)
    (target / "fixtures.yaml").write_text("edited")
    paths.default_shows()
    assert (target / "fixtures.yaml").read_text() == "edited"


def test_seed_skips_runtime_files(tmp_path):
    src = tmp_path / "src"
    (src / ".backups" / "x").mkdir(parents=True)
    (src / ".state.json").write_text("{}")
    (src / ".giglock").write_text("")
    (src / "fixtures.yaml").write_text("a: 1")
    assert paths.seed_shows(tmp_path / "dst", src)
    assert sorted(p.name for p in (tmp_path / "dst").iterdir()) == ["fixtures.yaml"]
    assert not paths.seed_shows(tmp_path / "dst", src)


def test_no_documents_folder_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert paths.user_shows() == tmp_path / "0.05 DMX Suite" / "shows"


def test_installed_app_seeds_folder_picked_in_installer(monkeypatch, tmp_path):
    picked = tmp_path / "OneDrive" / "Music" / "0.05 DMX Suite" / "shows"
    monkeypatch.setenv(paths.ENV_VAR, str(picked))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO_SHOWS.parent), raising=False)
    assert paths.default_shows() == picked
    assert (picked / "fixtures.yaml").is_file()


def test_installed_app_seeds_folder_given_with_flag(monkeypatch, tmp_path):
    # the installer passes --shows to every shortcut and setup step
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO_SHOWS.parent), raising=False)
    target = tmp_path / "picked" / "shows"
    args = resolve_shows(build_parser().parse_args(["--shows", str(target), "check"]))
    assert args.shows == target
    assert (target / "fixtures.yaml").is_file()


def test_source_checkout_never_creates_flag_folder(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    resolve_shows(build_parser().parse_args(["--shows", str(tmp_path / "nope"), "check"]))
    assert not (tmp_path / "nope").exists()
