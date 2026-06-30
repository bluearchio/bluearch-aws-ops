import pytest
from unittest.mock import MagicMock, patch
from bluearch import cli_app

@pytest.fixture
def mock_sfn_client():
    with patch('aws.wrappers.sfn.StateMachine') as mock:
        instance = mock.return_value
        instance.check_previous_execution.return_value = {
            'status': 'SUCCEEDED',
            'input': '{"test": "data"}'
        }
        instance.start.return_value = "arn:aws:states:us-east-1:123456789012:execution:test"
        yield instance

@pytest.fixture
def mock_eventbridge(mocker):
    """Mock EventBridge client"""
    mock = mocker.patch('aws.wrappers.eventbridge.EventBridge')
    mock_instance = mock.return_value
    
    # Mock CloudFormation client
    mock_instance.cloudformation = mocker.MagicMock()
    mock_instance.cloudformation.client = mocker.MagicMock()
    mock_instance.cloudformation.stack_name = "test-stack"
    mock_instance.cloudformation.client.describe_stacks.return_value = {
        'Stacks': [{
            'Parameters': [{'ParameterKey': 'SchedulerExpression', 'ParameterValue': 'rate(7 days)'}]
        }]
    }
    mock_instance.cloudformation.client.update_stack.return_value = {"StackId": "test-stack"}
    mock_instance.cloudformation.client.get_waiter.return_value.wait.return_value = None
    
    # Mock EventBridge methods
    mock_instance.GetScheduleStatus.return_value = "ENABLED"
    mock_instance.GetScheduleExpression.return_value = "rate(7 days)"
    mock_instance.ValidateScheduleExpression.return_value = (True, "1 day")
    mock_instance.rule_name = "test-rule"
    mock_instance.SetScheduleExpression.return_value = "rate(1 day)"
    
    return mock

@pytest.fixture
def mock_organizations():
    with patch('aws.wrappers.organizations.Organizations') as mock:
        instance = mock.return_value
        instance.client.describe_account.return_value = {
            'Account': {'Name': 'Test Account'}
        }
        instance.is_account_delegated_admin_or_management.return_value = True
        yield instance

@pytest.fixture
def mock_config_manager():
    instance = MagicMock()
    instance.get_event_hook_config.return_value = {
        "data_collected": {
            "cli_version": True,
            "command_used": True
        }
    }
    yield instance

@pytest.fixture
def mock_sfn(mocker):
    """Mock StateMachine client"""
    mock = mocker.patch('aws.wrappers.sfn.StateMachine')
    mock_instance = mock.return_value
    mock_instance.check_previous_execution.return_value = True
    return mock

@pytest.fixture
def mock_error_handler(mocker):
    """Mock error handler"""
    mock = mocker.patch('aws.misc.error_handlings.error_handler')
    return mock

