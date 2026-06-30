import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, AsyncMock, patch
from aws.misc.alarm_ui import configure_alarms, configure_targets, AlarmConfigUI, AlarmTargetUI

@pytest.fixture
def mock_get_recommendations(mocker):
    """
    Fixture to mock the get.get_recommendations function.
    """
    return mocker.patch('commons.get.get_recommendations')

@pytest.fixture
def mock_config_file(mocker):
    """Mock file operations for ConfigManager"""
    mocker.patch('os.path.expanduser', return_value='/mock/home')
    mock_open = mocker.patch('builtins.open', mocker.mock_open(read_data='{}'))
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.makedirs')
    return mock_open

@pytest.fixture
def mock_display(mocker):
    """Mock display functions"""
    mock = mocker.patch('aws.misc.display.display_manual_instructions_workflow')
    mock.return_value = ['123456789012', '210987654321']  # Default test account IDs
    
    # Mock other display functions if needed
    mocker.patch('aws.misc.display.display_recommendations')
    mocker.patch('aws.misc.display.display_recommendation_types')
    mocker.patch('aws.misc.display.display_scheduler_info')
    mocker.patch('aws.misc.display.display_bluearch_ascii_art')
    mocker.patch('aws.misc.display.display_accounts_and_regions')
    
    return mock

@pytest.fixture
def mock_console(mocker):
    return mocker.patch('rich.console.Console')

@pytest.fixture
def mock_populate(mocker):
    """
    Fixture to mock the populate function.
    """
    return mocker.patch('cli.recommendations.populate')

@pytest.fixture
def mock_display_recommendations(mocker):
    """
    Fixture to mock the display.display_recommendations function.
    """
    return mocker.patch('aws.misc.display.display_recommendations')

@pytest.fixture
def mock_get_accounts_and_regions(mocker):
    """Mock get_accounts_and_regions to prevent actual AWS calls"""
    mock = mocker.patch('commons.get.get_accounts_and_regions')
    mock.return_value = {
        '123456789012': {
            'account_name': 'TestAccount',
            'regions': ['us-east-1', 'us-west-2']
        }
    }
    
    # Also mock at module level
    mocker.patch('commons.execution.get_accounts_and_regions', return_value=mock.return_value)
    
    return mock


@pytest.fixture
def mock_error_handler(mocker):
    """
    Mock error handler with console and all necessary methods.
    This provides a centralized way to verify error handling in CLI tests.
    """
    mock = mocker.patch('aws.misc.error_handlings.error_handler')
    
    # Create console mock that will be used directly
    mock.console = mocker.MagicMock()
    
    # Set up all error handling methods
    mock.handle_error = mocker.MagicMock()
    mock.handle_update_error = mocker.MagicMock()
    mock.handle_dynamodb_error = mocker.MagicMock()
    mock.handle_scheduler_error = mocker.MagicMock()
    
    # Configure mock to return itself when called
    mock.return_value = mock
    
    return mock

@pytest.fixture
def runner():
    """
    Fixture for invoking command-line interfaces.
    """
    return CliRunner()

@pytest.fixture
def mock_logger(mocker):
    """Mock logger for ConfigManager"""
    return mocker.patch('utils.logger_config.log')

@pytest.fixture
def mock_eb_client(mocker):
    """
    Fixture to mock the EventBridge client.
    """
    mock_eb = mocker.patch('aws.wrappers.eventbridge.EventBridge')
    instance = mock_eb.return_value
    instance.GetScheduleStatus.return_value = "DISABLED"
    instance.SetScheduleExpression.return_value = "rate(1 day)"
    return instance

@pytest.fixture
def mock_console(mocker):
    """
    Fixture to mock the Rich Console.
    """
    return mocker.patch('rich.console.Console')

@pytest.fixture
def mock_eb_client(mocker):
    """Mock EventBridge client"""
    return mocker.patch('aws.wrappers.eventbridge.EventBridge')

