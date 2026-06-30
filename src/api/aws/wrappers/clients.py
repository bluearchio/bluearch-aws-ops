import boto3
import os
from commons.globals import CloudFormationOutputs, CURRENT_REGION, ROLE_NAME
from utils.logger_config import log
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator
from utils.cache_manager import CLOUDFORMATION_CACHE, ASSUMED_ROLE_CACHE
from datetime import datetime, timezone
import json

class AWSClients:
    def __init__(self, account_ids: list, clients: list, global_clients: list, regions: list):
        self.region_name = CURRENT_REGION
        self.external_id = 'BlueArchAlertingEngineAPIExternalID'
        self.global_clients = self._initialize_global_cross_account_clients(account_ids, global_clients)
        self.clients = self.initialize_cross_account_clients(account_ids, clients, regions)
    
    @staticmethod
    def assumed_role_client(account_id, client, region=None):
        try:
            default_region = CURRENT_REGION
            target_region = region if region else default_region
            
            # Create a unique cache key for this combination
            cache_key = f"assumed_role_{account_id}_{client}_{target_region}"
            
            # Check if we have valid cached credentials
            cached_credentials = ASSUMED_ROLE_CACHE.get(cache_key)
            if cached_credentials:
                try:
                    # Parse the cached credentials
                    credentials = json.loads(cached_credentials)
                    
                    # Parse expiration with timezone awareness
                    expiration_str = credentials['Expiration']
                    # Handle both ISO format with and without timezone
                    if 'Z' in expiration_str or '+' in expiration_str:
                        # Already has timezone info
                        expiration = datetime.fromisoformat(expiration_str.replace('Z', '+00:00'))
                    else:
                        # No timezone info, assume UTC
                        expiration = datetime.fromisoformat(expiration_str).replace(tzinfo=timezone.utc)
                    
                    # Get current time with timezone awareness
                    now = datetime.now(timezone.utc)
                    
                    # Check if credentials are still valid (with some buffer time)
                    if now < expiration:
                        log.debug(f"Using cached credentials for {cache_key}")
                        session = boto3.Session(
                            aws_access_key_id=credentials['AccessKeyId'],
                            aws_secret_access_key=credentials['SecretAccessKey'],
                            aws_session_token=credentials['SessionToken']
                        )
                        
                        config = Config(retries={'max_attempts': 15, 'mode': 'standard'})
                        return session.client(client, region_name=target_region, config=config)
                except Exception as e:
                    log.debug(f"Error parsing cached credentials: {str(e)}")
                    # Continue to get new credentials
            
            # If we don't have valid cached credentials, get new ones
            sts_client = boto3.client('sts', region_name=region) if region else boto3.client('sts')
            
            # Get role name from cache or CloudFormation
            role_name = CLOUDFORMATION_CACHE.get('cfn_output_RoleName')
            if not role_name:
                cfn_outputs = CloudFormationOutputs()
                outputs = cfn_outputs.get_cfn_outputs(['RoleName'])
                role_name = outputs.get('RoleName', 'bluearch-alerting-engine-cli-role-manual')
                CLOUDFORMATION_CACHE.set('cfn_output_RoleName', role_name)
            
            assumed_role_object = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{account_id}:role/{role_name}',
                ExternalId='BlueArchAlertingEngineAPIExternalID',
                RoleSessionName='AssumeRoleSession'
            )
            
            # Cache the credentials
            credentials_to_cache = {
                'AccessKeyId': assumed_role_object['Credentials']['AccessKeyId'],
                'SecretAccessKey': assumed_role_object['Credentials']['SecretAccessKey'],
                'SessionToken': assumed_role_object['Credentials']['SessionToken'],
                'Expiration': assumed_role_object['Credentials']['Expiration'].isoformat()
            }
            ASSUMED_ROLE_CACHE.set(cache_key, json.dumps(credentials_to_cache))
            
            session = boto3.Session(
                aws_access_key_id=assumed_role_object['Credentials']['AccessKeyId'],
                aws_secret_access_key=assumed_role_object['Credentials']['SecretAccessKey'],
                aws_session_token=assumed_role_object['Credentials']['SessionToken']
            )

            config = Config(retries={'max_attempts': 15, 'mode': 'standard'})
            return session.client(client, region_name=target_region, config=config)
            
        except Exception as e:
            log.debug(f"Error at 'assumed_role_client' for account {account_id}: {str(e)}")
            config = Config(retries={'max_attempts': 15, 'mode': 'standard'})
            if region:
                return boto3.client(client, region_name=region, config=config)
            return boto3.client(client, region_name=default_region, config=config)
    
    def initialize_cross_account_clients(self, account_id: str, clients: list, regions: list):
        credentials_object = {}

        for region in regions:
            credentials_object[account_id] = credentials_object.get(account_id, {})
            credentials_object[account_id][region] = {}
            for client in clients:
                credentials_object[account_id][region][client] = self.assumed_role_client(account_id, client, region)
        log.debug(f"Initialized clients {clients} for account {account_id} in regions [{regions}]")
        return credentials_object

    
    def _initialize_global_cross_account_clients(self, account_id: str, global_clients: list):
        credentials_object = {}

        credentials_object[account_id] = credentials_object.get(account_id, {})
        for client in global_clients:
            credentials_object[account_id][client] = self.assumed_role_client(account_id, client, "us-east-1")
        log.debug(f"Initialized global clients {global_clients} for account {account_id}")
        return credentials_object

    @staticmethod
    def validate_manual_deployment_role_assumptions(account_ids: list) -> dict:
        def _validate_single_account(acc_id: str) -> tuple[str, bool]:
            try:
                sts_client = boto3.client('sts')
                response = sts_client.assume_role(
                    RoleArn=f'arn:aws:iam::{acc_id}:role/bluearch-alerting-engine-cli-role-manual',
                    ExternalId='BlueArchAlertingEngineAPIExternalID',
                    RoleSessionName='ValidateAssumeRole'
                )
                return acc_id, True
            except Exception as e:
                log.debug(f"Failed to assume role for account {acc_id}: {str(e)}")
                return acc_id, False

        with ThreadPoolExecutor(max_workers=min(10, len(account_ids))) as executor:
            future_to_account = {
                executor.submit(_validate_single_account, acc_id): acc_id 
                for acc_id in account_ids
            }
            
            for future in as_completed(future_to_account):
                yield future.result()