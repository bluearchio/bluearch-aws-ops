"""AWS Opt-In services management endpoints.

Web equivalent of the CLI `bluearch optin-hub` command. Lets users
enable/disable AWS Organizations trusted services and check per-account
enrollment status for services like Compute Optimizer and Cost Optimization
Hub at the organization level.
"""

import asyncio
import hashlib
import logging
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/optin", tags=["optin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ServiceStatus(BaseModel):
    name: str
    service_principal: str
    enabled: bool
    supported: bool = True
    description: Optional[str] = None
    toggle_supported: bool = True
    disabled_reason: Optional[str] = None


class AccountEnrollment(BaseModel):
    account_id: str
    status: str  # Active, Inactive, Pending, Failed, Unknown
    error: Optional[str] = None


class ServiceEnrollmentResponse(BaseModel):
    service: str
    org_enabled: bool
    accounts: List[AccountEnrollment] = []


class ToggleServiceRequest(BaseModel):
    service_principal: str
    enable: bool


class UpdateEnrollmentRequest(BaseModel):
    service: str  # "compute-optimizer" or "cost-optimization-hub"
    account_id: str
    status: str  # Active or Inactive
    optin_organization: bool = False


# ---------------------------------------------------------------------------
# Service registry (mirrors the CLI optin-hub)
# ---------------------------------------------------------------------------

ORGANIZATIONS_SERVICES = [
    ("Compute Optimizer", "compute-optimizer.amazonaws.com", True,
     "Analyzes EC2/EBS/Lambda utilization to recommend rightsizing."),
    ("Cost Optimization Hub", "cost-optimization-hub.bcm.amazonaws.com", True,
     "Consolidated cost-saving recommendations across AWS."),
    ("Amazon GuardDuty", "guardduty.amazonaws.com", False,
     "Managed threat detection service."),
    ("AWS Config", "config.amazonaws.com", False,
     "Resource configuration tracking and compliance."),
    ("AWS Security Hub", "securityhub.amazonaws.com", False,
     "Security posture across AWS accounts."),
    ("Amazon Inspector", "inspector2.amazonaws.com", False,
     "Automated vulnerability management."),
    ("AWS Trusted Advisor", "reporting.trustedadvisor.amazonaws.com", False,
     "Cost and performance recommendations."),
    ("AWS Backup", "backup.amazonaws.com", False,
     "Centralized backup management."),
    ("CloudTrail", "cloudtrail.amazonaws.com", False,
     "API activity auditing."),
]

TRUSTED_ADVISOR_TOGGLE_DISABLED_REASON = (
    "AWS Trusted Advisor organizational view is managed from Trusted Advisor. "
    "Enable or disable it from Trusted Advisor instead of the BlueArch "
    "Organizations trusted-services toggle."
)

TOGGLE_UNSUPPORTED_REASONS = {
    "trustedadvisor.amazonaws.com": TRUSTED_ADVISOR_TOGGLE_DISABLED_REASON,
    "reporting.trustedadvisor.amazonaws.com": TRUSTED_ADVISOR_TOGGLE_DISABLED_REASON,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_management_or_delegated() -> tuple[bool, Optional[str]]:
    """Return (is_authorized, error_message)."""
    try:
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        current_account = identity.get("Account")

        org = boto3.client("organizations")
        org_info = org.describe_organization()["Organization"]
        master_account = org_info.get("MasterAccountId")

        if current_account == master_account:
            return True, None

        # Check delegated admin status
        try:
            delegated = org.list_delegated_administrators()
            da_ids = [a["Id"] for a in delegated.get("DelegatedAdministrators", [])]
            if current_account in da_ids:
                return True, None
        except ClientError:
            pass

        return False, (
            f"Current account ({current_account}) is not the management account "
            f"({master_account}) and not a delegated administrator."
        )
    except ClientError as e:
        return False, str(e)


def _list_enabled_org_services() -> set[str]:
    """Return the set of service principals currently enabled in the org."""
    try:
        org = boto3.client("organizations")
        paginator = org.get_paginator("list_aws_service_access_for_organization")
        enabled = set()
        for page in paginator.paginate():
            for s in page.get("EnabledServicePrincipals", []):
                sp = s.get("ServicePrincipal")
                if sp:
                    enabled.add(sp)
        return enabled
    except ClientError as e:
        logger.warning("Failed to list enabled org services: %s", e)
        return set()


def _list_organization_accounts() -> list[str]:
    """List active account IDs in the organization."""
    try:
        org = boto3.client("organizations")
        paginator = org.get_paginator("list_accounts")
        accounts = []
        for page in paginator.paginate():
            for acct in page.get("Accounts", []):
                if acct.get("Status") == "ACTIVE":
                    accounts.append(acct["Id"])
        return accounts
    except ClientError:
        return []


def _optin_region() -> str:
    """Use a stable region for cost optimization control-plane APIs."""
    return boto3.session.Session().region_name or "us-east-1"


def _organization_context() -> tuple[str, str]:
    """Return (organization_id, management_account_id)."""
    org = boto3.client("organizations")
    info = org.describe_organization()["Organization"]
    return info["Id"], info["MasterAccountId"]


def _current_account_id() -> str:
    return boto3.client("sts").get_caller_identity()["Account"]


def _cross_account_external_id() -> str:
    """ExternalId used by the shared BlueArchRole StackSet."""
    org_id, management_account_id = _organization_context()
    seed = f"{org_id}-{management_account_id}-BlueArchCLI"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _client_for_account(service_name: str, account_id: Optional[str]):
    """Return a service client in the target account.

    For member accounts this assumes the shared StackSet role. This makes the
    web Opt-In Hub work regardless of whether the StackSet was deployed from
    BlueArch or Tag Manager.
    """
    region = _optin_region()
    target = account_id or _current_account_id()
    if target == _current_account_id():
        return boto3.client(service_name, region_name=region)

    sts = boto3.client("sts")
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{target}:role/BlueArchRole",
        RoleSessionName="BlueArchOptInHub",
        ExternalId=_cross_account_external_id(),
    )["Credentials"]
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
    return session.client(service_name, region_name=region)


