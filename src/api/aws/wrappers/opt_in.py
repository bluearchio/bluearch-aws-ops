from commons import get
from utils.logger_config import log
from aws.wrappers.organizations import Organizations
from aws.wrappers.clients import AWSClients
from aws.wrappers.co import ComputeOptimizer
from aws.wrappers.cost_optimization_hub import CostOptimizationHub
from rich.console import Console

console = Console()
org = Organizations()

aws_organizations_integrated_services = {
    "Amazon Detective": ("detective.amazonaws.com", "NotSupported"), 
    "Amazon DevOps Guru": ("devops-guru.amazonaws.com", "NotSupported"),
    "Amazon GuardDuty": ("guardduty.amazonaws.com", "NotSupported"),
    "Amazon Inspector": ("inspector2.amazonaws.com", "NotSupported"),
    "Amazon Macie": ("macie.amazonaws.com", "NotSupported"),
    "Amazon Security Lake": ("securitylake.amazonaws.com", "NotSupported"),
    "Amazon VPC IP Address Manager": ("ipam.amazonaws.com", "NotSupported"),
    "Artifact": ("artifact.amazonaws.com", "NotSupported"),
    "AWS Account Management": ("account.amazonaws.com", "NotSupported"),
    "AWS Application Migration Service": ("mgn.amazonaws.com", "NotSupported"),
    "AWS Audit Manager": ("auditmanager.amazonaws.com", "NotSupported"),
    "AWS Backup": ("backup.amazonaws.com", "NotSupported"),
    "AWS Control Tower": ("controltower.amazonaws.com", "NotSupported"),
    "AWS Health": ("health.amazonaws.com", "NotSupported"),
    "AWS IAM Identity Center (AWS Single Sign-On)": ("sso.amazonaws.com", "NotSupported"),
    "AWS License Manager - Linux Subscriptions": ("license-manager-linux-subscriptions.amazonaws.com", "NotSupported"),
    "AWS Marketplace - License Management": ("license-management.marketplace.amazonaws.com", "NotSupported"),
    "AWS Marketplace Private Marketplace": ("private-marketplace.marketplace.amazonaws.com", "NotSupported"),
    "AWS Network Manager": ("networkmanager.amazonaws.com", "NotSupported"),
    "AWS Resource Explorer": ("resource-explorer-2.amazonaws.com", "NotSupported"),
    "AWS Trusted Advisor": ("trustedadvisor.amazonaws.com", "NotSupported"),
    "CloudFormation StackSets": ("stacksets.cloudformation.amazonaws.com", "NotSupported"),
    "CloudTrail": ("cloudtrail.amazonaws.com", "NotSupported"),
    "Compute Optimizer": ("compute-optimizer.amazonaws.com", "Supported"),
    "Config": ("config.amazonaws.com", "NotSupported"),
    "Cost Optimization Hub": ("cost-optimization-hub.bcm.amazonaws.com", "Supported"),
    "Directory Service": ("ds.amazonaws.com", "NotSupported"),
    "Firewall Manager": ("fms.amazonaws.com", "NotSupported"),
    "IAM Access Analyzer": ("access-analyzer.amazonaws.com", "NotSupported"),
    "License Manager": ("license-manager.amazonaws.com", "NotSupported"),
    "RAM": ("ram.amazonaws.com", "NotSupported"),
    "S3 Storage Lens": ("storage-lens.s3.amazonaws.com", "NotSupported"),
    "Security Hub": ("securityhub.amazonaws.com", "NotSupported"),
    "Service Catalog": ("servicecatalog.amazonaws.com", "NotSupported"),
    "Service Quotas": ("servicequotas.amazonaws.com", "NotSupported"),
    "Systems Manager": ("ssm.amazonaws.com", "NotSupported"),
    "Tag Policies": ("tagpolicies.tag.amazonaws.com", "NotSupported"),
    "VPC Reachability Analyzer": ("reachabilityanalyzer.networkinsights.amazonaws.com", "NotSupported"),
}

def check_aws_organizations_integrated_services() -> dict:
    service_status = {}
    for service, (service_principal, support_status) in aws_organizations_integrated_services.items():
        if support_status == "Supported":
            if org.organization_trust_status_for_service(service_principal):
                service_status[service] = True
            else:
                service_status[service] = False
    
    return service_status

