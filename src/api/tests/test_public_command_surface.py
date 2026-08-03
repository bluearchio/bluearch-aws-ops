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


def test_version_is_one_exact_machine_readable_public_identity():
    result = CliRunner().invoke(
        bluearch.cli_app,
        ["--version"],
        terminal_width=300,
    )

    assert result.exit_code == 0
    assert result.output == "bluearch-aws-ops 0.13.8\n"


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
