"""Local recommendation engine — analyzes collected resources in SQLite.

Ported from the worker's gold-layer logic. These functions run against locally
collected resource data and produce Recommendation rows in the shared database.

Recommendations:
- Unattached EBS volumes
- Previous-generation EBS volumes (gp2/io1)
- Old stopped EC2 instances
- Previous-generation EC2 instances
- Expired IAM access keys
- Inactive IAM roles
- Unencrypted EBS volumes
- Unencrypted RDS instances
- Previous-generation RDS instances
- Underutilized EC2 instances (CloudWatch CPU/Network metrics)
- Unused security groups (no attached ENIs)
- Unattached Elastic IPs (no association)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Importing ``collectors`` first ensures its bottom-of-file registration of
# sibling collectors (including ``compute_optimizer``) has completed before we
# pull the mapper functions in, avoiding a partially-initialized-module
# ImportError when ``recommendations`` is the first entry point.
from modules.collection import collectors as _collectors  # noqa: F401
from modules.collection.compute_optimizer import (
    COMPUTE_OPTIMIZER_RECOMMENDATION_FUNCTIONS,
)
from utils.core_storage import list_objects, upsert_by_filter
from utils.logger_config import log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec_id(rec_type: str, resource_id: str, account_id: str, region: str) -> str:
    """Deterministic recommendation unique_id (SHA256)."""
    raw = f"{rec_type}:{resource_id}:{account_id}:{region}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _upsert_recommendations(recs: List[Dict[str, Any]]):
    """Write recommendation dicts through bluearch-core storage."""
    if not recs:
        return

    for rec in recs:
        uid = rec["unique_id"]
        upsert_by_filter(
            "bluearch",
            "recommendations",
            filters=[("unique_id", uid)],
            payload={
                "unique_id": uid,
                "recommendation_type": rec["recommendation_type"],
                "region_name": rec.get("region_name", ""),
                "account_id": rec.get("account_id", ""),
                "account_name": rec.get("account_name", ""),
                "attributes": rec.get("attributes", {}),
                "resource_id": rec.get("db_resource_id"),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        )


# ---------------------------------------------------------------------------
# EC2 Recommendations
# ---------------------------------------------------------------------------

def unattached_ec2_volumes(resources: List[Any]) -> List[Dict]:
    """EBS volumes in 'available' state (not attached to any instance)."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Volume":
            continue
        meta = r.metadata_json or {}
        if meta.get("state") != "available":
            continue

        recs.append({
            "unique_id": _rec_id("unattached_ec2_volumes", r.resource_id, r.account_id, r.region),
            "recommendation_type": "unattached_ec2_volumes",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "VolumeType": meta.get("volume_type"),
                "Size": meta.get("size_gb"),
                "ActionRationale": "Unattached",
            },
        })
    return recs


def previous_gen_ec2_volumes(resources: List[Resource]) -> List[Dict]:
    """EBS volumes using gp2 or io1 (should be upgraded to gp3/io2)."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Volume":
            continue
        meta = r.metadata_json or {}
        vol_type = meta.get("volume_type", "")
        if vol_type not in ("gp2", "io1"):
            continue

        recs.append({
            "unique_id": _rec_id("previous_gen_ec2_volumes", r.resource_id, r.account_id, r.region),
            "recommendation_type": "previous_gen_ec2_volumes",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "VolumeType": vol_type,
                "Size": meta.get("size_gb"),
                "ActionRationale": "Previous Gen",
                "BluearchAction": "UPGRADE_VOLUME_TYPE",
            },
        })
    return recs


def unencrypted_ec2_volumes(resources: List[Resource]) -> List[Dict]:
    """EBS volumes without encryption enabled."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Volume":
            continue
        meta = r.metadata_json or {}
        if meta.get("encrypted") is True:
            continue

        recs.append({
            "unique_id": _rec_id("unencrypted_ec2_volumes", r.resource_id, r.account_id, r.region),
            "recommendation_type": "unencrypted_ec2_volumes",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "VolumeType": meta.get("volume_type"),
                "Size": meta.get("size_gb"),
                "ActionRationale": "Unencrypted",
            },
        })
    return recs