class TestRecommendations:
    def test_show_recommendations_with_data(self, runner, mock_get_recommendations, mock_display_recommendations):
        """Test showing recommendations when data exists"""
        recommendations = {
            ('123456789012', 'TestAccount'): {
                'us-east-1': {
                    'test_type': [{'id': 'test'}]
                }
            }
        }
        mock_get_recommendations.return_value = recommendations
        
        result = runner.invoke(cli_app, ["show-recommendations"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_get_recommendations.assert_called_once_with(
            account_id=None,
            region=None,
            recommendation_type=None
        )
        mock_display_recommendations.assert_called_once_with(recommendations)

    # def test_populate_command(
    #     self,
    #     runner,
    #     mock_cli_output,
    #     mock_sfn,
    #     mock_execution,
    #     mock_get_accounts_and_regions
    # ):
    #     """Test populate command execution"""
    #     # Set up mock responses
    #     mock_cli_output['prompt'].ask.return_value = "yes"
    #     mock_cli_output['console'].return_value.print.return_value = None
    #     mock_get_accounts_and_regions.return_value = {'123456789012': ['us-east-1']}
        
    #     result = runner.invoke(cli_app, ["populate"], prog_name="bluearch")
        
    #     assert result.exit_code == 0
    #     mock_execution['populate'].assert_called_once()
    #     mock_cli_output['console'].return_value.print.assert_any_call(
    #         "[green]Accounts and regions table refreshed successfully.[/green]"
    #     )

    def test_populate_command_aborted(
        self,
        runner,
        mock_cli_output,
        mock_sfn,
        mock_execution,
        mock_get_accounts_and_regions
    ):
        """Test populate command when user aborts"""
        mock_cli_output['prompt'].ask.return_value = "no"
        mock_cli_output['console'].return_value.print.return_value = None
        
        result = runner.invoke(cli_app, ["populate"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_cli_output['console'].return_value.print.assert_called_with("Population aborted.")
        mock_execution['populate'].assert_not_called()


    # def test_populate_with_scheduler(
    #     self,
    #     runner,
    #     mock_cli_output,
    #     mock_sfn,
    #     mock_eventbridge,
    #     mock_organizations,
    #     mock_config_manager,
    #     mock_get_accounts_and_regions,
    #     mock_execution,
    #     mocker
    # ):
    #     """Test populate command with scheduler enabled"""
    #     # Mock AWS clients
    #     mock_sts = mocker.patch('boto3.client')
    #     mock_sts.return_value.assume_role.return_value = {
    #         'Credentials': {
    #             'AccessKeyId': 'test',
    #             'SecretAccessKey': 'test',
    #             'SessionToken': 'test'
    #         }
    #     }

    #     # Mock DB operations
    #     mock_db = mocker.patch('db.crud.DatabaseManager')
    #     mock_db_instance = mock_db.return_value
    #     mock_db_instance.populate_accounts_and_regions.return_value = None

    #     # Set up mock responses
    #     mock_cli_output['prompt'].ask.side_effect = [
    #         "yes",  # Proceed with population
    #         "yes",  # Enable scheduler
    #         "1 day" # Scheduler rate
    #     ]
        
    #     mock_eventbridge.return_value.GetScheduleStatus.return_value = "DISABLED"
    #     mock_eventbridge.return_value.ValidateScheduleExpression.return_value = (True, "1 day")
        
    #     mock_get_accounts_and_regions.return_value = {
    #         '123456789012': {
    #             'account_name': 'TestAccount',
    #             'regions': ['us-east-1']
    #         }
    #     }

    #     # Execute command
    #     result = runner.invoke(
    #         cli_app,
    #         ["populate"],
    #         input="yes\nyes\n1 day\n",
    #         prog_name="bluearch",
    #         catch_exceptions=False
    #     )

    #     # Verify results
    #     assert result.exit_code == 0
    #     mock_execution['populate'].assert_called_once()
    #     mock_eventbridge.return_value.SetScheduleExpression.assert_called_once_with("1 day", "ENABLED")
    #     mock_db_instance.populate_accounts_and_regions.assert_called_once()

    def test_scheduler_get_status(self, runner, mock_eventbridge):
        """Test getting scheduler status"""
        mock_eventbridge.return_value.GetScheduleStatus.return_value = "ENABLED"
        
        result = runner.invoke(cli_app, ["scheduler", "--get"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_eventbridge.return_value.GetScheduleStatus.assert_called_once()

    def test_scheduler_disable(self, runner, mock_prompt, mock_eventbridge, mock_sfn):
        """Test disabling scheduler"""
        mock_prompt.ask.return_value = "yes"
        mock_eventbridge.return_value.GetScheduleStatus.return_value = "ENABLED"
        mock_sfn.return_value.check_previous_execution.return_value = True
        
        result = runner.invoke(cli_app, ["scheduler", "--disable"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_eventbridge.return_value.SetScheduleExpression.assert_called_once()

    def test_scheduler_invalid_expression(self, runner, mock_prompt, mock_eventbridge, mock_sfn):
        """Test scheduler with invalid expression"""
        mock_prompt.ask.side_effect = ["invalid", "1 day"]  # First invalid, then valid expression
        mock_eventbridge.return_value.ValidateScheduleExpression.side_effect = [
            (False, "Invalid expression"),  # First call fails
            (True, "1 day")  # Second call succeeds
        ]
        mock_sfn.return_value.check_previous_execution.return_value = True

        result = runner.invoke(cli_app, ["scheduler"], prog_name="bluearch")

        assert result.exit_code == 0
        mock_eventbridge.return_value.SetScheduleExpression.assert_called_once_with("1 day", "ENABLED")

    def test_show_recommendation_types(self, runner, mock_get_recommendation_types, mock_display_recommendation_types):
        """Test showing recommendation types"""
        types = ["type1", "type2"]
        mock_get_recommendation_types.return_value = types
        
        result = runner.invoke(cli_app, ["show-recommendation-types"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_get_recommendation_types.assert_called_once()
        mock_display_recommendation_types.assert_called_once_with(types)

    def test_populate_command_with_scheduler(
        self,
        runner,
        mock_cli_output,
        mock_sfn,
        mock_execution,
        mock_get_accounts_and_regions,
        mock_eventbridge
    ):
        """Test populate command with scheduler enabled"""
        # Set up mock responses
        mock_cli_output['prompt'].ask.side_effect = [
            "yes",  # Proceed with population
            "yes",  # Enable scheduler
            "1 day" # Scheduler rate
        ]
        
        mock_eventbridge.return_value.GetScheduleStatus.return_value = "DISABLED"
        mock_eventbridge.return_value.ValidateScheduleExpression.return_value = (True, "1 day")
        
        mock_get_accounts_and_regions.return_value = {
            '123456789012': {
                'account_name': 'TestAccount',
                'regions': ['us-east-1']
            }
        }
        
        result = runner.invoke(cli_app, ["populate"], prog_name="bluearch")
        
        assert result.exit_code == 0
        mock_execution['populate'].assert_called_once()
        mock_eventbridge.return_value.SetScheduleExpression.assert_called_once_with("1 day", "ENABLED")
