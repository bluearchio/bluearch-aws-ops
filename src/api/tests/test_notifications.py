import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_cloudwatch():
    with patch('aws.wrappers.cloudwatch.CloudWatchWrapper') as mock:
        instance = mock.return_value
        instance.get_alarms.return_value = [{
            'AlarmName': 'bluearch_test_type_alarm',
            'Threshold': 5,
            'ActionsEnabled': True
        }]
        instance.create_alarm.return_value = True
        yield instance

@pytest.fixture
def mock_sns():
    with patch('aws.wrappers.sns.SnsWrapper') as mock:
        instance = mock.return_value
        instance.list_subscriptions.return_value = [{
            'Protocol': 'email',
            'Endpoint': 'test@example.com',
            'SubscriptionArn': 'arn:aws:sns:test'
        }]
        instance.create_subscription.return_value = 'arn:aws:sns:new-subscription'
        instance.delete_subscription.return_value = 'deleted'
        yield instance

@pytest.fixture
def mock_slack():
    with patch('aws.wrappers.slack_webhook.SlackWebhookWrapper') as mock:
        instance = mock.return_value
        instance.validate_webhook_url.return_value = True
        instance.test_webhook.return_value = True
        instance.create_webhook.return_value = (True, "Success")
        instance.list_webhooks.return_value = ["https://hooks.slack.com/test"]
        yield instance

class TestNotifications:
    def test_alarm_command_success(self, mock_cloudwatch):
        """Test alarm command with successful configuration"""
        from cli.notifications import alarm
        
        with patch('aws.misc.alarm_ui.configure_alarms', return_value=True) as mock_configure:
            result = alarm(config_targets=False)
            
        mock_configure.assert_called_once()

    def test_alarm_command_failure(self, mock_cloudwatch):
        """Test alarm command with failed configuration"""
        from cli.notifications import alarm
        
        with patch('aws.misc.alarm_ui.configure_alarms', return_value=False) as mock_configure:
            result = alarm(config_targets=False)
            
        mock_configure.assert_called_once()

    def test_alarm_command_with_targets_success(self, mock_sns, mock_slack):
        """Test alarm command with successful target configuration"""
        from cli.notifications import alarm
        
        with patch('aws.misc.alarm_ui.configure_targets', return_value=True) as mock_configure:
            result = alarm(config_targets=True)
            
        mock_configure.assert_called_once()

    def test_alarm_command_with_targets_failure(self, mock_sns, mock_slack):
        """Test alarm command with failed target configuration"""
        from cli.notifications import alarm
        
        with patch('aws.misc.alarm_ui.configure_targets', return_value=False) as mock_configure:
            result = alarm(config_targets=True)
            
        mock_configure.assert_called_once()

    def test_error_handling(self, mock_sns, mock_error_handler):
        """Test error handling functionality"""
        from cli.notifications import alarm

        with patch('aws.misc.alarm_ui.configure_targets', side_effect=Exception("Test error")):
            mock_error_handler.handle_error.side_effect = SystemExit(1)
            with pytest.raises(SystemExit):
                alarm(config_targets=True)
            
            mock_error_handler.handle_error.assert_called_once()

    