def _get_organization_account_ids() -> list:
    accounts = get.get_accounts_and_regions()
    return list(accounts.keys())

def generic_service_enableness_checker(service_name, client_method_name, status_check=None, method_params=None) -> dict:
    def service_enableness():
        account_ids = _get_organization_account_ids()
        service_accounts_status = {}
        for account_id in account_ids:
            service_client = AWSClients.assumed_role_client(account_id, service_name)
            method_to_call = getattr(service_client, client_method_name)
            
            params = {}
            if method_params:
                if callable(method_params):
                    params = method_params(account_id)
                elif isinstance(method_params, dict):
                    params = method_params.copy()
                    if '{account_id}' in str(params):
                        params = {k: v.format(account_id=account_id) if isinstance(v, str) else v 
                                for k, v in params.items()}
            
            status = method_to_call(**params)
            service_accounts_status[account_id] = status_check(status) if status_check else status
        return service_accounts_status
    return service_enableness

def service_trust_status_update(service_principal: str, status: bool) -> bool:
    is_account_management = org.is_account_delegated_admin_or_management()
    if not is_account_management:
        return False
    
    if not status:
        return org.disable_organization_service_access(service_principal)
    
    return org.enable_organization_service_access(service_principal)
    
def compute_optimizer_service_enableness() -> dict:
    return generic_service_enableness_checker(
        service_name='compute-optimizer',
        client_method_name='get_enrollment_status',
        status_check=lambda account_info: account_info.get('status') == 'Active' if account_info.get('status') else False,
    )()

def compute_optimizer_service_update(optin_organization: bool = False, status: str = 'Active', accountid: str = None) -> dict:
    co = ComputeOptimizer()
    account_ids = _get_organization_account_ids()
    responses = {}

    # Create client once, using either accountid or management account
    clients = AWSClients(
        account_ids=accountid, 
        clients=[], 
        global_clients=['compute-optimizer'], 
        regions=[]
    )

    if optin_organization and status == 'Inactive':
        response = co.update_enrollment_status(status=status)
        responses['management'] = response

        for account_id in account_ids:
            co_client = clients.global_clients[account_id]['compute-optimizer']
            response = co_client.update_enrollment_status(status=status)
            responses[account_id] = response
        return responses

    if not optin_organization and accountid:
        co_client = clients.global_clients[accountid]['compute-optimizer']
        response = co_client.update_enrollment_status(status=status)
        return response
    
    co_client = clients.global_clients[accountid]['compute-optimizer']
    response = co_client.update_enrollment_status(status=status, optin_organization=optin_organization)
    return response
    
def cost_optimization_hub_service_enableness():
    return generic_service_enableness_checker(
        service_name='cost-optimization-hub',
        client_method_name='list_enrollment_statuses',
        status_check=lambda account_info: account_info.get('items')[0].get('status') == 'Active' if account_info.get('items') else False,
        method_params={
            'accountId': '{account_id}'
        }
    )()

def cost_optimization_hub_service_update(optin_organization: bool = False, status: str = 'Active', accountid: str = None) -> dict:
    coh = CostOptimizationHub()
    account_ids = _get_organization_account_ids()
    responses = {}

    clients = AWSClients(
        account_ids=accountid, 
        clients=[], 
        global_clients=['cost-optimization-hub'], 
        regions=[]
    )

    if optin_organization and status == 'Inactive':
        response = coh.update_enrollment_status(status=status)
        responses['management'] = response
        for account_id in account_ids:
            coh_client = clients.global_clients[account_id]['cost-optimization-hub']
            response = coh_client.update_enrollment_status(status=status)
            responses[account_id] = response
        return responses
    
    if not optin_organization and accountid:
        coh_client = clients.global_clients[accountid]['cost-optimization-hub']
        response = coh_client.update_enrollment_status(status=status)
        return response
    
    coh_client = clients.global_clients[accountid]['cost-optimization-hub']
    response = coh_client.update_enrollment_status(status=status, optin_organization=optin_organization)
    return response