def _get_compute_optimizer_enrollment() -> list[AccountEnrollment]:
    """Get Compute Optimizer enrollment status.

    Tries the organization-wide API first. If that fails (trusted access not
    enabled or org features not all enabled), falls back to checking only
    the current account's own enrollment status.
    """
    results = []
    co = boto3.client("compute-optimizer", region_name=_optin_region())

    # Try org-wide query first
    try:
        resp = co.get_enrollment_statuses_for_organization()
        for s in resp.get("accountEnrollmentStatuses", []):
            results.append(
                AccountEnrollment(
                    account_id=s.get("accountId", ""),
                    status=s.get("status", "Unknown"),
                )
            )
        return results
    except ClientError as org_err:
        logger.info("Org-wide Compute Optimizer query unavailable (%s), falling back to single-account", org_err)

    # Fallback: check only current account
    try:
        resp = co.get_enrollment_status()
        status = resp.get("status", "Unknown")
        sts = boto3.client("sts")
        acct = sts.get_caller_identity().get("Account", "")
        results.append(AccountEnrollment(account_id=acct, status=status))
    except ClientError as e:
        try:
            sts = boto3.client("sts")
            acct = sts.get_caller_identity().get("Account", "")
        except Exception:
            acct = "current"
        results.append(
            AccountEnrollment(
                account_id=acct,
                status="Unknown",
                error=(
                    "Organization-wide enrollment query requires trusted access "
                    "for Compute Optimizer. Enable it in the services table above, "
                    f"then reload. (Detail: {e})"
                ),
            )
        )
    return results


