from types import SimpleNamespace

import pytest

from cli import config


def test_formula_trust_is_exact_and_formula_scoped(monkeypatch):
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._trust_homebrew_formula(config.CORE_FORMULA)
    assert config._trust_homebrew_formula(config.OPS_FORMULA)
    assert commands == [
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-ops"],
    ]


def test_active_homebrew_mutation_trusts_before_install(monkeypatch):
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._run_trusted_homebrew_formula("install", config.CORE_FORMULA)
    assert commands == [
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        ["brew", "install", "bluearchio/tap/bluearch-aws-core"],
    ]


def test_active_homebrew_mutation_rejects_unapproved_formula(monkeypatch):
    commands = []
    monkeypatch.setattr(config.subprocess, "run", lambda command, **kwargs: commands.append(command))

    try:
        config._run_trusted_homebrew_formula("install", "third-party/tap/wrapper")
    except ValueError:
        pass
    else:
        raise AssertionError("unapproved formula should be rejected")

    assert commands == []


def test_outdated_check_trusts_and_queries_only_the_exact_ops_formula(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    result = config._run_trusted_homebrew_outdated()

    assert result.returncode == 0
    assert commands == [
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-ops"],
        ["brew", "outdated", "bluearchio/tap/bluearch-aws-ops"],
    ]


def test_outdated_check_treats_nonzero_as_failure(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=2, stdout="", stderr="tap unavailable"),
        ]
    )
    monkeypatch.setattr(config.subprocess, "run", lambda command, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="tap unavailable"):
        config._run_trusted_homebrew_outdated()


def test_homebrew_detection_executes_resolved_exact_public_target(monkeypatch, tmp_path):
    resolved = tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.4" / "bin" / "bluearch-aws-ops"
    resolved.parent.mkdir(parents=True)
    resolved.write_text("#!/bin/sh\n", encoding="utf-8")
    resolved.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(resolved)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="BlueArch CLI version: 0.13.4\n", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    installation = config.detect_homebrew_installation({"test": public_link})

    assert installation["installed"] is True
    assert installation["binary_path"] == str(public_link)
    assert installation["resolved_binary_path"] == str(resolved)
    assert commands == [[str(resolved), "--version"]]


def test_homebrew_detection_rejects_public_link_to_legacy_target(monkeypatch, tmp_path):
    legacy = tmp_path / "Cellar" / "bluearch" / "0.13.3" / "bin" / "bluearch"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("#!/bin/sh\n", encoding="utf-8")
    legacy.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(legacy)
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config.detect_homebrew_installation({"test": public_link}) == {"installed": False}
    assert commands == []


def test_homebrew_detection_rejects_public_named_binary_from_legacy_formula(monkeypatch, tmp_path):
    renamed_legacy = tmp_path / "Cellar" / "bluearch" / "0.13.3" / "bin" / "bluearch-aws-ops"
    renamed_legacy.parent.mkdir(parents=True)
    renamed_legacy.write_text("#!/bin/sh\n", encoding="utf-8")
    renamed_legacy.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(renamed_legacy)
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config.detect_homebrew_installation({"test": public_link}) == {"installed": False}
    assert commands == []