PREVIOUS_GEN_INSTANCE_FAMILIES = {
    "a1", "c1", "c3", "c4", "g2", "i2",
    "m1", "m2", "m3", "m4", "r3", "r4", "t1",
}


def previous_gen_ec2_instances(resources: List[Resource]) -> List[Dict]:
    """EC2 instances running previous-generation instance types."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Instance":
            continue
        meta = r.metadata_json or {}
        instance_type = meta.get("instance_type", "")
        family = instance_type.split(".")[0] if "." in instance_type else ""
        if family not in PREVIOUS_GEN_INSTANCE_FAMILIES:
            continue

        recs.append({
            "unique_id": _rec_id("previous_gen_ec2_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "previous_gen_ec2_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "InstanceType": instance_type,
                "ActionRationale": "Previous Gen",
            },
        })
    return recs


def old_stopped_ec2_instances(resources: List[Resource], days: int = 7) -> List[Dict]:
    """EC2 instances stopped for longer than the threshold."""
    recs = []
    now = datetime.now(timezone.utc)

    for r in resources:
        if r.resource_type != "AWS::EC2::Instance":
            continue
        meta = r.metadata_json or {}
        if meta.get("state") != "stopped":
            continue

        # Use last_scanned_at as a proxy — if the instance has been seen as
        # stopped across multiple scans, it qualifies. For a more precise check,
        # the worker parses StateTransitionReason, but we don't collect that yet.
        # We use discovered_at as a lower bound for how long it's been stopped.
        if r.discovered_at and (now - r.discovered_at).days >= days:
            recs.append({
                "unique_id": _rec_id("old_stopped_ec2_instances", r.resource_id, r.account_id, r.region),
                "recommendation_type": "old_stopped_ec2_instances",
                "region_name": r.region,
                "account_id": r.account_id,
                "db_resource_id": r.id,
                "attributes": {
                    "resource_id": r.resource_id,
                    "InstanceType": meta.get("instance_type"),
                    "ActionRationale": "Stopped",
                    "BluearchAction": "CREATE_AMI_AND_TERMINATE",
                },
            })
    return recs


# ---------------------------------------------------------------------------
# RDS Recommendations
# ---------------------------------------------------------------------------

PREVIOUS_GEN_RDS_FAMILIES = {
    "m1", "m2", "m3", "m4", "r1", "r2", "r3", "r4", "t1", "t2",
}


def previous_gen_rds_instances(resources: List[Resource]) -> List[Dict]:
    """RDS instances using previous-generation instance classes."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::RDS::DBInstance":
            continue
        meta = r.metadata_json or {}
        instance_class = meta.get("instance_class", "")
        # Instance class format: db.m4.large -> family is m4
        parts = instance_class.replace("db.", "").split(".")
        family = parts[0] if parts else ""
        if family not in PREVIOUS_GEN_RDS_FAMILIES:
            continue

        recs.append({
            "unique_id": _rec_id("previous_gen_rds_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "previous_gen_rds_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "DBInstanceClass": instance_class,
                "Engine": meta.get("engine"),
                "ActionRationale": "Previous Generation",
            },
        })
    return recs


