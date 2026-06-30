"""Local scan orchestrator — runs collectors and writes results to SQLite.

This replaces the remote ECS/Step Functions pipeline for local execution.
Scan results use the same Resource schema as the Tag Manager CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID

from modules.collection.collectors import (
    COLLECTORS,
    GLOBAL_SERVICES,
    SERVICE_PRIORITIES,
    CollectorResult,
)
from modules.collection.models import CollectionJob
from modules.collection.scan_contract import validate_resource_dict
from utils.core_storage import (
    create_record,
    delete_records,
    get_first_record,
    list_all_records,
    list_objects,
    resource_payload,
    update_record,
    upsert_by_filter,
)
from utils.logger_config import log

console = Console()

DEFAULT_SCAN_REGIONS = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
DEFAULT_SCAN_MAX_WORKERS = 8
ASSUME_ROLE_DEADLINE_SECONDS = 20
AWS_CLIENT_CONFIG = Config(
    connect_timeout=15,
    read_timeout=30,
    retries={"max_attempts": 2, "mode": "standard"},
)


class ScanCancelled(Exception):
    """Raised when a web scan receives a cooperative cancellation request."""


def _raise_if_cancelled(cancel_check: Optional[Callable[[], bool]]) -> None:
    if cancel_check and cancel_check():
        raise ScanCancelled("Scan cancelled")


def _permission_detail_with_account(detail: Dict, account_id: str) -> Dict:
    enriched = dict(detail)
    enriched["account_id"] = enriched.get("account_id") or account_id
    return enriched


def _permission_resource_types(details: List[Dict]) -> List[str]:
    resource_types = set()
    for detail in details:
        for resource_type in detail.get("resource_types") or []:
            resource_types.add(str(resource_type))
    return sorted(resource_types)


def _permission_progress_data(total_permission_errors: int, details: List[Dict]) -> Dict:
    return {
        "permission_errors_count": total_permission_errors,
        "permission_error_details": details[-10:],
        "permission_error_resource_types": _permission_resource_types(details),
    }


def get_enabled_regions(session: Optional["boto3.Session"] = None) -> List[str]:
    """Discover AWS regions enabled for this account."""
    ec2 = (
        session.client("ec2", region_name="us-east-1", config=AWS_CLIENT_CONFIG)
        if session
        else boto3.client("ec2", region_name="us-east-1", config=AWS_CLIENT_CONFIG)
    )
    response = ec2.describe_regions(
        Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
    )
    return sorted([r["RegionName"] for r in response.get("Regions", [])])


def get_account_info(session: Optional["boto3.Session"] = None) -> Dict[str, str]:
    """Get current account ID and name."""
    if session is None:
        try:
            accounts = list_all_records("core", "account-status")
            account = next((row for row in accounts if not row.get("role_arn")), None)
            if account and account.get("account_id"):
                return {
                    "account_id": account["account_id"],
                    "account_name": account.get("account_name") or account["account_id"],
                }
        except Exception:
            pass

    sts = session.client("sts", config=AWS_CLIENT_CONFIG) if session else boto3.client("sts", config=AWS_CLIENT_CONFIG)
    identity = sts.get_caller_identity()
    account_id = identity["Account"]

    account_name = account_id
    try:
        account = get_first_record("core", "account-status", filters=[("account_id", account_id)])
        if account and account.get("account_name"):
            account_name = account["account_name"]
    except Exception:
        pass

    # Avoid Organizations calls during web scan startup. They can add tens of
    # seconds under SSO and are not needed to execute collection.
    if account_name != account_id:
        return {"account_id": account_id, "account_name": account_name}

    try:
        arn = identity.get("Arn", "")
        if ":assumed-role/" in arn:
            account_name = arn.split(":assumed-role/", 1)[1].split("/", 1)[0]
    except Exception:
        pass

    return {"account_id": account_id, "account_name": account_name}


def run_local_scan(
    services: Optional[List[str]] = None,
    regions: Optional[List[str]] = None,
    session: Optional["boto3.Session"] = None,
    progress_callback: Optional[callable] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Run a full local scan — collect resources and write to SQLite.

    Args:
        services: List of service names to scan (default: all registered collectors)
        regions: List of regions to scan (default: US regions). Use ["all"] to scan all enabled regions.
        session: Optional boto3.Session for cross-account
        cancel_check: Optional callable returning True when the scan should stop

    Returns:
        Summary dict with counts and errors
    """
    _raise_if_cancelled(cancel_check)

    # Resolve account
    account_info = get_account_info(session)
    account_id = account_info["account_id"]
    account_name = account_info["account_name"]

    # Resolve services
    if services:
        active_collectors = {s: COLLECTORS[s] for s in services if s in COLLECTORS}
    else:
        active_collectors = dict(COLLECTORS)

    if not active_collectors:
        console.print("[red]No valid services to scan.[/red]")
        return {"error": "No valid services"}

    # Resolve regions
    scan_all_regions = bool(regions and len(regions) == 1 and regions[0].lower() == "all")
    if scan_all_regions:
        console.print("Discovering enabled regions...")
        regions = get_enabled_regions(session)
    elif not regions:
        regions = list(DEFAULT_SCAN_REGIONS)
    _raise_if_cancelled(cancel_check)

    console.print(f"Account: [cyan]{account_id}[/cyan] ({account_name})")
    console.print(f"Regions: [cyan]{len(regions)}[/cyan] | Services: [cyan]{', '.join(active_collectors.keys())}[/cyan]")

    # Save account to DB
    _upsert_account(account_id, account_name, regions)

    # Record scan start
    scan_record = _start_scan_record(account_id)
    scan_started_at = datetime.now(timezone.utc)

    # One-shot cleanup: the Service Quotas collector was removed, so any
    # leftover AWS::ServiceQuotas::Quota rows written by previous builds
    # will never be refreshed and should be dropped.
    _purge_service_quotas_rows(account_id)

    # Build jobs sorted by priority
    jobs = _build_jobs(active_collectors, regions, account_id, account_name, session)
    _raise_if_cancelled(cancel_check)

    # Report initial progress before cross-account setup. StackSet and STS
    # calls can be slow; the UI should never sit at 0% while setup is active.
    if progress_callback:
        progress_callback(2, f"Starting scan: {len(active_collectors)} services, {len(regions)} regions", {
            "total_resources": 0,
            "total_jobs": len(jobs),
            "completed_jobs": 0,
            "by_service": {},
            "by_region": {},
            "account_id": account_id,
            "current_service": None,
            "current_region": None,
            "errors_count": 0,
        })

    # Cross-account targets affect both duration and progress. Resolve them up
    # front so the web UI can report progress across the whole scan, not only
    # the management account.
    if progress_callback:
        progress_callback(3, "Checking multi-account scan targets...", {
            "total_resources": 0,
            "total_jobs": len(jobs),
            "completed_jobs": 0,
            "by_service": {},
            "by_region": {},
            "account_id": account_id,
            "current_service": None,
            "current_region": None,
            "errors_count": 0,
        })
    if not _has_enabled_cross_account_configs():
        _sync_stackset_scan_targets_from_aws()
    _raise_if_cancelled(cancel_check)
    if progress_callback:
        progress_callback(4, "Assuming roles for multi-account scan...", {
            "total_resources": 0,
            "total_jobs": len(jobs),
            "completed_jobs": 0,
            "by_service": {},
            "by_region": {},
            "account_id": account_id,
            "current_service": None,
            "current_region": None,
            "errors_count": 0,
        })
    cross_account_sessions = _get_cross_account_sessions(
        progress_callback=progress_callback,
        base_progress_data={
            "total_resources": 0,
            "total_jobs": len(jobs),
            "completed_jobs": 0,
            "by_service": {},
            "by_region": {},
            "account_id": account_id,
            "current_service": None,
            "current_region": None,
            "errors_count": 0,
        },
    )
    _raise_if_cancelled(cancel_check)
    estimated_total_jobs = len(jobs) * (1 + len(cross_account_sessions))

    # Execute
    total_resources = 0
    total_errors = []
    total_warnings = []
    total_permission_errors = 0
    total_permission_error_details = []
    by_service = {}
    by_region = {}
    completed_jobs = 0
    total_jobs = len(jobs)

    # Use Rich progress bar only when running in a terminal (not web headless)
    use_rich = progress_callback is None
    if use_rich:
        _progress_ctx = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        )
    else:
        from contextlib import nullcontext
        _progress_ctx = nullcontext()

    with _progress_ctx as progress_bar:
        if use_rich:
            task = progress_bar.add_task("Scanning...", total=len(jobs))

        max_workers = min(DEFAULT_SCAN_MAX_WORKERS, max(len(jobs), 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for job in jobs:
                _raise_if_cancelled(cancel_check)
                futures[executor.submit(active_collectors[job.service].collect, job)] = job

            try:
                for future in as_completed(futures):
                    _raise_if_cancelled(cancel_check)
                    job = futures[future]
                    label = f"{job.service}"
                    if job.region:
                        label += f" ({job.region})"
                    if use_rich:
                        progress_bar.update(task, description=f"Completed {label}")

                    try:
                        result = future.result()
                        _persist_resources(result.resources, account_id)
                        resource_count = len(result.resources)
                        total_resources += resource_count
                        total_warnings.extend(result.warnings)
                        total_errors.extend(result.errors)
                        total_permission_errors += result.permission_errors
                        permission_details = [
                            _permission_detail_with_account(detail, job.account_id or account_id)
                            for detail in result.permission_error_details
                        ]
                        total_permission_error_details.extend(permission_details)

                        # Track by service/region
                        by_service[job.service] = by_service.get(job.service, 0) + resource_count
                        if job.region:
                            by_region[job.region] = by_region.get(job.region, 0) + resource_count
                    except Exception as e:
                        total_errors.append(f"{job.service}/{job.region}: {e}")
                        log.warning(
                            "Collector %s/%s failed: %s: %s",
                            job.service, job.region, type(e).__name__, e,
                        )

                    completed_jobs += 1
                    if progress_callback:
                        pct = 5 + int((completed_jobs / max(estimated_total_jobs, 1)) * 85)
                        progress_callback(pct, f"Completed {label}", {
                            "total_resources": total_resources,
                            "total_jobs": total_jobs,
                            "completed_jobs": completed_jobs,
                            "by_service": dict(by_service),
                            "by_region": dict(by_region),
                            "account_id": account_id,
                            "current_service": job.service,
                            "current_region": job.region,
                            "warnings": total_warnings[-10:],
                            "warnings_count": len(total_warnings),
                            "errors_count": len(total_errors),
                            **_permission_progress_data(
                                total_permission_errors,
                                total_permission_error_details,
                            ),
                        })
                    if use_rich:
                        progress_bar.advance(task)
            except ScanCancelled:
                for pending in futures:
                    pending.cancel()
                raise

    # Finalize scan record
    _finish_scan_record(scan_record, total_resources, len(total_errors))

    # Run recommendations against collected data
    _raise_if_cancelled(cancel_check)
    console.print("Analyzing recommendations...")
    from modules.collection.recommendations import run_recommendations
    rec_summary = run_recommendations(account_id)
    total_recommendations = sum(rec_summary.values())

    # Discover relationships between collected resources
    _raise_if_cancelled(cancel_check)
    console.print("Discovering resource relationships...")
    total_relationships = _discover_relationships(account_id)

    # ------------------------------------------------------------------
    # Cross-account scanning
    # ------------------------------------------------------------------
    cross_accounts_scanned = 0

    for xa_account_id, xa_alias, xa_session in cross_account_sessions:
        _raise_if_cancelled(cancel_check)
        cross_accounts_scanned += 1
        label = xa_alias or xa_account_id
        console.print()
        console.print(f"[bold]Scanning cross-account: [cyan]{label}[/cyan] ({xa_account_id})[/bold]")

        if progress_callback:
            completed_overall_jobs = total_jobs + ((cross_accounts_scanned - 1) * total_jobs)
            pct = 5 + int((completed_overall_jobs / max(estimated_total_jobs, 1)) * 85)
            progress_callback(pct, f"Preparing cross-account scan: {label}", {
                "total_resources": total_resources,
                "total_jobs": 0,
                "completed_jobs": 0,
                "by_service": dict(by_service),
                "by_region": dict(by_region),
                "account_id": xa_account_id,
                "current_service": None,
                "current_region": None,
                "cross_accounts_scanned": cross_accounts_scanned - 1,
                "cross_accounts_total": len(cross_account_sessions),
                "warnings": total_warnings[-10:],
                "warnings_count": len(total_warnings),
                "errors_count": len(total_errors),
                **_permission_progress_data(
                    total_permission_errors,
                    total_permission_error_details,
                ),
            })

        if scan_all_regions:
            try:
                xa_regions = get_enabled_regions(xa_session)
            except Exception as e:
                total_errors.append(f"cross-account/{xa_account_id}: failed to discover regions: {e}")
                log.debug(f"Cross-account region discovery failed for {xa_account_id}: {e}")
                continue
        else:
            xa_regions = list(regions)

        _upsert_account(xa_account_id, xa_alias or xa_account_id, xa_regions)
        xa_jobs = _build_jobs(active_collectors, xa_regions, xa_account_id, xa_alias or xa_account_id, xa_session)
        xa_completed_jobs = 0
        xa_total_jobs = len(xa_jobs)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            xa_task = progress.add_task(f"Scanning {label}...", total=len(xa_jobs))

            max_workers = min(DEFAULT_SCAN_MAX_WORKERS, max(len(xa_jobs), 1))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for job in xa_jobs:
                    _raise_if_cancelled(cancel_check)
                    futures[executor.submit(active_collectors[job.service].collect, job)] = job

                try:
                    for future in as_completed(futures):
                        _raise_if_cancelled(cancel_check)
                        job = futures[future]
                        job_label = f"{job.service}"
                        if job.region:
                            job_label += f" ({job.region})"
                        progress.update(xa_task, description=f"[{label}] completed {job_label}")

                        try:
                            result = future.result()
                            _persist_resources(result.resources, xa_account_id)
                            resource_count = len(result.resources)
                            total_resources += resource_count
                            total_warnings.extend(result.warnings)
                            total_errors.extend(result.errors)
                            total_permission_errors += result.permission_errors
                            permission_details = [
                                _permission_detail_with_account(detail, job.account_id or xa_account_id)
                                for detail in result.permission_error_details
                            ]
                            total_permission_error_details.extend(permission_details)
                            by_service[job.service] = by_service.get(job.service, 0) + resource_count
                            if job.region:
                                by_region[job.region] = by_region.get(job.region, 0) + resource_count
                        except Exception as e:
                            total_errors.append(f"{xa_account_id}/{job.service}/{job.region}: {e}")
                            log.debug(f"Cross-account collector error: {xa_account_id}/{job.service}/{job.region}: {e}")

                        xa_completed_jobs += 1
                        if progress_callback:
                            completed_overall_jobs = (
                                total_jobs
                                + ((cross_accounts_scanned - 1) * xa_total_jobs)
                                + xa_completed_jobs
                            )
                            pct = 5 + int((completed_overall_jobs / max(estimated_total_jobs, 1)) * 85)
                            progress_callback(pct, f"Completed {label}: {job_label}", {
                                "total_resources": total_resources,
                                "total_jobs": xa_total_jobs,
                                "completed_jobs": xa_completed_jobs,
                                "by_service": dict(by_service),
                                "by_region": dict(by_region),
                                "account_id": xa_account_id,
                                "current_service": job.service,
                                "current_region": job.region,
                                "cross_accounts_scanned": cross_accounts_scanned - 1,
                                "cross_accounts_total": len(cross_account_sessions),
                                "warnings": total_warnings[-10:],
                                "warnings_count": len(total_warnings),
                                "errors_count": len(total_errors),
                                **_permission_progress_data(
                                    total_permission_errors,
                                    total_permission_error_details,
                                ),
                            })
                        progress.advance(xa_task)
                except ScanCancelled:
                    for pending in futures:
                        pending.cancel()
                    raise

        # Discover relationships for cross-account resources
        _raise_if_cancelled(cancel_check)
        xa_rels = _discover_relationships(xa_account_id)
        total_relationships += xa_rels

        if progress_callback:
            completed_overall_jobs = total_jobs + (cross_accounts_scanned * xa_total_jobs)
            pct = 5 + int((completed_overall_jobs / max(estimated_total_jobs, 1)) * 85)
            progress_callback(
                pct,
                f"Completed cross-account scan: {label}",
                {
                    "total_resources": total_resources,
                    "total_jobs": xa_total_jobs,
                    "completed_jobs": xa_completed_jobs,
                    "by_service": dict(by_service),
                    "by_region": dict(by_region),
                    "account_id": xa_account_id,
                    "current_service": None,
                    "current_region": None,
                    "cross_accounts_scanned": cross_accounts_scanned,
                    "cross_accounts_total": len(cross_account_sessions),
                    "warnings": total_warnings[-10:],
                    "warnings_count": len(total_warnings),
                    "errors_count": len(total_errors),
                    **_permission_progress_data(
                        total_permission_errors,
                        total_permission_error_details,
                    ),
                },
            )

        # Update last_used_at for this cross-account config
        _update_cross_account_last_used(xa_account_id)

    # Summary
    summary = {
        "account_id": account_id,
        "account_name": account_name,
        "regions_scanned": len(regions),
        "services_scanned": len(active_collectors),
        "total_resources": total_resources,
        "resources_found": total_resources,
        "recommendations_found": total_recommendations,
        "recommendation_breakdown": rec_summary,
        "relationships_found": total_relationships,
        "by_service": dict(by_service),
        "by_region": dict(by_region),
        "warnings": total_warnings,
        "warnings_count": len(total_warnings),
        "errors": total_errors,
        "permission_errors": total_permission_errors,
        "permission_error_details": total_permission_error_details,
        "permission_error_resource_types": _permission_resource_types(total_permission_error_details),
        "cross_accounts_scanned": cross_accounts_scanned,
    }

    console.print()
    console.print(f"[green]Scan complete:[/green] {total_resources} resources found")
    if cross_accounts_scanned:
        console.print(f"[cyan]Cross-account:[/cyan] {cross_accounts_scanned} additional accounts scanned")
    if total_recommendations:
        console.print(f"[cyan]Recommendations:[/cyan] {total_recommendations} findings")
        for rec_type, count in sorted(rec_summary.items()):
            console.print(f"  {rec_type}: {count}")
    if total_relationships:
        console.print(f"[cyan]Relationships:[/cyan] {total_relationships} discovered")
    if total_permission_errors:
        console.print(f"[yellow]Permission errors: {total_permission_errors} (some services may need additional IAM permissions)[/yellow]")
        skipped_types = _permission_resource_types(total_permission_error_details)
        if skipped_types:
            console.print("[yellow]Resource types not collected due to permissions:[/yellow]")
            for resource_type in skipped_types:
                console.print(f"  - {resource_type}")
        if total_permission_error_details:
            console.print("[yellow]Permission error details:[/yellow]")
            for detail in total_permission_error_details[:12]:
                account = detail.get("account_id") or "unknown"
                region = detail.get("region") or "global"
                service = detail.get("service") or "unknown"
                code = detail.get("code") or "AccessDenied"
                resource_types = ", ".join(detail.get("resource_types") or []) or "unknown resource types"
                resource_name = detail.get("resource_name")
                suffix = f"; resource {resource_name}" if resource_name else ""
                console.print(f"  - {account} {service}/{region}: {code}; skipped {resource_types}{suffix}")
            remaining = len(total_permission_error_details) - 12
            if remaining > 0:
                console.print(f"  ... and {remaining} more permission error(s)")
    if total_errors:
        console.print(f"[yellow]Errors: {len(total_errors)}[/yellow]")

    return summary

def _build_jobs(collectors, regions, account_id, account_name, session) -> List[CollectionJob]:
    """Build ordered list of CollectionJob objects."""
    jobs = []

    # Sort collectors by priority
    sorted_services = sorted(
        collectors.keys(),
        key=lambda s: SERVICE_PRIORITIES.get(s, 99),
    )

    for service in sorted_services:
        if service in GLOBAL_SERVICES:
            jobs.append(CollectionJob(
                service=service,
                region=None,
                account_id=account_id,
                account_name=account_name,
                session=session,
            ))
        else:
            for region in regions:
                jobs.append(CollectionJob(
                    service=service,
                    region=region,
                    account_id=account_id,
                    account_name=account_name,
                    session=session,
                ))

    return jobs


def _persist_resources(resource_dicts: List[Dict], account_id: str) -> None:
    """Upsert resources into bluearch-core storage.

    Each resource dict is validated against the scan contract before
    persisting. Invalid resources are skipped with a debug log warning.
    """
    if not resource_dicts:
        return

    for rd in resource_dicts:
        arn = rd.get("resource_arn")
        if not arn:
            continue

        # Validate against scan contract
        errors = validate_resource_dict(rd)
        if errors:
            log.debug(f"Skipping invalid resource {arn}: {errors}")
            continue

        payload = resource_payload(rd, default_account_id=account_id)
        upsert_by_filter(
            "core",
            "resources",
            filters=[("resource_arn", arn)],
            payload=payload,
        )


def _discover_relationships(account_id: str) -> int:
    """Discover and persist relationships between collected resources.

    Examines resource metadata to infer connections:
      - EC2 instance -> VPC (via vpc_id)
      - EC2 instance -> Subnet (via subnet_id)
      - EC2 instance -> Security Groups (via security_groups in metadata)
      - ELB -> VPC (via vpc_id)
      - RDS instance -> VPC (via DBSubnetGroup.VpcId or metadata)
      - EBS volume -> EC2 instance (via attachments)
      - Security Group -> VPC (via vpc_id)
      - ECS service -> ECS cluster (via ARN prefix)

    Returns:
        Number of relationships discovered.
    """
    relationships_found = 0

    # Load all resources for this account into a lookup by ARN
    resources = list_objects("core", "resources", filters=[("account_id", account_id)])
    if not resources:
        return 0

    arn_lookup = {r.resource_arn: r for r in resources}

    # Build secondary lookups for VPC, subnet, security group by resource_id
    vpc_by_id: Dict[str, Resource] = {}
    subnet_by_id: Dict[str, Resource] = {}
    sg_by_id: Dict[str, Resource] = {}
    instance_by_id: Dict[str, Resource] = {}
    ecs_cluster_by_arn: Dict[str, Resource] = {}

    for r in resources:
        if r.resource_type == "AWS::EC2::VPC":
            vpc_by_id[r.resource_id] = r
        elif r.resource_type == "AWS::EC2::Subnet":
            subnet_by_id[r.resource_id] = r
        elif r.resource_type == "AWS::EC2::SecurityGroup":
            sg_by_id[r.resource_id] = r
        elif r.resource_type == "AWS::EC2::Instance":
            instance_by_id[r.resource_id] = r
        elif r.resource_type == "AWS::ECS::Cluster":
            ecs_cluster_by_arn[r.resource_arn] = r

    def _upsert_rel(source_arn: str, target_arn: str, rel_type: str,
                    source_type: str, target_type: str, region: str):
        nonlocal relationships_found
        filters = [
            ("source_arn", source_arn),
            ("target_arn", target_arn),
            ("relationship_type", rel_type),
        ]
        existing = get_first_record("core", "resource-relationships", filters=filters)
        upsert_by_filter(
            "core",
            "resource-relationships",
            filters=filters,
            payload={
                "source_arn": source_arn,
                "target_arn": target_arn,
                "relationship_type": rel_type,
                "source_type": source_type,
                "target_type": target_type,
                "region": region,
                "account_id": account_id,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if not existing:
            relationships_found += 1

    for r in resources:
        meta = r.metadata_json or {}

        # EC2 Instance -> VPC
        if r.resource_type == "AWS::EC2::Instance":
            vpc_id = meta.get("vpc_id")
            if vpc_id and vpc_id in vpc_by_id:
                vpc_r = vpc_by_id[vpc_id]
                _upsert_rel(r.resource_arn, vpc_r.resource_arn, "member_of",
                            r.resource_type, vpc_r.resource_type, r.region)

            # EC2 Instance -> Subnet
            subnet_id = meta.get("subnet_id")
            if subnet_id and subnet_id in subnet_by_id:
                subnet_r = subnet_by_id[subnet_id]
                _upsert_rel(r.resource_arn, subnet_r.resource_arn, "member_of",
                            r.resource_type, subnet_r.resource_type, r.region)

            # EC2 Instance -> Security Groups
            sg_list = meta.get("security_groups", [])
            if isinstance(sg_list, list):
                for sg_entry in sg_list:
                    sg_id = sg_entry if isinstance(sg_entry, str) else (sg_entry.get("GroupId") if isinstance(sg_entry, dict) else None)
                    if sg_id and sg_id in sg_by_id:
                        sg_r = sg_by_id[sg_id]
                        _upsert_rel(r.resource_arn, sg_r.resource_arn, "secured_by",
                                    r.resource_type, sg_r.resource_type, r.region)

        # EBS Volume -> EC2 Instance (via attachments)
        elif r.resource_type == "AWS::EC2::Volume":
            attachments = meta.get("attachments", [])
            if isinstance(attachments, list):
                for att in attachments:
                    if isinstance(att, dict):
                        inst_id = att.get("instance_id")
                        if inst_id and inst_id in instance_by_id:
                            inst_r = instance_by_id[inst_id]
                            _upsert_rel(r.resource_arn, inst_r.resource_arn, "attached_to",
                                        r.resource_type, inst_r.resource_type, r.region)

        # Security Group -> VPC
        elif r.resource_type == "AWS::EC2::SecurityGroup":
            vpc_id = meta.get("vpc_id")
            if vpc_id and vpc_id in vpc_by_id:
                vpc_r = vpc_by_id[vpc_id]
                _upsert_rel(r.resource_arn, vpc_r.resource_arn, "member_of",
                            r.resource_type, vpc_r.resource_type, r.region)

        # ELB -> VPC
        elif r.resource_type and "ElasticLoadBalancing" in r.resource_type:
            vpc_id = meta.get("vpc_id")
            if vpc_id and vpc_id in vpc_by_id:
                vpc_r = vpc_by_id[vpc_id]
                _upsert_rel(r.resource_arn, vpc_r.resource_arn, "member_of",
                            r.resource_type, vpc_r.resource_type, r.region)

        # RDS -> VPC (metadata may include vpc_id from DBSubnetGroup)
        elif r.resource_type in ("AWS::RDS::DBInstance", "AWS::RDS::DBCluster"):
            vpc_id = meta.get("vpc_id")
            if vpc_id and vpc_id in vpc_by_id:
                vpc_r = vpc_by_id[vpc_id]
                _upsert_rel(r.resource_arn, vpc_r.resource_arn, "member_of",
                            r.resource_type, vpc_r.resource_type, r.region)

        # ECS Service -> ECS Cluster (via ARN prefix)
        elif r.resource_type == "AWS::ECS::Service":
            # ECS service ARN contains cluster name:
            # arn:aws:ecs:region:acct:service/cluster-name/service-name
            svc_arn = r.resource_arn or ""
            for cluster_arn, cluster_r in ecs_cluster_by_arn.items():
                cluster_name = cluster_r.resource_id
                if cluster_name and f"/service/{cluster_name}/" in svc_arn:
                    _upsert_rel(r.resource_arn, cluster_arn, "runs_in",
                                r.resource_type, cluster_r.resource_type, r.region)
                    break

    return relationships_found


def _upsert_account(account_id: str, account_name: str, regions: List[str]) -> None:
    """Create or update the core AccountStatus record."""
    upsert_by_filter(
        "core",
        "account-status",
        filters=[("account_id", account_id)],
        payload={
            "account_id": account_id,
            "account_name": account_name,
            "regions": regions,
            "last_discovery_at": datetime.now(timezone.utc).isoformat(),
            "enabled_for_discovery": True,
            "status": "ACTIVE",
        },
    )


def _purge_service_quotas_rows(account_id: str) -> None:
    """Drop every AWS::ServiceQuotas::Quota row — the collector that produced
    them has been removed, so they can never be refreshed. Runs once at the
    start of each scan to clean up data from older builds."""
    rows = list_all_records(
        "core",
        "resources",
        filters=[
            ("resource_type", "AWS::ServiceQuotas::Quota"),
            ("account_id", account_id),
        ],
    )
    deleted = delete_records("core", "resources", rows)
    if deleted:
        log.debug(f"Purged {deleted} obsolete Service Quotas rows")


def _start_scan_record(account_id: str) -> int:
    """Record a scan start in scan_history."""
    record = create_record(
        "core",
        "scan-history",
        {
            "scan_mode": "local",
            "collected_by": "bluearch",
            "status": "running",
        },
    )
    return record["id"]


def _finish_scan_record(record_id: int, resources_found: int, error_count: int) -> None:
    """Mark a scan as completed."""
    record = {"id": str(record_id), "record_key": str(record_id)}
    update_record(
        "core",
        "scan-history",
        record,
        {
            "status": "completed" if error_count == 0 else "completed_with_errors",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "resources_found": resources_found,
        },
    )


def _get_cross_account_sessions(
    progress_callback: Optional[callable] = None,
    base_progress_data: Optional[dict] = None,
) -> List[Tuple[str, str, "boto3.Session"]]:
    """Load enabled cross-account configs and assume roles.

    Returns:
        List of (account_id, alias_or_account_id, boto3.Session) tuples for
        accounts where role assumption succeeded.  Failures are logged but
        do not raise.
    """
    sessions: List[Tuple[str, str, "boto3.Session"]] = []

    try:
        configs = list_all_records(
            "core",
            "assume-role-configurations",
            filters=[("enabled", "true")],
        )
        config_data = [
            {
                "account_id": c.get("account_id"),
                "role_arn": c.get("role_arn"),
                "external_id": c.get("external_id"),
                "alias": c.get("alias"),
            }
            for c in configs
            if c.get("account_id") and c.get("role_arn")
        ]
    except Exception as e:
        log.debug(f"Failed to query cross-account configs: {e}")
        return sessions

    if not config_data:
        return sessions

    for cfg in config_data:
        if progress_callback:
            data = dict(base_progress_data or {})
            data.update({
                "current_service": "assume-role",
                "current_region": None,
                "account_id": cfg["account_id"],
                "cross_accounts_total": len(config_data),
                "cross_accounts_scanned": len(sessions),
            })
            progress_callback(4, f"Assuming role for {cfg['alias'] or cfg['account_id']}...", data)
        assumed = _assume_config(cfg)
        if assumed:
            sessions.append(assumed)

    return sorted(sessions, key=lambda item: item[0])


def _assume_config(cfg: dict) -> Optional[Tuple[str, str, "boto3.Session"]]:
    """Assume one cross-account role with a hard subprocess timeout when possible."""
    account_label = cfg["alias"] or cfg["account_id"]
    try:
        creds = _assume_role_with_aws_cli(cfg) or _assume_role_with_boto3(cfg)
        assumed_session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
        log.debug(f"Assumed role for cross-account {cfg['account_id']}")
        return (cfg["account_id"], account_label, assumed_session)
    except Exception as e:
        console.print(f"[yellow]Failed to assume role for account {cfg['account_id']}: {e}[/yellow]")
        log.debug(f"Cross-account assume_role failed for {cfg['account_id']}: {e}")
        return None


def _assume_role_with_aws_cli(cfg: dict) -> Optional[dict]:
    aws_cli = shutil.which("aws")
    if not aws_cli:
        return None

    cmd = [
        aws_cli,
        "sts",
        "assume-role",
        "--role-arn",
        cfg["role_arn"],
        "--role-session-name",
        "BlueArchCLI",
        "--output",
        "json",
    ]
    if cfg.get("external_id"):
        cmd.extend(["--external-id", cfg["external_id"]])

    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = datetime.now(timezone.utc).timestamp() + ASSUME_ROLE_DEADLINE_SECONDS
    while proc.poll() is None and datetime.now(timezone.utc).timestamp() < deadline:
        time.sleep(0.2)

    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.kill()
        raise TimeoutError(
            f"aws sts assume-role timed out after {ASSUME_ROLE_DEADLINE_SECONDS}s"
        )

    stdout, stderr = proc.communicate(timeout=2)
    if proc.returncode != 0:
        raise RuntimeError((stderr or stdout or "aws sts assume-role failed").strip())
    return json.loads(stdout)["Credentials"]


def _assume_role_with_boto3(cfg: dict) -> dict:
    sts = boto3.client("sts", config=AWS_CLIENT_CONFIG)
    assume_kwargs = {
        "RoleArn": cfg["role_arn"],
        "RoleSessionName": "BlueArchCLI",
    }
    if cfg.get("external_id"):
        assume_kwargs["ExternalId"] = cfg["external_id"]
    return sts.assume_role(**assume_kwargs)["Credentials"]


def _has_enabled_cross_account_configs() -> bool:
    """Return True when local scan targets already exist."""
    try:
        return bool(
            list_all_records(
                "core",
                "assume-role-configurations",
                filters=[("enabled", "true")],
            )
        )
    except Exception as e:
        log.debug(f"Failed to check cross-account configs: {e}")
        return False


def _sync_stackset_scan_targets_from_aws() -> int:
    """Best-effort sync of StackSet CURRENT instances into scan targets."""
    try:
        cf = boto3.client("cloudformation", config=AWS_CLIENT_CONFIG)
        org = boto3.client("organizations", config=AWS_CLIENT_CONFIG)
        org_info = org.describe_organization()["Organization"]
        management_account_id = (
            org_info.get("MasterAccountId")
            or org_info.get("ManagementAccountId")
            or ""
        )
        external_id = _generate_stackset_external_id(
            org_info["Id"],
            management_account_id,
        )
        paginator = cf.get_paginator("list_stack_instances")
        by_account: Dict[str, set[str]] = {}
        for page in paginator.paginate(StackSetName="BlueArchCLI-CrossAccount-Infrastructure"):
            for inst in page.get("Summaries", []):
                if inst.get("Status") == "CURRENT":
                    by_account.setdefault(inst["Account"], set()).add(inst["Region"])
    except Exception as e:
        log.debug(f"StackSet scan-target sync skipped: {e}")
        return 0

    account_names = {}
    try:
        paginator = org.get_paginator("list_accounts")
        for page in paginator.paginate():
            for account_info in page.get("Accounts", []):
                account_names[account_info["Id"]] = account_info.get("Name") or account_info["Id"]
    except Exception:
        pass

    synced = 0
    for account_id, regions in by_account.items():
        account_name = account_names.get(account_id, account_id)
        role_arn = f"arn:aws:iam::{account_id}:role/BlueArchRole"

        upsert_by_filter(
            "core",
            "account-status",
            filters=[("account_id", account_id)],
            payload={
                "account_id": account_id,
                "account_name": account_name,
                "enabled_for_discovery": True,
                "role_name": "BlueArchRole",
                "role_arn": role_arn,
                "regions": sorted(regions),
                "access_check_status": "NOT_TESTED",
                "status": "ACTIVE",
            },
        )

        upsert_by_filter(
            "core",
            "assume-role-configurations",
            filters=[("account_id", account_id)],
            payload={
                "account_id": account_id,
                "role_arn": role_arn,
                "role_name": "BlueArchRole",
                "external_id": external_id,
                "alias": account_name,
                "enabled": True,
                "is_active": True,
            },
        )
        synced += 1
    return synced


def _generate_stackset_external_id(organization_id: str, management_account_id: str) -> str:
    import hashlib

    unique_string = f"{organization_id}-{management_account_id}-BlueArchCLI"
    return hashlib.sha256(unique_string.encode()).hexdigest()[:32]


def _update_cross_account_last_used(account_id: str) -> None:
    """Update the last_used_at timestamp for a cross-account config."""
    try:
        config = get_first_record(
            "core",
            "assume-role-configurations",
            filters=[("account_id", account_id)],
        )
        if config:
            update_record(
                "core",
                "assume-role-configurations",
                config,
                {
                    "last_used_at": datetime.now(timezone.utc).isoformat(),
                    "is_active": True,
                },
            )
    except Exception as e:
        log.debug(f"Failed to update last_used_at for {account_id}: {e}")