@pytest.fixture
def mock_compute_optimizer(mocker):
    """Mock ComputeOptimizer for populate tests"""
    mock_co = mocker.patch('aws.wrappers.co.ComputeOptimizer')
    instance = mock_co.return_value
    instance.handle_compute_optimizer_activation.return_value = None
    return instance

@pytest.fixture
def mock_organizations(mocker):
    """Mock Organizations for populate tests"""
    mock_org = mocker.patch('aws.wrappers.organizations.Organizations')
    instance = mock_org.return_value
    instance.client.describe_account.return_value = {
        'Account': {'Name': 'TestAccount'}
    }
    return instance

@pytest.fixture
def mock_webbrowser(mocker):
    """Mock webbrowser to prevent actual browser opening"""
    return mocker.patch('webbrowser.open', return_value=True)

@pytest.fixture
def mock_prompt(mocker):
    """Mock Rich Prompt for user inputs"""
    mock = mocker.patch('rich.prompt.Prompt')
    mock.ask = mocker.MagicMock()
    return mock

@pytest.fixture
def mock_cloudformation(mocker):
    """Mock CloudFormation wrapper"""
    mock = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
    instance = mock.return_value
    instance.check_stack_exists.return_value = True
    instance.delete_stack.return_value = True
    instance.describe_change_set.return_value = {"Changes": []}
    return mock

@pytest.fixture
def mock_refresh_accounts(mocker):
    """Mock refresh_accounts_n_regions_table function"""
    return mocker.patch('commons.get.refresh_accounts_n_regions_table')

@pytest.fixture(autouse=True)
def mock_version_controller(mocker):
    """Mock version controller functions"""
    mock_get_updates = mocker.patch('aws.misc.version_controller.get_updates')
    return {'get_updates': mock_get_updates}

@pytest.fixture(autouse=True)
def mock_subprocess(mocker):
    """Mock subprocess calls"""
    mock = mocker.patch('subprocess.run')
    mock.return_value.returncode = 0
    return mock

@pytest.fixture(autouse=True)
def mock_platform(mocker):
    """Mock platform.machine()"""
    return mocker.patch('platform.machine', return_value='x86_64')

@pytest.fixture
def mock_event_hook_client(mocker):
    """Mock legacy event hook client fixture."""
    return mocker.MagicMock()

@pytest.fixture
def mock_textual_app(mocker):
    """Mock Rich UI components (legacy name kept for compatibility)"""
    mocker.patch('aws.misc.alarm_ui.AlarmConfigUI.run')
    mocker.patch('aws.misc.alarm_ui.AlarmTargetUI.run')
    return mocker

@pytest.fixture
def mock_config_dir(mocker):
    """Mock configuration directory"""
    mocker.patch('os.path.expanduser', return_value='/mock/home')
    mocker.patch('os.makedirs')
    return mocker

@pytest.fixture
def mock_cloudwatch(mocker):
    mock = mocker.patch('aws.wrappers.cloudwatch.CloudWatchWrapper')
    instance = mock.return_value
    instance.get_alarms.return_value = []
    instance.create_alarm.return_value = True
    return mock

@pytest.fixture
def mock_sns(mocker):
    mock = mocker.patch('aws.wrappers.sns.SnsWrapper')
    instance = mock.return_value
    instance.list_subscriptions.return_value = []
    instance.create_subscription.return_value = "arn:aws:sns:subscription"
    return mock

@pytest.fixture
def mock_slack(mocker):
    mock = mocker.patch('aws.wrappers.slack_webhook.SlackWebhookWrapper')
    instance = mock.return_value
    instance.list_webhooks.return_value = []
    instance.create_webhook.return_value = (True, "Success")
    return mock

@pytest.fixture
def mock_textual_components(mocker):
    """Mock Rich UI components (legacy name kept for compatibility)"""
    mocker.patch('aws.misc.alarm_ui.AlarmConfigUI.run')
    mocker.patch('aws.misc.alarm_ui.AlarmTargetUI.run')
    return MagicMock()