def unencrypted_rds_instances(resources: List[Resource]) -> List[Dict]:
    """RDS instances without storage encryption."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::RDS::DBInstance":
            continue
        meta = r.metadata_json or {}
        # Skip if encrypted or field missing (assume encrypted if unknown)
        if meta.get("storage_encrypted") is not False:
            # We don't store storage_encrypted in the collector yet, but the
            # field can be added later. For now check the raw metadata.
            continue

        recs.append({
            "unique_id": _rec_id("unencrypted_rds_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "unencrypted_rds_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "Engine": meta.get("engine"),
                "StorageGB": meta.get("allocated_storage_gb"),
                "ActionRationale": "Unencrypted",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# IAM Recommendations
# ---------------------------------------------------------------------------

def expired_iam_keys(resources: List[Resource], max_age_days: int = 90) -> List[Dict]:
    """IAM access keys older than the threshold."""
    recs = []
    now = datetime.now(timezone.utc)

    for r in resources:
        if r.resource_type != "AWS::IAM::AccessKey":
            continue
        if not r.created_at:
            continue

        created = r.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days

        if age_days <= max_age_days:
            continue

        meta = r.metadata_json or {}
        recs.append({
            "unique_id": _rec_id("expired_iam_keys", r.resource_id, r.account_id, "global"),
            "recommendation_type": "expired_iam_keys",
            "region_name": "global",
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "Username": meta.get("user_name"),
                "AccessKeyId": r.resource_id,
                "AgeDays": age_days,
                "ActionRationale": f"Warning: IAM key is {age_days} days old and needs rotation.",
            },
        })
    return recs


def inactive_iam_roles(resources: List[Resource], warning_days: int = 30) -> List[Dict]:
    """IAM roles not used within the threshold period."""
    recs = []
    # IAM roles need RoleLastUsed data which we don't collect in the basic
    # role listing yet. This is a placeholder for when the collector is
    # enhanced to include last-used info.
    # For now, skip — this will be enabled when the IAM collector is expanded.
    return recs


# ---------------------------------------------------------------------------
# CloudWatch-based EC2 Recommendations
# ---------------------------------------------------------------------------

# Thresholds for underutilized instances
_CPU_AVG_THRESHOLD = 5.0  # percent
_NETWORK_IN_THRESHOLD = 100 * 1024 * 1024  # 100 MB over 7 days


def underutilized_ec2_instances(resources: List[Resource]) -> List[Dict]:
    """EC2 instances with very low CPU and network usage over 7 days.

    Requires CloudWatch metrics to be present in metadata_json (populated
    by the EC2 collector's CloudWatch enrichment step).  An instance is
    flagged when **both** ``cpu_avg`` < 5 % and ``network_in_bytes`` <
    100 MB over the measurement window.
    """
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Instance":
            continue
        meta = r.metadata_json or {}
        if meta.get("state") != "running":
            continue
        cpu_avg = meta.get("cpu_avg")
        network_in = meta.get("network_in_bytes")
        # Skip if CloudWatch metrics were not collected for this instance
        if cpu_avg is None or network_in is None:
            continue
        if cpu_avg >= _CPU_AVG_THRESHOLD or network_in >= _NETWORK_IN_THRESHOLD:
            continue

        recs.append({
            "unique_id": _rec_id("underutilized_ec2_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "underutilized_ec2_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "InstanceType": meta.get("instance_type"),
                "CpuAvgPercent": cpu_avg,
                "NetworkInBytes7d": network_in,
                "ActionRationale": (
                    f"Underutilized: CPU avg {cpu_avg}%, "
                    f"network in {round(network_in / (1024 * 1024), 1)} MB over 7 days"
                ),
                "BluearchAction": "RIGHTSIZE_OR_TERMINATE",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Security Group Recommendations
# ---------------------------------------------------------------------------

def unused_security_groups(resources: List[Resource]) -> List[Dict]:
    """Security groups with no attached network interfaces.

    Uses boto3 directly to call ``describe_network_interfaces`` with each
    security group as a filter.  Groups that have zero associated ENIs are
    considered unused.  Default VPC security groups (named ``default``) are
    skipped because AWS prevents their deletion.
    """
    # Collect SG resources grouped by (account_id, region) so we can batch
    # API calls with a single EC2 client per region.
    sg_map: Dict[tuple, List[Resource]] = {}
    for r in resources:
        if r.resource_type != "AWS::EC2::SecurityGroup":
            continue
        meta = r.metadata_json or {}
        # Skip default SGs — they cannot be deleted
        if meta.get("group_name") == "default":
            continue
        key = (r.account_id, r.region)
        sg_map.setdefault(key, []).append(r)

    if not sg_map:
        return []

    recs = []
    for (account_id, region), sg_resources in sg_map.items():
        try:
            ec2 = boto3.client("ec2", region_name=region)
        except Exception:
            log.debug(f"unused_security_groups: failed to create EC2 client for {region}")
            continue

        for r in sg_resources:
            try:
                resp = ec2.describe_network_interfaces(
                    Filters=[{"Name": "group-id", "Values": [r.resource_id]}],
                    MaxResults=5,  # We only need to know if >0 exist
                )
                if resp.get("NetworkInterfaces"):
                    continue  # SG is in use
            except ClientError:
                # If we can't check, skip rather than produce a false positive
                continue

            meta = r.metadata_json or {}
            recs.append({
                "unique_id": _rec_id("unused_security_groups", r.resource_id, r.account_id, r.region),
                "recommendation_type": "unused_security_groups",
                "region_name": r.region,
                "account_id": r.account_id,
                "db_resource_id": r.id,
                "attributes": {
                    "resource_id": r.resource_id,
                    "GroupName": meta.get("group_name"),
                    "VpcId": meta.get("vpc_id"),
                    "ActionRationale": "Security group has no attached network interfaces",
                },
            })

    return recs


# ---------------------------------------------------------------------------
# Elastic IP Recommendations
# ---------------------------------------------------------------------------

def unattached_elastic_ips(resources: List[Resource]) -> List[Dict]:
    """Elastic IPs that are not associated with any resource.

    An unassociated EIP incurs hourly charges.  The collector stores
    ``association_id`` in metadata; when it is absent or empty, the EIP is
    considered unattached.
    """
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::EIP":
            continue
        meta = r.metadata_json or {}
        # association_id is set only when the EIP is associated with an ENI/instance
        if meta.get("association_id"):
            continue

        recs.append({
            "unique_id": _rec_id("unattached_elastic_ips", r.resource_id, r.account_id, r.region),
            "recommendation_type": "unattached_elastic_ips",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "PublicIp": meta.get("public_ip"),
                "Domain": meta.get("domain"),
                "ActionRationale": "Elastic IP is not associated with any resource and incurs hourly charges",
                "BluearchAction": "RELEASE_EIP",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Cost Optimization Hub Recommendations
# ---------------------------------------------------------------------------

def cost_optimization_hub_recommendations(resources: List[Resource]) -> List[Dict]:
    """Surface recommendations collected from AWS Cost Optimization Hub.

    Each ``AWS::CostOptimizationHub::Recommendation`` resource becomes a single
    Recommendation row. The full metadata (action type, savings, effort, etc.)
    is copied into ``attributes`` so downstream reporting has access to the
    same fields AWS returned.
    """
    recs: List[Dict[str, Any]] = []
    for r in resources:
        if r.resource_type != "AWS::CostOptimizationHub::Recommendation":
            continue
        meta = r.metadata_json or {}

        estimated_savings = meta.get("estimatedMonthlySavings")
        action_type = meta.get("actionType") or "Optimize"
        current_type = meta.get("currentResourceType") or ""
        rationale = f"Cost Optimization Hub: {action_type}"
        if current_type:
            rationale += f" ({current_type})"
        if estimated_savings is not None:
            rationale += f" — estimated monthly savings: {estimated_savings}"

        attributes: Dict[str, Any] = {
            "resource_id": r.resource_id,
            "ActionType": action_type,
            "CurrentResourceType": current_type,
            "RecommendedResourceType": meta.get("recommendedResourceType"),
            "EstimatedMonthlySavings": estimated_savings,
            "EstimatedSavingsPercentage": meta.get("estimatedSavingsPercentage"),
            "CurrencyCode": meta.get("currencyCode"),
            "ImplementationEffort": meta.get("implementationEffort"),
            "RestartNeeded": meta.get("restartNeeded"),
            "Source": meta.get("source"),
            "LookbackPeriodDays": meta.get("recommendationLookbackPeriodInDays"),
            "CurrentResourceSummary": meta.get("currentResourceSummary"),
            "RecommendedResourceSummary": meta.get("recommendedResourceSummary"),
            "ActionRationale": rationale,
        }

        recs.append({
            "unique_id": _rec_id(
                "cost_optimization_hub_recommendations",
                r.resource_id,
                r.account_id,
                r.region or "us-east-1",
            ),
            "recommendation_type": "cost_optimization_hub_recommendations",
            "region_name": r.region or "us-east-1",
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": attributes,
        })
    return recs


# ---------------------------------------------------------------------------
# Phase A: RDS metric-based recommendations
# ---------------------------------------------------------------------------

_RDS_IDLE_CONN_THRESHOLD = 1.0
_RDS_UNDERUTIL_CPU_THRESHOLD = 10.0


def idle_rds_instances(resources: List[Resource]) -> List[Dict]:
    """RDS instances with near-zero database connections over 7 days."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::RDS::DBInstance":
            continue
        meta = r.metadata_json or {}
        conns = meta.get("connections_avg")
        if conns is None or conns >= _RDS_IDLE_CONN_THRESHOLD:
            continue
        recs.append({
            "unique_id": _rec_id("idle_rds_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "idle_rds_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "DBInstanceClass": meta.get("instance_class"),
                "Engine": meta.get("engine"),
                "ConnectionsAvg7d": conns,
                "ActionRationale": f"Idle: {conns} avg connections over 7 days",
                "BluearchAction": "STOP_OR_DELETE",
            },
        })
    return recs


def underutilized_rds_instances(resources: List[Resource]) -> List[Dict]:
    """RDS instances with low CPU and moderate connections (rightsize candidates)."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::RDS::DBInstance":
            continue
        meta = r.metadata_json or {}
        cpu = meta.get("cpu_avg")
        conns = meta.get("connections_avg")
        if cpu is None or conns is None:
            continue
        # Skip idle (handled separately) and heavily used
        if cpu >= _RDS_UNDERUTIL_CPU_THRESHOLD or conns < _RDS_IDLE_CONN_THRESHOLD:
            continue
        recs.append({
            "unique_id": _rec_id("underutilized_rds_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "underutilized_rds_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "DBInstanceClass": meta.get("instance_class"),
                "Engine": meta.get("engine"),
                "CpuAvgPercent": cpu,
                "ConnectionsAvg7d": conns,
                "ActionRationale": f"Underutilized: CPU {cpu}% avg, {conns} connections",
                "BluearchAction": "RIGHTSIZE",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase A: ALB idle detection
# ---------------------------------------------------------------------------

_ALB_IDLE_REQUEST_THRESHOLD = 100


def idle_application_load_balancers(resources: List[Resource]) -> List[Dict]:
    """Application Load Balancers with near-zero request volume over 7 days."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::ElasticLoadBalancingV2::LoadBalancer/Application":
            continue
        meta = r.metadata_json or {}
        req_count = meta.get("request_count_7d")
        if req_count is None or req_count >= _ALB_IDLE_REQUEST_THRESHOLD:
            continue
        recs.append({
            "unique_id": _rec_id("idle_application_load_balancers", r.resource_id, r.account_id, r.region),
            "recommendation_type": "idle_application_load_balancers",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "Scheme": meta.get("scheme"),
                "RequestCount7d": req_count,
                "ActionRationale": f"Idle: {req_count} requests over 7 days",
                "BluearchAction": "DELETE_IDLE_ALB",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase A: IDLE EC2 instances (stricter than underutilized)
# ---------------------------------------------------------------------------

_EC2_IDLE_CPU_THRESHOLD = 1.0
_EC2_IDLE_NETWORK_THRESHOLD = 5 * 1024 * 1024  # 5 MB over 7 days


def idle_ec2_instances(resources: List[Resource]) -> List[Dict]:
    """EC2 instances with near-zero CPU and network usage (terminate candidates)."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Instance":
            continue
        meta = r.metadata_json or {}
        if meta.get("state") != "running":
            continue
        cpu_avg = meta.get("cpu_avg")
        network_in = meta.get("network_in_bytes")
        if cpu_avg is None or network_in is None:
            continue
        if cpu_avg >= _EC2_IDLE_CPU_THRESHOLD or network_in >= _EC2_IDLE_NETWORK_THRESHOLD:
            continue
        recs.append({
            "unique_id": _rec_id("idle_ec2_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "idle_ec2_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "InstanceType": meta.get("instance_type"),
                "CpuAvgPercent": cpu_avg,
                "NetworkInBytes7d": network_in,
                "ActionRationale": (
                    f"Idle: CPU {cpu_avg}%, network {round(network_in / (1024*1024), 1)} MB over 7 days"
                ),
                "BluearchAction": "TERMINATE",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase B: EC2 snapshots and io volumes
# ---------------------------------------------------------------------------

def outdated_ebs_snapshots(resources: List[Resource], max_age_days: int = 90) -> List[Dict]:
    """EBS snapshots older than the threshold (90 days default)."""
    recs = []
    now = datetime.now(timezone.utc)
    for r in resources:
        if r.resource_type != "AWS::EC2::Snapshot":
            continue
        if not r.created_at:
            continue
        created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        if age_days <= max_age_days:
            continue
        meta = r.metadata_json or {}
        recs.append({
            "unique_id": _rec_id("outdated_ebs_snapshots", r.resource_id, r.account_id, r.region),
            "recommendation_type": "outdated_ebs_snapshots",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "VolumeId": meta.get("volume_id"),
                "VolumeSize": meta.get("volume_size"),
                "AgeDays": age_days,
                "ActionRationale": f"Snapshot is {age_days} days old",
                "BluearchAction": "DELETE_SNAPSHOT",
            },
        })
    return recs


def io_volume_type_non_optimized(resources: List[Resource]) -> List[Dict]:
    """io1/io2 volumes with <=16000 IOPS that could migrate to cheaper gp3."""
    recs = []
    for r in resources:
        if r.resource_type != "AWS::EC2::Volume":
            continue
        meta = r.metadata_json or {}
        vol_type = meta.get("volume_type", "")
        if vol_type not in ("io1", "io2"):
            continue
        iops = meta.get("iops") or 0
        if iops > 16000:
            continue  # High IOPS workload, needs io1/io2
        recs.append({
            "unique_id": _rec_id("io_volume_type_non_optimized", r.resource_id, r.account_id, r.region),
            "recommendation_type": "io_volume_type_non_optimized",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "VolumeType": vol_type,
                "IOPS": iops,
                "Size": meta.get("size_gb"),
                "ActionRationale": f"{vol_type} with {iops} IOPS can be migrated to gp3",
                "BluearchAction": "MIGRATE_TO_GP3",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase C: Reserved Instances expiring soon
# ---------------------------------------------------------------------------

def expiring_ec2_reserved_instances(resources: List[Resource], warning_days: int = 30) -> List[Dict]:
    """EC2 Reserved Instances expiring within the warning window."""
    recs = []
    now = datetime.now(timezone.utc)
    for r in resources:
        if r.resource_type != "AWS::EC2::ReservedInstances":
            continue
        meta = r.metadata_json or {}
        end_str = meta.get("end_time")
        if not end_str:
            continue
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = (end - now).days
        if days_left < 0 or days_left > warning_days:
            continue
        recs.append({
            "unique_id": _rec_id("expiring_ec2_reserved_instances", r.resource_id, r.account_id, r.region),
            "recommendation_type": "expiring_ec2_reserved_instances",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "InstanceType": meta.get("instance_type"),
                "InstanceCount": meta.get("instance_count"),
                "OfferingType": meta.get("offering_type"),
                "EndTime": end_str,
                "DaysUntilExpiration": days_left,
                "ActionRationale": f"Reserved Instance expires in {days_left} days",
                "BluearchAction": "RENEW_OR_PURCHASE_NEW_RI",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase D: IAM inactive roles (with RoleLastUsed)
# ---------------------------------------------------------------------------

def inactive_iam_roles_impl(resources: List[Resource], warning_days: int = 30) -> List[Dict]:
    """IAM roles not used within the threshold period (uses RoleLastUsed metadata)."""
    recs = []
    now = datetime.now(timezone.utc)
    for r in resources:
        if r.resource_type != "AWS::IAM::Role":
            continue
        meta = r.metadata_json or {}
        path = meta.get("path", "/")
        # Skip AWS-managed and service-linked roles
        if path.startswith("/aws-service-role/") or path.startswith("/aws-reserved/"):
            continue
        last_used_str = meta.get("last_used_date")

        if last_used_str:
            try:
                last_used = datetime.fromisoformat(last_used_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if last_used.tzinfo is None:
                last_used = last_used.replace(tzinfo=timezone.utc)
            days_since = (now - last_used).days
            reason = f"Not used for {days_since} days"
        elif r.created_at:
            created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
            days_since = (now - created).days
            reason = f"Never used (created {days_since} days ago)"
        else:
            continue

        if days_since <= warning_days:
            continue

        recs.append({
            "unique_id": _rec_id("inactive_iam_roles", r.resource_id, r.account_id, "global"),
            "recommendation_type": "inactive_iam_roles",
            "region_name": "global",
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "RoleName": r.resource_id,
                "Path": path,
                "LastUsed": last_used_str or "never",
                "DaysSinceUsed": days_since,
                "ActionRationale": reason,
                "BluearchAction": "REVIEW_OR_DELETE_ROLE",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Phase E: ElastiCache — on-demand without reservation
# ---------------------------------------------------------------------------

def old_on_demand_elasticache(resources: List[Resource], min_age_days: int = 30) -> List[Dict]:
    """ElastiCache clusters running on-demand (no matching RI) for >30 days."""
    recs = []
    now = datetime.now(timezone.utc)
    for r in resources:
        if r.resource_type != "AWS::ElastiCache::CacheCluster":
            continue
        meta = r.metadata_json or {}
        if not meta.get("is_on_demand"):
            continue
        if not r.created_at:
            continue
        created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        if age_days < min_age_days:
            continue
        recs.append({
            "unique_id": _rec_id("old_on_demand_elasticache", r.resource_id, r.account_id, r.region),
            "recommendation_type": "old_on_demand_elasticache",
            "region_name": r.region,
            "account_id": r.account_id,
            "db_resource_id": r.id,
            "attributes": {
                "resource_id": r.resource_id,
                "NodeType": meta.get("cache_node_type"),
                "Engine": meta.get("engine"),
                "AgeDays": age_days,
                "ActionRationale": f"Running on-demand for {age_days} days without a reservation",
                "BluearchAction": "PURCHASE_RESERVED_NODES",
            },
        })
    return recs


# ---------------------------------------------------------------------------
# Recommendation Registry + Runner
# ---------------------------------------------------------------------------

# Functions that analyze locally-collected resources
RECOMMENDATION_FUNCTIONS = [
    # EC2 core
    unattached_ec2_volumes,
    previous_gen_ec2_volumes,
    unencrypted_ec2_volumes,
    previous_gen_ec2_instances,
    old_stopped_ec2_instances,
    # EC2 metric-based
    underutilized_ec2_instances,
    idle_ec2_instances,
    # EC2 additions
    outdated_ebs_snapshots,
    io_volume_type_non_optimized,
    expiring_ec2_reserved_instances,
    # Network / IP hygiene
    unused_security_groups,
    unattached_elastic_ips,
    # RDS
    previous_gen_rds_instances,
    unencrypted_rds_instances,
    idle_rds_instances,
    underutilized_rds_instances,
    # ELB
    idle_application_load_balancers,
    # IAM
    expired_iam_keys,
    inactive_iam_roles_impl,
    # ElastiCache
    old_on_demand_elasticache,
    # Cost Optimization Hub
    cost_optimization_hub_recommendations,
    # Compute Optimizer (28 mapper functions — EC2/EBS/Lambda/ASG/ECS/RDS)
    *COMPUTE_OPTIMIZER_RECOMMENDATION_FUNCTIONS,
]


def run_recommendations(account_id: Optional[str] = None) -> Dict[str, int]:
    """Run all recommendation functions against collected resources.

    Args:
        account_id: Optional filter to run only for a specific account.

    Returns:
        Dict mapping recommendation_type to count of findings.
    """
    filters = [("account_id", account_id)] if account_id else None
    resources = list_objects("core", "resources", filters=filters)
    if not resources:
        log.debug("No resources to analyze")
        return {}

    summary = {}
    for func in RECOMMENDATION_FUNCTIONS:
        try:
            recs = func(resources)
            if recs:
                _upsert_recommendations(recs)
                rec_type = recs[0]["recommendation_type"]
                summary[rec_type] = len(recs)
                log.debug(f"{rec_type}: {len(recs)} findings")
        except Exception as e:
            log.debug(f"Recommendation function {func.__name__} error: {e}")

    return summary
