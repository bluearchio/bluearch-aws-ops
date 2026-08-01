from typer.testing import CliRunner

import bluearch


def test_update_help_uses_the_public_ops_command_name():
    """Catches updater help that tells customers to invoke the retired Ops alias."""
    result = CliRunner().invoke(bluearch.cli_app, ["update", "--help"])

    assert result.exit_code == 0
    assert "bluearch-aws-ops update" in result.output
    assert "bluearch update" not in result.output