@pytest.fixture
def mock_app_run(mocker):
    """Mock the UI run methods"""
    mocker.patch.object(AlarmConfigUI, 'run', return_value=None)
    mocker.patch.object(AlarmTargetUI, 'run', return_value=None)
    return None


@pytest.fixture
def mock_alarm_target_ui(mocker):
    """Mock AlarmTargetUI"""
    mock = mocker.patch('aws.misc.alarm_ui.AlarmTargetUI')
    mock_instance = mock.return_value
    mock_instance.target_config = {}
    mock_instance.run = MagicMock()
    return mock


@pytest.fixture
def mock_prompt(mocker):
    """Mock Rich Prompt with predefined responses"""
    mock = mocker.patch('rich.prompt.Prompt.ask')
    mock.side_effect = ["yes"]  # Default response for all prompts
    return mock

@pytest.fixture
def mock_app(mocker):
    """Mock UI classes"""
    mock_alarm = mocker.patch('aws.misc.alarm_ui.AlarmConfigUI')
    mock_alarm.return_value.run = MagicMock()
    mock_target = mocker.patch('aws.misc.alarm_ui.AlarmTargetUI')
    mock_target.return_value.run = MagicMock()
    return mock_alarm.return_value

@pytest.fixture
def mock_input_screens(mocker):
    """Mock Rich prompts used in alarm target UI"""
    mock_prompt = mocker.patch('aws.misc.alarm_ui.Prompt.ask')
    mock_prompt.side_effect = ["Email", "test@example.com"]
    return mock_prompt

@pytest.fixture
def mock_table(mocker):
    """Mock DataTable"""
    table = MagicMock()
    table.cursor_row = 0
    table.get_row_at.return_value = ["Email", "test@example.com", "Yes"]
    table.add_row = MagicMock()
    table.clear = MagicMock()
    return table



@pytest.fixture
def mock_alarm_ui(mocker):
    """Mock AlarmConfigUI"""
    mock = mocker.patch('aws.misc.alarm_ui.AlarmConfigUI')
    instance = mock.return_value
    instance.alarm_config = {
        'test_type': {'enabled': True, 'threshold': 5}
    }
    instance.run = MagicMock()
    return instance

@pytest.fixture
def mock_target_ui(mocker):
    """Mock AlarmTargetUI"""
    mock = mocker.patch('aws.misc.alarm_ui.AlarmTargetUI')
    instance = mock.return_value
    instance.target_config = {
        'test@example.com': {'type': 'Email', 'confirmed': True}
    }
    instance.run = MagicMock()
    return instance

@pytest.fixture
def mock_screens(mocker):
    """Mock Rich prompt interactions"""
    mocker.patch('aws.misc.alarm_ui.Prompt.ask', return_value="q")
    mocker.patch('aws.misc.alarm_ui.Confirm.ask', return_value=False)
    return mocker

@pytest.fixture
def mock_error_handler():
    with patch('aws.misc.error_handlings.error_handler') as mock:
        yield mock

@pytest.fixture
def mock_cli_output(mocker, mock_console, mock_display, mock_prompt, mock_get_recommendations, mock_get_recommendation_types):
    """Combine all CLI output related mocks"""
    return {
        'console': mock_console,
        'display': mock_display,
        'prompt': mock_prompt,
        'get_recs': mock_get_recommendations,
        'get_types': mock_get_recommendation_types
    }

@pytest.fixture
def mock_execution(mocker):
    """Mock execution functions"""
    return {'populate': mocker.patch('commons.execution.populate')}

