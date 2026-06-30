from aws.wrappers.awsbase import AWSBase
from botocore.exceptions import ClientError
from utils.logger_config import log
from typing import List, Dict
from commons.globals import SLACK_NOTIFICATION_LAMBDA_ARN, TOPIC_ARN
class CloudWatchWrapper(AWSBase):
    def __init__(self):
        super().__init__('cloudwatch')

    def create_alarm(self, alarm_name: str, alarm_enabled: bool, alarm_threshold: int):
        try:
            alarm_actions = [TOPIC_ARN]
            slack_lambda_arn = SLACK_NOTIFICATION_LAMBDA_ARN
            if slack_lambda_arn:
                alarm_actions.append(slack_lambda_arn)

            self.client.put_metric_alarm(
                AlarmName=alarm_name,
                AlarmDescription=f"This alarm is triggered when the number of {alarm_name} recommendations is greater than or equal to {alarm_threshold}",
                ActionsEnabled=alarm_enabled,
                AlarmActions=alarm_actions,
                MetricName=f"Number of {alarm_name} recommendations",
                Statistic="Sum",
                EvaluationPeriods=1,
                Period=10,
                Threshold=alarm_threshold,
                Namespace="BlueArch/Recommendations",
                Unit="Count",
                ComparisonOperator='GreaterThanOrEqualToThreshold',
                TreatMissingData='notBreaching',
                Tags=[
                    {
                        'Key': 'BlueArchAlarm',
                        'Value': 'true'
                    }
                ]
            )
            # log.debug(f"Alarm {alarm_name} created successfully")
        except ClientError as e:
            log.error(f"Error creating alarm: {e}")

    def get_alarms(self, alarm_name_prefix: str = 'bluearch_') -> List[Dict]:
        try:
            response = self.client.describe_alarms(AlarmNamePrefix=alarm_name_prefix)
            return response['MetricAlarms']
        except ClientError as e:
            log.error(f"Error getting alarm: {e}")
            return []
