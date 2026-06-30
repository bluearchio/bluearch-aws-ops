import pytest
from bluearch import cli_app

@pytest.fixture
def mock_version_controller(mocker):
    """Mock version controller functions"""
    mock_get_updates = mocker.patch('aws.misc.version_controller.get_updates')
    return {'get_updates': mock_get_updates}

def test_version_check_with_updates(runner, mock_version_controller):
    mock_version_controller['get_updates'].return_value = [{
        'version': '1.0.1',
        'date': '2024-03-20',
        'message': 'Test update'
    }]

    result = runner.invoke(cli_app, ["--version"], prog_name="bluearch")

    assert result.exit_code == 0
    assert "There's a new version available" in result.stdout

def test_version_check_no_updates(runner, mock_version_controller):
    mock_version_controller['get_updates'].return_value = []

    result = runner.invoke(cli_app, ["--version"], prog_name="bluearch")

    assert result.exit_code == 0
    assert "up to date!" in result.stdout
