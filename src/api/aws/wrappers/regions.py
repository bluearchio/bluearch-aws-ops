import boto3
import os
from .clients import AWSClients
from utils.logger_config import log
from commons.globals import CloudFormationOutputs, CURRENT_REGION
from utils.cache_manager import CLOUDFORMATION_CACHE

class EC2Regions:
    """
    calls the ec2 get enabled regions from the aws sdk given the account list that is passed into the instance
    """
    def __init__(self, account_ids):
        self.account_ids = account_ids
        self.current_region = CURRENT_REGION or 'us-east-1'
        
        # Get role name from cache or CloudFormation
        self.role_name = CLOUDFORMATION_CACHE.get('cfn_output_RoleName')
        if not self.role_name:
            cfn_outputs = CloudFormationOutputs()
            outputs = cfn_outputs.get_cfn_outputs(['RoleName'])
            self.role_name = outputs.get('RoleName', 'bluearch-alerting-engine-cli-role-manual')
            CLOUDFORMATION_CACHE.set('cfn_output_RoleName', self.role_name)

    def get_enabled_regions_per_accounts(self):
        """
        gets the enabled regions for the account
        """
        regions_per_account = {}
        for account_id in self.account_ids:
            try:
                client = AWSClients.assumed_role_client(account_id, 'ec2', self.current_region)
                response = client.describe_regions()
                regions_per_account[account_id] = [region['RegionName'] for region in response['Regions']]
            except Exception as e:
                log.error(f"Failed to get regions for account {account_id}: {str(e)}")
                # Use current region as fallback
                regions_per_account[account_id] = [self.current_region]
        return regions_per_account