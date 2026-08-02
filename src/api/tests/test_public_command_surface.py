from click import unstyle
from typer.testing import CliRunner

import bluearch


def test_main_help_uses_the_public_scan_and_recommendations_commands(monkeypatch):
    """Catches a help regression that directs customers to renamed commands."""
    from utils import onboarding

    monkeypatch.setattr(onboarding, "is_first_time_user", lambda: False)

    result = CliRunner().invoke(bluearch.cli_app, [])

    assert result.exit_code == 0
    assert "bluearch-aws-ops scan" in result.output
    assert "bluearch-aws-ops recommendations" in result.output
    assert "logs scan" not in result.output
    assert "bluearch web start" not in result.output


def test_version_identifies_public_ops_and_trusts_before_outdated():
    result = CliRunner().invoke(
        bluearch.cli_app,
        ["--version"],
        terminal_width=300,
    )

    assert result.exit_code == 0
    assert result.output.splitlines()[0] == "bluearch-aws-ops 0.13.5"
    core_trust = "brew trust --formula bluearchio/tap/bluearch-aws-core"
    ops_trust = "brew trust --formula bluearchio/tap/bluearch-aws-ops"
    outdated = "brew outdated bluearchio/tap/bluearch-aws-ops"
    assert core_trust in result.output
    assert ops_trust in result.output
    assert outdated in result.output
    assert (
        result.output.index(core_trust)
        < result.output.index(ops_trust)
        < result.output.index(outdated)
    )


def test_web_help_hides_the_core_managed_start_command():
    """Catches exposing direct dashboard startup that Core must manage."""
    result = CliRunner().invoke(bluearch.cli_app, ["web", "--help"])
    plain_output = unstyle(result.output)

    assert result.exit_code == 0
    assert "│ start " not in plain_output
    assert "bluearch-aws-core start --daemon" in plain_output


def test_web_landing_page_does_not_advertise_direct_start():
    """Catches the callback reintroducing a hidden Core-managed command."""
    result = CliRunner().invoke(bluearch.cli_app, ["web"])

    assert result.exit_code == 0
    assert "  start          " not in result.output
    assert "bluearch-aws-core start --daemon" in result.output