def _get_cost_optimization_hub_enrollment() -> list[AccountEnrollment]:
    """Get Cost Optimization Hub enrollment status.

    Falls back to single-account check if the org-wide API is unavailable.
    """
    results = []
    coh = boto3.client("cost-optimization-hub", region_name=_optin_region())

    # Try org-wide query
    try:
        resp = coh.list_enrollment_statuses(includeOrganizationInfo=True)
        for item in resp.get("items", []):
            results.append(
                AccountEnrollment(
                    account_id=item.get("accountId", ""),
                    status=item.get("status", "Unknown"),
                )
            )
        return results
    except ClientError as org_err:
        logger.info("Org-wide Cost Optimization Hub query unavailable (%s), falling back", org_err)

    # Fallback: single account
    try:
        resp = coh.list_enrollment_statuses()
        for item in resp.get("items", []):
            results.append(
                AccountEnrollment(
                    account_id=item.get("accountId", ""),
                    status=item.get("status", "Unknown"),
                )
            )
        if not results:
            sts = boto3.client("sts")
            acct = sts.get_caller_identity().get("Account", "")
            results.append(AccountEnrollment(account_id=acct, status="Not enrolled"))
    except ClientError as e:
        try:
            sts = boto3.client("sts")
            acct = sts.get_caller_identity().get("Account", "")
        except Exception:
            acct = "current"
        results.append(
            AccountEnrollment(
                account_id=acct,
                status="Unknown",
                error=(
                    "Enable trusted access for Cost Optimization Hub in the "
                    f"services table above, then reload. (Detail: {e})"
                ),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/authorization")
async def check_authorization(_user: Optional[dict] = Depends(get_current_user)):
    """Check if the current identity can manage Organizations opt-in settings."""
    is_authorized, err = await asyncio.to_thread(_is_management_or_delegated)
    return {"authorized": is_authorized, "error": err}


@router.get("/services", response_model=List[ServiceStatus])
async def list_services(current_user=Depends(get_current_user)):
    """List AWS Organizations trusted services and their enabled status."""
    def _fetch():
        enabled = _list_enabled_org_services()
        return [
            ServiceStatus(
                name=name,
                service_principal=sp,
                enabled=sp in enabled,
                supported=supported,
                description=description,
                toggle_supported=sp not in TOGGLE_UNSUPPORTED_REASONS,
                disabled_reason=TOGGLE_UNSUPPORTED_REASONS.get(sp),
            )
            for name, sp, supported, description in ORGANIZATIONS_SERVICES
        ]

    result = await asyncio.to_thread(_fetch)


    return result


@router.post("/services/toggle")
async def toggle_service(
    body: ToggleServiceRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Enable or disable an AWS Organizations trusted service."""
    is_authorized, err = await asyncio.to_thread(_is_management_or_delegated)
    if not is_authorized:
        raise HTTPException(status_code=403, detail=err or "Not authorized")

    def _toggle():
        disabled_reason = TOGGLE_UNSUPPORTED_REASONS.get(body.service_principal)
        if disabled_reason:
            raise HTTPException(status_code=400, detail=disabled_reason)

        known_services = {sp for _, sp, _, _ in ORGANIZATIONS_SERVICES}
        if body.service_principal not in known_services:
            raise HTTPException(status_code=400, detail="Unsupported service principal")

        org = boto3.client("organizations")
        try:
            if body.enable:
                org.enable_aws_service_access(ServicePrincipal=body.service_principal)
                return {"success": True, "message": f"Enabled {body.service_principal}"}
            else:
                org.disable_aws_service_access(ServicePrincipal=body.service_principal)
                return {"success": True, "message": f"Disabled {body.service_principal}"}
        except ClientError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return await asyncio.to_thread(_toggle)


@router.get("/enrollment/{service}", response_model=ServiceEnrollmentResponse)
async def get_enrollment(
    service: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Get per-account enrollment status for Compute Optimizer or Cost Optimization Hub."""
    if service not in ("compute-optimizer", "cost-optimization-hub"):
        raise HTTPException(status_code=400, detail="Service must be compute-optimizer or cost-optimization-hub")

    def _fetch():
        enabled_services = _list_enabled_org_services()
        if service == "compute-optimizer":
            org_enabled = "compute-optimizer.amazonaws.com" in enabled_services
            accounts = _get_compute_optimizer_enrollment()
        else:
            org_enabled = "cost-optimization-hub.bcm.amazonaws.com" in enabled_services
            accounts = _get_cost_optimization_hub_enrollment()
        return ServiceEnrollmentResponse(
            service=service, org_enabled=org_enabled, accounts=accounts
        )

    return await asyncio.to_thread(_fetch)


@router.post("/enrollment/update")
async def update_enrollment(
    body: UpdateEnrollmentRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Update Compute Optimizer or Cost Optimization Hub enrollment for an account."""
    if body.service not in ("compute-optimizer", "cost-optimization-hub"):
        raise HTTPException(status_code=400, detail="Unsupported service")
    if body.status not in ("Active", "Inactive"):
        raise HTTPException(status_code=400, detail="Status must be Active or Inactive")

    def _update():
        try:
            if body.service == "compute-optimizer":
                client = (
                    boto3.client("compute-optimizer", region_name=_optin_region())
                    if body.optin_organization
                    else _client_for_account("compute-optimizer", body.account_id)
                )
                resp = client.update_enrollment_status(
                    status=body.status,
                    includeMemberAccounts=body.optin_organization,
                )
                return {
                    "success": True,
                    "service": body.service,
                    "account_id": body.account_id,
                    "new_status": resp.get("status"),
                }
            else:
                client = (
                    boto3.client("cost-optimization-hub", region_name=_optin_region())
                    if body.optin_organization
                    else _client_for_account("cost-optimization-hub", body.account_id)
                )
                resp = client.update_enrollment_status(
                    status=body.status,
                    includeMemberAccounts=body.optin_organization,
                )
                return {
                    "success": True,
                    "service": body.service,
                    "account_id": body.account_id,
                    "new_status": resp.get("status"),
                }
        except ClientError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return await asyncio.to_thread(_update)
