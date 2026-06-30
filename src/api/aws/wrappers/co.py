from utils.logger_config import log
from aws.wrappers.awsbase import AWSBase
from aws.wrappers.organizations import Organizations
from rich.prompt import Prompt
from rich.console import Console

console = Console()

class ComputeOptimizer(AWSBase):
    def __init__(self):
        super().__init__('compute-optimizer')
        self.org = Organizations()

    def get_enrollment_status(self) -> tuple[dict, bool]:
        try:
            response = self.client.get_enrollment_status()
            if 'ResponseMetadata' in response:
                del response['ResponseMetadata']
            if response['memberAccountsEnrolled'] == True:
                return response, True
            return response, False
        except (self.client.exceptions.MissingAuthenticationToken,
                self.client.exceptions.AccessDeniedException) as e:
            log.debug(f"Error getting enrollment status: {e}")
            return None, False
    
    def get_enrollment_statuses_for_organization(self) -> dict:
        try:
            all_statuses = []
            next_token = None
            while True:
                if next_token:
                    response = self.client.get_enrollment_statuses_for_organization(nextToken=next_token)
                else:
                    response = self.client.get_enrollment_statuses_for_organization()

                if 'accountEnrollmentStatuses' in response:
                    all_statuses.extend(response['accountEnrollmentStatuses'])

                if 'nextToken' in response:
                    next_token = response['nextToken']
                else:
                    break
            return {'accountEnrollmentStatuses': all_statuses}
        except (self.client.exceptions.MissingAuthenticationToken,
                self.client.exceptions.AccessDeniedException) as e:
            log.debug(f"Error getting enrollment statuses for organization: {e}")
            return {}

    def check_compute_optimizer_trust_status(self) -> bool:
        return self.org.organization_trust_status_for_service('compute-optimizer.amazonaws.com')
    
    def update_enrollment_status(self, optin_organization: bool = False, status: str = 'Active') -> dict:
        try:
            enrollment_response = self.client.update_enrollment_status(
                status=status,
                includeMemberAccounts=optin_organization
            )
            return enrollment_response
        except (self.client.exceptions.MissingAuthenticationToken,
                self.client.exceptions.AccessDeniedException) as e:
            log.debug(f"Error updating enrollment status: {e}")
            return {}

    def _handle_compute_optimizer_for_organization(self, org: Organizations):
        co_trust_status = self.check_compute_optimizer_trust_status()
        if not co_trust_status:
            if not Prompt.ask("[blue]Do you want BlueArch to enable the Compute Optimizer Service Access to your organization?[/blue]", choices=["yes", "no"], default="no") == "yes":
                console.print("[red]Compute Optimizer Service Access will not be enabled for your organization.[/red]")
                return
            
            org.enable_organization_service_access('compute-optimizer.amazonaws.com')
            console.print("[green]Compute Optimizer Service Access enabled for your organization.[/green]")
        
        self.update_enrollment_status(optin_organization=True)
        console.print("[green]Compute Optimizer enabled for all accounts in your organization.[/green]")
            
    def handle_compute_optimizer_activation(self, org: Organizations):
        is_management_account = org.is_account_delegated_admin_or_management()
        status, is_members_enrolled = self.get_enrollment_status()
        if status['status'] == 'Active' and is_members_enrolled:
            return
        
        if status['status'] == 'Active' and is_management_account and not is_members_enrolled:
            if Prompt.ask("[blue]We checked you have compute optimizer enabled and you are the management account of an organization. Do you want BlueArch to enable the Compute Optimizer for all your organization accounts?[/blue]", choices=["yes", "no"], default="no") == "yes":
                self._handle_compute_optimizer_for_organization(org)
                return

        if status['status'] == 'Inactive':
            if Prompt.ask("[blue]Do you want to enable the Compute Optimizer?[/blue]", choices=["yes", "no"], default="no") == "yes":
                if is_management_account:
                    self._handle_compute_optimizer_for_organization(org)
                    return

                self.update_enrollment_status(optin_organization=False)
                console.print("[green]Compute Optimizer enabled for your account.[/green]")