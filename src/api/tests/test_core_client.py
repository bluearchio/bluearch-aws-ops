from pathlib import Path

import pytest

from utils import core_client


def test_missing_core_token_tells_customers_to_start_the_public_core_command(monkeypatch, tmp_path):
    """Catches recovery guidance that sends customers to the removed core executable."""
    monkeypatch.setenv("BLUEARCH_CORE_TOKEN_PATH", str(tmp_path / "missing-token"))

    try:
        core_client.read_service_token()
    except core_client.CoreRuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("missing Core token should be reported")

    assert "bluearch-aws-core start --daemon" in message
    assert "bluearch-core start" not in message


def test_core_version_lookup_spawns_only_the_public_core_executable(monkeypatch):
    """Catches fallback to legacy Core binaries when both names are installed."""
    public_core = "/opt/homebrew/bin/bluearch-aws-core"
    legacy_core = "/opt/homebrew/bin/bluearch-core"
    commands = []

    monkeypatch.delenv("BLUEARCH_CORE_BINARY", raising=False)
    monkeypatch.setattr(
        core_client.shutil,
        "which",
        lambda name: {"bluearch-aws-core": public_core, "bluearch-core": legacy_core}.get(name),
    )

    class Result:
        stdout = "BlueArch Core v0.2.6"
        stderr = ""

    monkeypatch.setattr(
        core_client.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or Result(),
    )

    assert core_client.get_installed_core_version() == "0.2.6"
    assert commands == [[public_core, "--version"]]


@pytest.mark.parametrize("legacy_override", ["bluearch", "bluearch-core"])
def test_core_override_rejects_bare_legacy_names_but_accepts_public_and_custom_paths(
    monkeypatch, tmp_path, legacy_override
):
    """Catches executing a legacy override while preserving supported custom launchers."""
    custom_core = tmp_path / "company-core-launcher"
    custom_core.write_text("#!/bin/sh\n")
    custom_core.chmod(0o755)
    public_core = tmp_path / "bluearch-aws-core"
    public_core.write_text("#!/bin/sh\n")
    public_core.chmod(0o755)

    monkeypatch.setattr(core_client.shutil, "which", lambda name: None)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", legacy_override)
    assert core_client._find_core_executable() is None

    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(public_core))
    assert core_client._find_core_executable() == str(public_core)

    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(custom_core))
    assert core_client._find_core_executable() == str(custom_core)


def test_core_resolver_rejects_public_named_symlink_to_legacy_target(monkeypatch, tmp_path):
    """Catches a public Core filename masking a bluearch-core target."""
    legacy_core = tmp_path / "bluearch-core"
    legacy_core.write_text("#!/bin/sh\n")
    legacy_core.chmod(0o755)
    public_symlink = tmp_path / "bluearch-aws-core"
    public_symlink.symlink_to(legacy_core)

    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(public_symlink))
    monkeypatch.setattr(core_client.shutil, "which", lambda name: str(public_symlink))

    assert core_client._find_core_executable() is None

    monkeypatch.delenv("BLUEARCH_CORE_BINARY")
    assert core_client._find_core_executable() is None


def test_core_bare_public_override_rejects_path_symlink_to_legacy_target(monkeypatch, tmp_path):
    """Catches subprocess PATH resolution bypassing the Core legacy-target guard."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    legacy_core = bin_dir / "bluearch-core"
    legacy_core.write_text("#!/bin/sh\n")
    legacy_core.chmod(0o755)
    public_symlink = bin_dir / "bluearch-aws-core"
    public_symlink.symlink_to(legacy_core)
    commands = []

    class Result:
        stdout = "BlueArch Core v0.2.6"
        stderr = ""

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", "bluearch-aws-core")
    monkeypatch.setattr(
        core_client.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or Result(),
    )

    assert core_client.get_installed_core_version() is None
    assert commands == []


@pytest.mark.parametrize("override_name", ["bluearch-aws-core", "company-core-launcher"])
def test_core_bare_nonlegacy_override_resolves_to_path(monkeypatch, tmp_path, override_name):
    """Catches accepting a valid bare override without normalizing its executable path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / override_name
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", override_name)

    assert core_client._find_core_executable() == str(executable)
