from pathlib import Path

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
