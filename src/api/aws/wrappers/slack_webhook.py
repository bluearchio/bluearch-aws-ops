import requests
import json
import re
import time
from typing import List
from aws.wrappers.auth import SlackSecretsWrapper

class SlackWebhookWrapper:
    def __init__(self):
        self.slack_secrets = SlackSecretsWrapper()

    def create_webhook(self, webhook_url: str) -> tuple[bool, str]:
        if not self.validate_webhook_url(webhook_url):
            return False, "Invalid webhook URL format"
        if self.test_webhook(webhook_url):
            if self.slack_secrets.store_slack_webhook(webhook_url):
                return True, "Webhook added successfully"
            else:
                return False, "Failed to store webhook"
        return False, "Failed to test webhook"

    def list_webhooks(self) -> List[str]:
        return self.slack_secrets.get_slack_webhooks()

    def delete_webhook(self, webhook_url: str) -> bool:
        return self.slack_secrets.delete_slack_webhook(webhook_url)

    def test_webhook(self, webhook_url: str) -> bool:
        current_time = int(time.time())
        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "BlueArch Test Message",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Hello! This is a test message from *BlueArch CLI*. :wave:"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*Status:*\nTest Successful"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Time:*\n<!date^{current_time}^{{date_num}} {{time_secs}}|{time.ctime(current_time)}>"
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "If you received this message, your Slack webhook is configured correctly."
                        }
                    ]
                }
            ]
        }

        try:
            response = requests.post(
                webhook_url,
                data=json.dumps(message),
                headers={'Content-Type': 'application/json'}
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    @staticmethod
    def validate_webhook_url(webhook_url: str) -> bool:
        if webhook_url is None:
            return False
        pattern = r'^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9%]+$'
        return re.match(pattern, webhook_url) is not None
