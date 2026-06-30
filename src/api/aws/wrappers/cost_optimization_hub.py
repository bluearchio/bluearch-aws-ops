from rich.console import Console

from utils.logger_config import log
from aws.wrappers.awsbase import AWSBase
from aws.wrappers.organizations import Organizations

console = Console()
class CostOptimizationHub(AWSBase):
    def __init__(self):
        super().__init__('cost-optimization-hub')
        self.org = Organizations()

    def get_enrollment_statuses(self, account_id: str = None) -> dict:
        try:
            response = self.client.list_enrollment_statuses(account_id=account_id) if account_id else self.client.list_enrollment_statuses()
            return response
        except (self.client.MissingAuthenticationToken, self.client.AccessDeniedException) as e:
            log.debug(f"Error getting enrollment status: {e}")
            return None
    
    def check_cost_optimization_hub_trust_status(self) -> bool:
        return self.org.organization_trust_status_for_service('cost-optimization-hub.amazonaws.com')
    
    def update_enrollment_status(self, optin_organization: bool = False, status: str = 'Active') -> dict:
        try:
            enrollment_response = self.client.update_enrollment_status(
                status=status,
                includeMemberAccounts=optin_organization
            )
            return enrollment_response
        except (self.client.MissingAuthenticationToken, self.client.AccessDeniedException) as e:
            log.debug(f"Error updating enrollment status: {e}")
            return {}