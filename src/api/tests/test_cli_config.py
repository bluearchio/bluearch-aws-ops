import subprocess
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import bluearch
from aws.misc import error_handlings, version_controller
from cli import config
from utils import core_client


def test_update_help_uses_the_public_ops_command_name():
    """Catches updater help that tells customers to invoke the retired Ops alias."""
    result = CliRunner().invoke(bluearch.cli_app, ["update", "--help"])

    assert result.exit_code == 0
    assert "bluearch-aws-ops update" in result.output
    assert "bluearch update" not in result.output


def _patch_update_dependencies(monkeypatch, *, homebrew_installed: bool, updates=None):
    handled = []
    monkeypatch.setattr(version_controller, "get_updates", lambda: updates or [])
    monkeypatch.setattr(core_client, "get_installed_core_version", lambda: "0.2.6")
    monkeypatch.setattr(
        config,
        "detect_homebrew_installation",
        lambda: {"installed": homebrew_installed},
    )
    monkeypatch.setattr(
        error_handlings.error_handler,
        "handle_error",
        lambda error: handled.append(error),
    )
    return handled


def test_homebrew_update_timeout_exits_nonzero_after_reporting(monkeypatch):
    brew = Path("/canonical/homebrew/bin/brew")
    handled = _patch_update_dependencies(monkeypatch, homebrew_installed=True)
    commands = []
    monkeypatch.setattr(config, "_canonical_homebrew_executable", lambda: brew)

    def run(command, **kwargs):
        commands.append(command)
        if command == [str(brew), "update"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    result = CliRunner().invoke(bluearch.cli_app, ["update", "--force"])

    assert result.exit_code == 1
    assert len(handled) == 1
    assert isinstance(handled[0], subprocess.TimeoutExpired)
    assert commands == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "update"],
    ]


def test_homebrew_install_oserror_exits_nonzero_after_reporting(monkeypatch):
    brew = Path("/canonical/homebrew/bin/brew")
    handled = _patch_update_dependencies(
        monkeypatch,
        homebrew_installed=False,
        updates=[{"version": "0.13.5", "minimum_core_version": "0.2.6"}],
    )
    commands = []
    monkeypatch.setattr(config, "_canonical_homebrew_executable", lambda: brew)

    def run(command, **kwargs):
        commands.append(command)
        if command == [str(brew), "install", config.CORE_FORMULA]:
            raise OSError("Homebrew executable disappeared")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    result = CliRunner().invoke(bluearch.cli_app, ["update", "--force"])

    assert result.exit_code == 1
    assert len(handled) == 1
    assert isinstance(handled[0], OSError)
    assert commands == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "install", config.CORE_FORMULA],
    ]


def test_homebrew_upgrade_oserror_exits_nonzero_after_reporting(monkeypatch):
    brew = Path("/canonical/homebrew/bin/brew")
    handled = _patch_update_dependencies(monkeypatch, homebrew_installed=True)
    commands = []
    monkeypatch.setattr(config, "_canonical_homebrew_executable", lambda: brew)
    monkeypatch.setattr(config, "_update_homebrew_core", lambda version, *, brew: True)

    def run(command, **kwargs):
        commands.append(command)
        if command == [str(brew), "upgrade", config.OPS_FORMULA]:
            raise OSError("Homebrew executable disappeared")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    result = CliRunner().invoke(bluearch.cli_app, ["update", "--force"])

    assert result.exit_code == 1
    assert len(handled) == 1
    assert isinstance(handled[0], OSError)
    assert commands == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "update"],
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "upgrade", config.OPS_FORMULA],
    ]
