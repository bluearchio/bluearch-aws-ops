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


def test_core_version_lookup_spawns_only_the_public_core_executable(monkeypatch, tmp_path):
    """Catches fallback to legacy Core binaries when both names are installed."""
    public_core = tmp_path / "bluearch-aws-core"
    public_core.write_text("#!/bin/sh\n")
    public_core.chmod(0o755)
    legacy_core = tmp_path / "bluearch-core"
    legacy_core.write_text("#!/bin/sh\n")
    legacy_core.chmod(0o755)
    commands = []

    monkeypatch.delenv("BLUEARCH_CORE_BINARY", raising=False)
    monkeypatch.setattr(
        core_client.shutil,
        "which",
        lambda name: {"bluearch-aws-core": str(public_core), "bluearch-core": str(legacy_core)}.get(name),
    )

    class Result:
        returncode = 0
        stdout = "bluearch-aws-core 0.2.6\n"
        stderr = ""

    monkeypatch.setattr(
        core_client.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or Result(),
    )

    assert core_client.get_installed_core_version() == "0.2.6"
    assert commands == [[str(public_core), "--version"]]


@pytest.mark.parametrize(
    "returncode,stdout,stderr",
    [
        (1, "bluearch-aws-core 0.2.6\n", "failed"),
        (0, "bluearch-core 9.9.9\n", ""),
        (0, "wrapper bluearch-aws-core 9.9.9\n", ""),
        (0, "garbage 9.9.9\n", ""),
        (0, "bluearch-aws-core v0.2.6\n", ""),
        (0, "garbage\nbluearch-aws-core 0.2.6\n", ""),
        (0, "", "bluearch-aws-core 0.2.6\n"),
    ],
)
def test_core_version_lookup_rejects_failed_or_non_public_identity(
    monkeypatch, tmp_path, returncode, stdout, stderr
):
    public_core = tmp_path / "bluearch-aws-core"
    public_core.write_text("#!/bin/sh\n")
    public_core.chmod(0o755)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(public_core))

    class Result:
        pass

    result = Result()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    monkeypatch.setattr(core_client.subprocess, "run", lambda *args, **kwargs: result)

    assert core_client.get_installed_core_version() is None


@pytest.mark.parametrize("unsafe_override", ["bluearch", "bluearch-core", "company-core-launcher"])
def test_core_override_rejects_legacy_and_arbitrary_launchers(monkeypatch, tmp_path, unsafe_override):
    """Catches executing a legacy name or arbitrary wrapper through the override."""
    custom_core = tmp_path / "company-core-launcher"
    custom_core.write_text("#!/bin/sh\n")
    custom_core.chmod(0o755)
    public_core = tmp_path / "bluearch-aws-core"
    public_core.write_text("#!/bin/sh\n")
    public_core.chmod(0o755)

    monkeypatch.setattr(core_client.shutil, "which", lambda name: None)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", unsafe_override)
    assert core_client._find_core_executable() is None

    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(public_core))
    assert core_client._find_core_executable() == str(public_core)

    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(custom_core))
    assert core_client._find_core_executable() is None


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


def test_core_bare_public_override_resolves_to_path(monkeypatch, tmp_path):
    """Catches accepting the canonical bare override without normalizing its path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "bluearch-aws-core"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", "bluearch-aws-core")

    assert core_client._find_core_executable() == str(executable)


def test_core_install_command_override_is_ignored(monkeypatch):
    """Catches arbitrary command execution through a legacy install override."""
    monkeypatch.setenv("BLUEARCH_CORE_INSTALL_URL", "company-installer --run")

    assert core_client.core_install_url() == "brew install bluearchio/tap/bluearch-aws-core"