@pytest.fixture
def mock_sfn(mocker):
    """Mock StateMachine class to prevent actual executions"""
    # Create a mock instance
    mock_instance = mocker.MagicMock()
    
    # Mock the populate method
    mock_instance.populate.return_value = "mock-execution-arn"
    
    # Mock the start method
    mock_instance.start.return_value = "mock-execution-arn"
    
    # Mock the wait_for_execution method
    mock_instance.wait_for_execution.return_value = "SUCCEEDED"
    
    # Mock the check_previous_execution method
    mock_instance.check_previous_execution.return_value = None
    
    # Mock the _generate_populate_input method
    mock_instance._generate_populate_input.return_value = {
        "PAYLOAD": [{
            "WORKFLOW": "POPULATE",
            "ACCOUNT_ID": "123456789012",
            "ACCOUNT_NAME": "Test Account",
            "REGION_NAME": ["us-east-1"],
            "RESOURCE_ACTIONS": ["EC2"]
        }]
    }

    # Mock the class constructor at both module levels
    mocker.patch('aws.wrappers.sfn.StateMachine', return_value=mock_instance)
    mocker.patch('commons.execution.StateMachine', return_value=mock_instance)
    
    return mock_instance

@pytest.fixture
def mock_get_recommendation_types(mocker):
    """Mock get_recommendation_types function"""
    mock = mocker.patch('commons.get.get_recommendation_types')
    mock.return_value = ['Idle Ec2 Instances', 'Unattached Volumes']
    return mock

@pytest.fixture
def mock_display_recommendation_types(mocker):
    """Mock display_recommendation_types function"""
    return mocker.patch('aws.misc.display.display_recommendation_types')

@pytest.fixture
def mock_organizations(mocker):
    """Mock Organizations class"""
    mock = mocker.patch('aws.wrappers.organizations.Organizations')
    instance = mock.return_value
    instance.is_account_delegated_admin_or_management.return_value = True
    instance.organization_trust_status_for_service.return_value = True
    return instance

@pytest.fixture
def mock_eventbridge(mocker):
    """Mock EventBridge class"""
    mock = mocker.patch('aws.wrappers.eventbridge.EventBridge')
    instance = mock.return_value
    instance.GetScheduleStatus.return_value = "ENABLED"
    instance.GetScheduleExpression.return_value = "rate(1 day)"
    instance.SetScheduleExpression.return_value = "rate(1 day)"
    return mock

@pytest.fixture
def mock_execution(mocker):
    """Mock execution functions"""
    mock_populate = mocker.patch('commons.execution.populate')
    mocker.patch('commons.execution.get_accounts_and_regions', return_value={
        '123456789012': {
            'account_name': 'Test Account',
            'regions': ['us-east-1', 'us-west-2']
        }
    })
    return {'populate': mock_populate}

@pytest.fixture
def mock_get_updatables(mocker):
    """Mock get_updatables function"""
    return mocker.patch('commons.get.get_updatables')

@pytest.fixture
def mock_prompt(mocker):
    """Mock Rich Prompt for user inputs"""
    mock = mocker.patch('rich.prompt.Prompt')
    mock.ask = mocker.MagicMock()  # Create a new MagicMock for the ask method
    return mock

@pytest.fixture
def mock_cli_output(mocker, mock_console, mock_display, mock_prompt):
    """Mock CLI output components"""
    return {
        'console': mock_console,
        'display': mock_display,
        'prompt': mock_prompt,
        'get_recs': mocker.patch('commons.get.get_recommendations'),
        'get_types': mocker.patch('commons.get.get_recommendation_types')
    }

@pytest.fixture
def mock_execution(mocker):
    """Mock execution functions"""
    return {'populate': mocker.patch('commons.execution.populate')}

@pytest.fixture
def mock_manual_instructions(mocker):
    """Mock manual instructions workflow"""
    mock = mocker.patch('aws.misc.display.display_manual_instructions_workflow')
    mock.return_value = ['123456789012', '987654321098']  # Default test account IDs
    return mock

@pytest.fixture
def mock_deploy_mode(mocker):
    """Mock DEPLOY_MODE global variable"""
    return mocker.patch('commons.globals.DEPLOY_MODE', 'manual')

@pytest.fixture
def mock_db_manager(mocker):
    """Mock DatabaseManager"""
    mock = mocker.patch('db.crud.DatabaseManager')
    instance = mock.return_value
    instance._account_ids = None
    instance.populate_accounts_and_regions = mocker.MagicMock()
    return mock
