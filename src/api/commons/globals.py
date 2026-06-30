import boto3
from utils.logger_config import log
import os
from threading import Lock
from functools import wraps
from typing import Any, Callable, Optional, List, Dict
from utils.cache import SecureCache, cache_result
from utils.cache_manager import CLOUDFORMATION_CACHE

MARKETPLACE_PRODUCT_IDS = ["prod-edqdyirb7ve6m", "prod-njhtl2zyyzshc"]

# Initialize a single instance of SecureCache for CloudFormation outputs
cfn_cache = CLOUDFORMATION_CACHE
required_keys = [
    'Region', 'RoleName', 'AlarmTableName', 'AlarmTargetTableName',
    'StackSetID', 'AccountID', 'BucketName', 'Workspace',
    'StateMachineArn', 'AccTableName', 'RecTableName',
    'SecretArn', 'SlackWebhooksSecretArn', 'SchedulerState',
    'SchedulerExpression', 'TopicArn', 'SlackNotificationLambdaArn',
    'DeployMode'
]
def cfn_output_cache_key(output_key: str) -> str:
    return f"cfn_output_{output_key}"

def cache_cfn_output(output_keys: List[str]) -> Callable:
    """
    Decorator to cache multiple CloudFormation outputs.
    """
    return cache_result(cfn_cache, lambda *args, **kwargs: "_".join([cfn_output_cache_key(key) for key in output_keys]))

class CloudFormationOutputs:
    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(CloudFormationOutputs, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, stack_name: str = 'bluearch-alerting-engine-cli', region_name: str = 'us-east-1'):
        if self._initialized:
            return
        self.stack_name = stack_name if not os.getenv('BLUEARCH_DEBUG') else 'bluearch-alerting-engine-cli-dev'
        self.region_name = region_name
        self.client = boto3.client('cloudformation', region_name=self.region_name)
        self._initialized = True

    def get_cfn_outputs(self, output_keys: List[str]) -> Dict[str, Any]:
        """
        Fetch multiple CloudFormation outputs and cache them.
        """
        results = {}
        cache_keys = [cfn_output_cache_key(key) for key in output_keys]
        cached_values = cfn_cache.get_multiple_keys(cache_keys)

        missing_keys = []
        for key, cache_key in zip(output_keys, cache_keys):
            if cache_key in cached_values:
                results[key] = cached_values[cache_key]
            else:
                missing_keys.append(key)

        if missing_keys:
            try:
                response = self.client.describe_stacks(StackName=self.stack_name)
                outputs = {output['OutputKey']: output['OutputValue'] for output in response['Stacks'][0].get('Outputs', [])}
                log.debug(f"Fetched Outputs from CloudFormation: {outputs}")

                # Update cache with fetched outputs
                for key, value in outputs.items():
                    cache_key = cfn_output_cache_key(key)
                    cfn_cache.set(cache_key, value)
                    if key in missing_keys:
                        results[key] = value
            except Exception as e:
                log.debug(f"Failed to fetch CloudFormation outputs: {str(e)}")

        return results

    # def get_cfn_output(self, output_key: str) -> Optional[Any]:
    #     # Attempt to retrieve from cache
    #     cached_value = cfn_cache.get(cfn_output_cache_key(output_key))
    #     if cached_value is not None:
    #         return cached_value

    #     # If not in cache, fetch from CloudFormation
    #     try:
    #         response = self.client.describe_stacks(StackName=self.stack_name)
    #         outputs = {output['OutputKey']: output['OutputValue'] for output in response['Stacks'][0].get('Outputs', [])}
    #         log.debug(f"Fetched Outputs from CloudFormation: {outputs}")

    #         # Update cache with all fetched outputs
    #         for key, value in outputs.items():
    #             cfn_cache.set(cfn_output_cache_key(key), value)

    #         return outputs.get(output_key)
    #     except Exception as e:
    #         log.debug(f"CloudFormationOutputs ERROR - {output_key}: {str(e)}")
    #         return None

    @property
    def all_outputs(self) -> Dict[str, Any]:
        """
        Fetch all required CloudFormation outputs at once.
        """

        return self.get_cfn_outputs(required_keys)

# Initialize the CloudFormationOutputs instance
cfn_outputs = CloudFormationOutputs()

all_cfn_outputs = cfn_outputs.all_outputs
def get_global_output(output_key: str) -> Optional[Any]:
    if not hasattr(cfn_outputs, '_all_outputs_fetched'):
        # cfn_outputs.get_cfn_outputs(required_keys)
        cfn_outputs._all_outputs_fetched = True
    return all_cfn_outputs.get(output_key)

# Assign to global variables
CURRENT_REGION = get_global_output('Region')
ALARM_CONFIG_TABLE_NAME = get_global_output('AlarmTableName')
ALARM_TARGETS_TABLE_NAME = get_global_output('AlarmTargetTableName')
STACKSET_ID = get_global_output('StackSetID')
ACCOUNT_ID = get_global_output('AccountID')
BUCKET_NAME = get_global_output('BucketName')
WORKSPACE = get_global_output('Workspace')
STATE_MACHINE_ARN = get_global_output('StateMachineArn')
ACC_TABLE_NAME = get_global_output('AccTableName')
REC_TABLE_NAME = get_global_output('RecTableName')
SECRET_ARN = get_global_output('SecretArn')
SLACK_WEBHOOKS_SECRET_ARN = get_global_output('SlackWebhooksSecretArn')
SCHEDULER_EXPRESSION = get_global_output('SchedulerExpression')
SCHEDULER_STATE = get_global_output('SchedulerState')
TOPIC_ARN = get_global_output('TopicArn')
SLACK_NOTIFICATION_LAMBDA_ARN = get_global_output('SlackNotificationLambdaArn')
DEPLOY_MODE = get_global_output('DeployMode')
ROLE_NAME = get_global_output('RoleName')