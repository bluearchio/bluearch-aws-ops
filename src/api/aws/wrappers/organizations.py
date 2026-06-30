import boto3
from utils.logger_config import log
from aws.wrappers.awsbase import AWSBase

class Organizations(AWSBase):
    def __init__(self):
        super().__init__('organizations')
        self.current_account_id = boto3.client('sts').get_caller_identity()['Account']

    def is_account_delegated_admin_or_management(self):
        try:
            delegated_admins = self.client.list_delegated_administrators()

            is_delegated_admin = any(admin["Id"] == self.current_account_id for admin in delegated_admins.get("DelegatedAdministrators", []))
        except Exception as e:
            if "AccessDeniedException" in str(e):
                return False
            else:
                raise e

        try:
            organization = self.client.describe_organization()["Organization"]
            is_management_account = organization["MasterAccountId"] == self.current_account_id
        except self.client.exceptions.AWSOrganizationsNotInUseException:
            is_management_account = False

        result = is_delegated_admin or is_management_account
        return result
    
    def organization_trust_status_for_service(self, service_principal: str) -> bool:
        response = self.client.list_aws_service_access_for_organization()
        return any(service['ServicePrincipal'] == service_principal for service in response.get("EnabledServicePrincipals", []))
    
    def enable_organization_service_access(self, service_principal: str) -> bool: # TODO: Strongly recommend to enable a service through the console
        try:
            self.client.enable_aws_service_access(ServicePrincipal=service_principal)
            log.debug(f"Enabled organization service access for {service_principal}")
            return True
        except (self.client.exceptions.AWSOrganizationsNotInUseException,
                self.client.exceptions.AccessDeniedException,
                self.client.exceptions.ServiceException,
                self.client.exceptions.InvalidInputException) as e:
            log.debug(f"Error enabling organization service access for {service_principal}: {e}")
            return False
        
    def disable_organization_service_access(self, service_principal: str) -> bool:
        try:
            self.client.disable_aws_service_access(ServicePrincipal=service_principal)
            log.debug(f"Disabled organization service access for {service_principal}")
            return True
        except (self.client.exceptions.AWSOrganizationsNotInUseException,
                self.client.exceptions.AccessDeniedException,
                self.client.exceptions.ServiceException,
                self.client.exceptions.InvalidInputException) as e:
            log.debug(f"Error disabling organization service access for {service_principal}: {e}")
            return False
