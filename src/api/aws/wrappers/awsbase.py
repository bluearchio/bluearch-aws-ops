import boto3
from aws.wrappers.clients import AWSClients
from utils.logger_config import log

class AWSBase:
    def __init__(self, service_name: str):
        try:
            from commons.globals import ACCOUNT_ID
            self.account_id=ACCOUNT_ID
        except Exception as e:
            log.debug(f"Error getting account ID: {e}")
            self.account_id = boto3.client('sts').get_caller_identity()['Account']
        self._service_name = service_name
        self._client = None
    
    @property
    def client(self):
        if self._client is None:
            self._client = AWSClients.assumed_role_client(self.account_id, self._service_name, 'us-east-1')
        return self._client
