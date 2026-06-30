from aws.wrappers.awsbase import AWSBase
from botocore.exceptions import ClientError
from utils.logger_config import log
from commons.globals import TOPIC_ARN
from typing import List, Dict

class SnsWrapper(AWSBase):
    def __init__(self):
        super().__init__('sns')
        self.topic_arn = TOPIC_ARN

    def create_subscription(self, protocol: str, endpoint: str) -> str:
        try:
            existing_subscriptions = self.list_subscriptions()
            for sub in existing_subscriptions:
                if sub['Protocol'] == protocol and sub['Endpoint'] == endpoint:
                    if sub['SubscriptionArn'] != 'PendingConfirmation':
                        log.debug(f"Subscription already exists and is confirmed for {endpoint}")
                        return sub['SubscriptionArn']
                    else:
                        log.debug(f"Subscription exists but is pending confirmation for {endpoint}")
                        return None

            response = self.client.subscribe(
                TopicArn=self.topic_arn,
                Protocol=protocol,
                Endpoint=endpoint
            )
            log.debug(f"New subscription created for {endpoint}")
            return response['SubscriptionArn']
        except ClientError as e:
            log.error(f"Error creating subscription: {e}")
            return None

    def list_subscriptions(self) -> List[Dict]:
        try:
            response = self.client.list_subscriptions_by_topic(TopicArn=self.topic_arn)
            return response['Subscriptions']
        except ClientError as e:
            log.error(f"Error listing subscriptions: {e}")
            return []

    def delete_subscription(self, endpoint: str):
        try:
            subscriptions = self.list_subscriptions()
            for sub in subscriptions:
                if sub['Endpoint'] == endpoint:
                    if sub['SubscriptionArn'] != 'PendingConfirmation':
                        self.client.unsubscribe(SubscriptionArn=sub['SubscriptionArn'])
                        log.debug(f"Subscription for endpoint {endpoint} deleted successfully")
                        return 'deleted'
                    else:
                        log.debug(f"Subscription for endpoint {endpoint} was pending confirmation and has been removed")
                        return 'pending'
            log.debug(f"No subscription found for endpoint {endpoint}")
            return 'not_found'
        except ClientError as e:
            log.error(f"Error deleting subscription: {e}")
            return 'error'