"""Local service collectors — output format identical to tag-manager CLI.

Each collector produces resource dicts with the same field names, resource_type
strings, and metadata_json keys as the tag-manager CLI's discovery.py. This
ensures both CLIs can share a single SQLite database.

Compatibility rules (from side-by-side analysis):
- resource_type strings must match tag-manager exactly
- metadata_json field names must match tag-manager exactly
- service_name must match tag-manager exactly
- Tags must be collected (not left empty)
- ELB resource_type gets /Network or /Application suffix
"""

import csv
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, ParamValidationError

from modules.collection.models import CollectionJob, CollectorResult
from utils.logger_config import log


PUBLIC_GRANTEE_URIS = {
    "http://acs.amazonaws.com/groups/global/AllUsers",
    "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
}


def _client_error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _principal_is_public(principal: Any) -> bool:
    if principal == "*":
        return True
    if isinstance(principal, dict):
        aws_principals = _as_list(principal.get("AWS"))
        return any(item == "*" for item in aws_principals)
    return False


def _action_includes_all_s3(actions: Any) -> bool:
    for action in _as_list(actions):
        action_name = str(action).lower()
        if action_name in {"*", "s3:*"}:
            return True
    return False


def _action_includes_s3_delete(actions: Any) -> bool:
    for action in _as_list(actions):
        action_name = str(action).lower()
        if action_name in {"*", "s3:*"} or action_name.startswith("s3:delete"):
            return True
    return False


def _action_matches_any(actions: Any, expected: set) -> bool:
    for action in _as_list(actions):
        action_name = str(action).lower()
        if action_name in expected:
            return True
    return False


def _denies_insecure_transport(statement: Dict[str, Any]) -> bool:
    condition = statement.get("Condition") or {}
    for operator, entries in condition.items():
        if str(operator).lower() not in {"bool", "boolifexists"} or not isinstance(entries, dict):
            continue
        secure_transport = entries.get("aws:SecureTransport")
        if secure_transport is None:
            continue
        if any(str(value).lower() == "false" for value in _as_list(secure_transport)):
            return True
    return False


def _empty_s3_policy_analysis() -> Dict[str, bool]:
    return {
        "bucket_policy_allows_all_principals_all_actions": False,
        "bucket_policy_allows_public_delete_actions": False,
        "bucket_policy_enforces_ssl": False,
        "bucket_policy_enforces_encrypted_writes": False,
    }


def _statement_denies_unencrypted_put_object(statement: Dict[str, Any]) -> bool:
    if str(statement.get("Effect", "")).lower() != "deny":
        return False
    if not _action_matches_any(statement.get("Action"), {"s3:putobject", "s3:*", "*"}):
        return False
    condition = statement.get("Condition") or {}
    for operator, entries in condition.items():
        operator_name = str(operator).lower()
        if operator_name not in {
            "stringnotequals",
            "stringnotequalsifexists",
            "null",
        } or not isinstance(entries, dict):
            continue
        for key, value in entries.items():
            key_name = str(key).lower()
            values = [str(item).lower() for item in _as_list(value)]
            if key_name == "s3:x-amz-server-side-encryption" and any(
                item in {"aws:kms", "aes256"} for item in values
            ):
                return True
            if key_name == "s3:x-amz-server-side-encryption" and operator_name == "null":
                return True
    return False


def _analyze_s3_bucket_policy(policy_text: str) -> Dict[str, bool]:
    analysis = _empty_s3_policy_analysis()
    try:
        policy = json.loads(policy_text or "{}")
    except (TypeError, json.JSONDecodeError):
        return analysis

    statements = policy.get("Statement", [])
    for statement in _as_list(statements):
        if not isinstance(statement, dict):
            continue

        effect = str(statement.get("Effect", "")).lower()
        principal_is_public = _principal_is_public(statement.get("Principal"))
        action = statement.get("Action")

        if effect == "allow" and principal_is_public:
            if _action_includes_all_s3(action):
                analysis["bucket_policy_allows_all_principals_all_actions"] = True
            if _action_includes_s3_delete(action):
                analysis["bucket_policy_allows_public_delete_actions"] = True

        if (
            effect == "deny"
            and principal_is_public
            and _action_includes_all_s3(action)
            and _denies_insecure_transport(statement)
        ):
            analysis["bucket_policy_enforces_ssl"] = True
        if _statement_denies_unencrypted_put_object(statement):
            analysis["bucket_policy_enforces_encrypted_writes"] = True

    return analysis


def _age_days(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - value).days, 0)


def _days_until(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (value - datetime.now(timezone.utc)).days


def _certificate_key_size_bits(key_algorithm: Optional[str]) -> Optional[int]:
    if not key_algorithm or not str(key_algorithm).startswith("RSA_"):
        return None
    try:
        return int(str(key_algorithm).split("_", 1)[1])
    except (IndexError, ValueError):
        return None


def _acm_certificate_expiry_metadata(session, region: str, certificate_arns: List[str]) -> Dict[str, Any]:
    acm_arns = sorted({arn for arn in certificate_arns if str(arn).startswith("arn:aws:acm:")})
    if not acm_arns:
        return {
            "listener_certificate_arns": sorted(set(certificate_arns)),
            "listener_certificate_min_days_until_expiration": None,
            "listener_certificates_expiring_within_30_days": [],
            "listener_certificates_expiring_within_7_days": [],
        }

    acm = session.client("acm", region_name=region) if session else boto3.client("acm", region_name=region)
    days_by_arn = {}
    for arn in acm_arns:
        try:
            certificate = acm.describe_certificate(CertificateArn=arn).get("Certificate", {})
        except ClientError:
            continue
        days_until_expiration = _days_until(certificate.get("NotAfter"))
        if days_until_expiration is not None:
            days_by_arn[arn] = days_until_expiration

    return {
        "listener_certificate_arns": sorted(set(certificate_arns)),
        "listener_certificate_min_days_until_expiration": (
            min(days_by_arn.values()) if days_by_arn else None
        ),
        "listener_certificates_expiring_within_30_days": sorted(
            arn for arn, days in days_by_arn.items() if days <= 30
        ),
        "listener_certificates_expiring_within_7_days": sorted(
            arn for arn, days in days_by_arn.items() if days <= 7
        ),
    }


PUBLIC_IPV4_CIDRS = {"0.0.0.0/0"}
PUBLIC_IPV6_CIDRS = {"::/0"}
MANAGEMENT_PORTS = {
    22: "ssh",
    3389: "rdp",
    443: "https",
    8443: "https-alt",
}


def _permission_has_public_range(permission: Dict[str, Any]) -> bool:
    for ip_range in permission.get("IpRanges") or []:
        if ip_range.get("CidrIp") in PUBLIC_IPV4_CIDRS:
            return True
    for ip_range in permission.get("Ipv6Ranges") or []:
        if ip_range.get("CidrIpv6") in PUBLIC_IPV6_CIDRS:
            return True
    return False


def _permission_covers_port(permission: Dict[str, Any], port: int) -> bool:
    protocol = str(permission.get("IpProtocol", ""))
    if protocol == "-1":
        return True
    if protocol not in {"tcp", "6", "udp", "17"}:
        return False
    from_port = permission.get("FromPort")
    to_port = permission.get("ToPort")
    if from_port is None or to_port is None:
        return False
    return int(from_port) <= port <= int(to_port)


def _permission_covers_all_ports(permission: Dict[str, Any]) -> bool:
    protocol = str(permission.get("IpProtocol", ""))
    if protocol == "-1":
        return True
    from_port = permission.get("FromPort")
    to_port = permission.get("ToPort")
    if from_port is None or to_port is None:
        return False
    return int(from_port) <= 0 and int(to_port) >= 65535


def _analyze_security_group_rules(ingress_rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    public_ports = set()
    public_all_ports = False
    public_ingress = False
    for permission in ingress_rules or []:
        if not _permission_has_public_range(permission):
            continue
        public_ingress = True
        if _permission_covers_all_ports(permission):
            public_all_ports = True
        for port, name in MANAGEMENT_PORTS.items():
            if _permission_covers_port(permission, port):
                public_ports.add(name)

    return {
        "public_ingress": public_ingress,
        "public_all_ports": public_all_ports,
        "public_management_ports": sorted(public_ports),
        "public_ssh": "ssh" in public_ports,
        "public_rdp": "rdp" in public_ports,
    }


def _count_security_group_rules(rules: List[Dict[str, Any]]) -> int:
    """Count concrete security group rules, including each source/destination."""
    count = 0
    for rule in rules or []:
        sources = (
            len(rule.get("IpRanges") or [])
            + len(rule.get("Ipv6Ranges") or [])
            + len(rule.get("UserIdGroupPairs") or [])
            + len(rule.get("PrefixListIds") or [])
        )
        count += max(1, sources)
    return count


PERMISSION_RESOURCE_TYPES: Dict[str, List[str]] = {
    "EC2 instances": ["AWS::EC2::Instance"],
    "EBS volumes": ["AWS::EC2::Volume"],
    "EBS snapshots": ["AWS::EC2::Snapshot"],
    "Elastic IPs": ["AWS::EC2::EIP"],
    "Reserved Instances": ["AWS::EC2::ReservedInstances"],
    "S3": ["AWS::S3::Bucket"],
    "Lambda": ["AWS::Lambda::Function"],
    "RDS instances": ["AWS::RDS::DBInstance"],
    "RDS clusters": ["AWS::RDS::DBCluster"],
    "DynamoDB": ["AWS::DynamoDB::Table"],
    "ECS": ["AWS::ECS::Cluster", "AWS::ECS::Service", "AWS::ECS::TaskDefinition"],
    "ECS task definitions": ["AWS::ECS::TaskDefinition"],
    "ELB": [
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Application",
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Network",
    ],
    "SNS": ["AWS::SNS::Topic"],
    "SQS": ["AWS::SQS::Queue"],
    "CloudWatch alarms": ["AWS::CloudWatch::Alarm"],
    "CloudWatch log groups": ["AWS::Logs::LogGroup"],
    "CloudTrail": ["AWS::CloudTrail::Region", "AWS::CloudTrail::Trail"],
    "EKS": ["AWS::EKS::Cluster"],
    "GuardDuty": ["AWS::GuardDuty::Region", "AWS::EKS::Cluster"],
    "Account": ["AWS::Account::Account"],
    "Organizations": ["AWS::Organizations::Organization"],
    "AWS Config": ["AWS::Config::ConfigurationRecorder"],
    "Route 53": ["AWS::Route53::RecordSet"],
    "Redshift": ["AWS::Redshift::Cluster"],
    "Kinesis": ["AWS::Kinesis::Stream"],
    "ACM certificates": ["AWS::CertificateManager::Certificate"],
    "CloudFront": ["AWS::CloudFront::Distribution"],
    "Inspector": ["AWS::InspectorV2::Finding"],
    "Security Hub": ["AWS::SecurityHub::Region"],
    "ElastiCache": ["AWS::ElastiCache::CacheCluster"],
    "ElastiCache reservations": ["AWS::ElastiCache::CacheCluster"],
    "EFS": ["AWS::EFS::FileSystem"],
    "VPCs": ["AWS::EC2::VPC"],
    "Security Groups": ["AWS::EC2::SecurityGroup"],
    "IAM account": ["AWS::IAM::Account"],
    "IAM roles": ["AWS::IAM::Role"],
    "IAM users": ["AWS::IAM::User"],
    "IAM keys": ["AWS::IAM::AccessKey"],
    "Logs Insights": ["AWS::Logs::LogGroup"],
    "Log Analysis": ["AWS::Logs::LogGroup"],
    "Cost Optimization Hub": ["AWS::CostOptimizationHub::Recommendation"],
    "ComputeOptimizer EC2": ["AWS::ComputeOptimizer::EC2InstanceRecommendation"],
    "ComputeOptimizer EBS": ["AWS::ComputeOptimizer::EBSVolumeRecommendation"],
    "ComputeOptimizer Lambda": ["AWS::ComputeOptimizer::LambdaFunctionRecommendation"],
    "ComputeOptimizer ASG": ["AWS::ComputeOptimizer::AutoScalingGroupRecommendation"],
    "ComputeOptimizer ECS": ["AWS::ComputeOptimizer::ECSServiceRecommendation"],
    "ComputeOptimizer RDS": ["AWS::ComputeOptimizer::RDSDatabaseRecommendation"],
}


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ServiceCollector:
    """Base class for all service collectors."""

    MAX_RETRIES = 3
    BASE_BACKOFF = 0.5
    THROTTLE_CODES = ["Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException"]

    def collect(self, job: CollectionJob) -> CollectorResult:
        raise NotImplementedError

    def _get_client(self, service_name: str, region: Optional[str], session=None):
        if session:
            return session.client(service_name, region_name=region)
        kwargs = {}
        if region:
            kwargs["region_name"] = region
        return boto3.client(service_name, **kwargs)

    def _paginate(self, client, method, result_key, **kwargs):
        paginator = client.get_paginator(method)
        items = []
        for page in paginator.paginate(**kwargs):
            items.extend(page.get(result_key, []))
        return items

    def _paginate_with_retry(self, client, method, result_key, **kwargs):
        for attempt in range(self.MAX_RETRIES):
            try:
                return self._paginate(client, method, result_key, **kwargs)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in self.THROTTLE_CODES and attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.BASE_BACKOFF * (2 ** attempt))
                    continue
                raise

    @staticmethod
    def _is_permission_error(e: ClientError) -> bool:
        code = e.response.get("Error", {}).get("Code", "")
        return code in ("AccessDenied", "AccessDeniedException", "UnauthorizedAccess", "AuthorizationError")

    @staticmethod
    def _extract_tags(tag_list: Optional[List[Dict]]) -> Dict[str, str]:
        if not tag_list:
            return {}
        return {t.get("Key", ""): t.get("Value", "") for t in tag_list if "Key" in t}

    def _record_permission_error(
        self,
        result: CollectorResult,
        region: Optional[str],
        service: str,
        exc: Exception,
        account_id: Optional[str] = None,
    ) -> None:
        """Record a frontend/CLI-visible permission failure."""
        code = ""
        message = str(exc)
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            code = error.get("Code", "")
            message = error.get("Message") or message

        resource_types = list(PERMISSION_RESOURCE_TYPES.get(service, []))
        result.permission_errors += 1
        result.permission_error_details.append({
            "type": "permission_denied",
            "service": service,
            "region": region or "global",
            "account_id": account_id,
            "code": code or type(exc).__name__,
            "message": f"{service} in {region or 'global'} was not collected: {message}",
            "resource_types": resource_types,
            "suggestion": (
                "Update the BlueArchRole StackSet or assume-role policy for these resource types, "
                "then rerun the scan."
            ),
        })

    def _safe_collect(self, result, region, service, fn):
        """Run a collection function with standard error handling."""
        try:
            fn()
        except ClientError as e:
            if self._is_permission_error(e):
                self._record_permission_error(result, region, service, e)
                log.warning("%s in %s: permission denied (%s)", service, region, e.response.get("Error", {}).get("Code", ""))
            else:
                result.errors.append(f"{service} error in {region}: {e}")
                log.warning("%s in %s: %s", service, region, e)
        except Exception as e:
            # Any non-ClientError (KeyError, TypeError, …) was previously
            # silent: it bubbled to the scanner loop and got logged at debug.
            # Surface it at warning so missing resources are diagnosable.
            result.errors.append(f"{service} unexpected error in {region}: {e}")
            log.warning("%s in %s: unexpected %s: %s", service, region, type(e).__name__, e)


# ---------------------------------------------------------------------------
# CloudWatch metrics helper — fetches CPU/Network for EC2 instances
# ---------------------------------------------------------------------------

def _parse_lambda_timestamp(value) -> Optional[datetime]:
    """Lambda's LastModified comes back as a string like
    '2024-01-02T03:04:05.000+0000'. Return a timezone-aware ``datetime`` or
    ``None`` if parsing fails (the DateTime column accepts either, but a
    string would blow up the whole collector run for this region)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    for candidate in (value, value.replace("+0000", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _parse_epoch_string(value) -> Optional[datetime]:
    """SQS CreatedTimestamp arrives as a string containing a unix epoch
    (e.g. '1700000000'). Return a timezone-aware ``datetime`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _get_cw_client(session, region: str):
    """Return a CloudWatch client bound to the scan session (or default)."""
    if session:
        return session.client("cloudwatch", region_name=region)
    return boto3.client("cloudwatch", region_name=region)


def _metric_stat(cw, namespace: str, metric: str, dimensions: list, stat: str = "Average", days: int = 7) -> Optional[float]:
    """Fetch a single CloudWatch metric aggregated over N days.

    Returns None if no datapoints are available (new resource, stopped, etc.).
    """
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=[stat],
        )
        dps = resp.get("Datapoints", [])
        if not dps:
            return None
        if stat == "Sum":
            return float(sum(d["Sum"] for d in dps))
        if stat == "Maximum":
            return float(max(d["Maximum"] for d in dps))
        # default: Average
        return round(sum(d["Average"] for d in dps) / len(dps), 2)
    except Exception:
        return None


def _metric_daily_series(
    cw,
    namespace: str,
    metric: str,
    dimensions: list,
    stat: str = "Average",
    days: int = 14,
) -> Dict[str, float]:
    """Fetch one datapoint per day for rules that require day counts."""
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=[stat],
        )
        values = {}
        for dp in resp.get("Datapoints", []):
            if stat in dp:
                timestamp = dp.get("Timestamp")
                if isinstance(timestamp, datetime):
                    values[timestamp.date().isoformat()] = float(dp[stat])
        return values
    except Exception:
        return {}


def _collect_cloudwatch_metrics(session, instance_ids: List[str], region: str) -> Dict[str, Dict]:
    """Fetch CPU and Network metrics for EC2 instances over lookback windows."""
    if not instance_ids:
        return {}

    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for iid in instance_ids:
        try:
            dims = [{"Name": "InstanceId", "Value": iid}]
            cpu = _metric_stat(cw, "AWS/EC2", "CPUUtilization", dims, "Average")
            net_in = _metric_stat(cw, "AWS/EC2", "NetworkIn", dims, "Sum")
            net_out = _metric_stat(cw, "AWS/EC2", "NetworkOut", dims, "Sum")
            cpu_series = _metric_daily_series(cw, "AWS/EC2", "CPUUtilization", dims, "Average", days=14)
            net_in_series = _metric_daily_series(cw, "AWS/EC2", "NetworkIn", dims, "Sum", days=14)
            net_out_series = _metric_daily_series(cw, "AWS/EC2", "NetworkOut", dims, "Sum", days=14)
            cpu_days = [value for _, value in sorted(cpu_series.items())]
            observed_dates = sorted(set(cpu_series) & set(net_in_series) & set(net_out_series))
            observed_days = len(observed_dates)
            idle_days = 0
            for day in observed_dates:
                network_bytes = net_in_series[day] + net_out_series[day]
                if cpu_series[day] < 5 and network_bytes <= 5 * 1024 * 1024:
                    idle_days += 1
            metrics[iid] = {
                "cpu_avg": cpu if cpu is not None else 0.0,
                "network_in_bytes": int(net_in) if net_in is not None else 0,
                "network_out_bytes": int(net_out) if net_out is not None else 0,
                "cpu_avg_14d": round(sum(cpu_days) / len(cpu_days), 2) if cpu_days else None,
                "metric_observed_days_14d": observed_days,
                "idle_days_14d": idle_days if observed_days else None,
                "high_cpu_days_14d": sum(1 for value in cpu_days if value > 90) if cpu_days else None,
                "very_low_cpu_days_14d": sum(1 for value in cpu_days if value <= 2) if cpu_days else None,
            }
        except Exception:
            pass

    return metrics


def _collect_rds_metrics(session, db_ids: List[str], region: str) -> Dict[str, Dict]:
    """Fetch CPU, DatabaseConnections, and FreeableMemory for RDS instances (7 days)."""
    if not db_ids:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for db_id in db_ids:
        try:
            dims = [{"Name": "DBInstanceIdentifier", "Value": db_id}]
            cpu = _metric_stat(cw, "AWS/RDS", "CPUUtilization", dims, "Average")
            conns = _metric_stat(cw, "AWS/RDS", "DatabaseConnections", dims, "Average")
            mem = _metric_stat(cw, "AWS/RDS", "FreeableMemory", dims, "Average")
            free_storage = _metric_stat(cw, "AWS/RDS", "FreeStorageSpace", dims, "Average")
            metrics[db_id] = {
                "cpu_avg": cpu if cpu is not None else 0.0,
                "connections_avg": conns if conns is not None else 0.0,
                "freeable_memory_bytes": int(mem) if mem is not None else 0,
                "free_storage_space_bytes": int(free_storage) if free_storage is not None else None,
            }
        except Exception:
            pass
    return metrics


def _collect_elb_metrics(session, lb_full_names: List[str], region: str, v2: bool = True) -> Dict[str, Dict]:
    """Fetch RequestCount for ALB/NLB (v2) or classic ELB over 7 days."""
    if not lb_full_names:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    namespace = "AWS/ApplicationELB" if v2 else "AWS/ELB"
    dim_name = "LoadBalancer" if v2 else "LoadBalancerName"
    metric_name = "RequestCount"
    for lb in lb_full_names:
        try:
            dims = [{"Name": dim_name, "Value": lb}]
            req = _metric_stat(cw, namespace, metric_name, dims, "Sum")
            metrics[lb] = {"request_count_7d": int(req) if req is not None else 0}
        except Exception:
            pass
    return metrics


def _collect_elasticache_metrics(session, cluster_ids: List[str], region: str) -> Dict[str, Dict]:
    """Fetch CPU + CurrConnections for ElastiCache clusters over 7 days."""
    if not cluster_ids:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for cid in cluster_ids:
        try:
            dims = [{"Name": "CacheClusterId", "Value": cid}]
            cpu = _metric_stat(cw, "AWS/ElastiCache", "CPUUtilization", dims, "Average")
            conns = _metric_stat(cw, "AWS/ElastiCache", "CurrConnections", dims, "Average")
            metrics[cid] = {
                "cpu_avg": cpu if cpu is not None else 0.0,
                "connections_avg": conns if conns is not None else 0.0,
            }
        except Exception:
            pass
    return metrics


def _metric_sum_over_days(
    cw,
    namespace: str,
    metric: str,
    dimensions: list,
    days: int = 14,
) -> Optional[float]:
    """Fetch summed CloudWatch usage over a lookback window.

    Empty datapoints mean no recorded usage, while exceptions mean unknown.
    """
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
        )
        datapoints = resp.get("Datapoints", [])
        if not datapoints:
            return 0.0
        return float(sum(point.get("Sum", 0.0) for point in datapoints))
    except Exception:
        return None


def _collect_dynamodb_metrics(session, table_names: List[str], region: str, days: int = 14) -> Dict[str, Dict]:
    """Fetch DynamoDB consumed capacity metrics over a lookback window."""
    if not table_names:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    seconds = days * 86400
    for table_name in table_names:
        dimensions = [{"Name": "TableName", "Value": table_name}]
        read_sum = _metric_sum_over_days(
            cw,
            "AWS/DynamoDB",
            "ConsumedReadCapacityUnits",
            dimensions,
            days=days,
        )
        write_sum = _metric_sum_over_days(
            cw,
            "AWS/DynamoDB",
            "ConsumedWriteCapacityUnits",
            dimensions,
            days=days,
        )
        throttled_requests = _metric_sum_over_days(
            cw,
            "AWS/DynamoDB",
            "ThrottledRequests",
            dimensions,
            days=days,
        )
        metrics[table_name] = {
            "capacity_metric_lookback_days": days,
            "consumed_read_capacity_units_lookback": read_sum,
            "consumed_write_capacity_units_lookback": write_sum,
            "throttled_requests_lookback": throttled_requests,
            "avg_read_capacity_units_per_second": (
                round(read_sum / seconds, 6) if read_sum is not None else None
            ),
            "avg_write_capacity_units_per_second": (
                round(write_sum / seconds, 6) if write_sum is not None else None
            ),
        }
    return metrics


def _collect_efs_metrics(session, file_system_ids: List[str], region: str) -> Dict[str, Dict]:
    """Fetch EFS client connection and IO metrics over 14 days."""
    if not file_system_ids:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for fs_id in file_system_ids:
        try:
            dims = [{"Name": "FileSystemId", "Value": fs_id}]
            client_connections = _metric_stat(
                cw,
                "AWS/EFS",
                "ClientConnections",
                dims,
                "Maximum",
                days=14,
            )
            total_io_bytes = _metric_stat(
                cw,
                "AWS/EFS",
                "TotalIOBytes",
                dims,
                "Sum",
                days=14,
            )
            metrics[fs_id] = {
                "efs_metric_lookback_days": 14,
                "client_connections_max_14d": int(client_connections) if client_connections is not None else None,
                "total_io_bytes_14d": int(total_io_bytes) if total_io_bytes is not None else None,
            }
        except Exception:
            pass
    return metrics


def _collect_redshift_metrics(session, cluster_ids: List[str], region: str) -> Dict[str, Dict]:
    """Fetch Redshift CPU and connection metrics over 7 days."""
    if not cluster_ids:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for cluster_id in cluster_ids:
        try:
            dims = [{"Name": "ClusterIdentifier", "Value": cluster_id}]
            cpu = _metric_stat(cw, "AWS/Redshift", "CPUUtilization", dims, "Average", days=7)
            connections = _metric_stat(cw, "AWS/Redshift", "DatabaseConnections", dims, "Maximum", days=7)
            metrics[cluster_id] = {
                "redshift_metric_lookback_days": 7,
                "cpu_avg_7d": cpu,
                "database_connections_max_7d": int(connections) if connections is not None else None,
            }
        except Exception:
            pass
    return metrics


def _collect_lambda_metrics(session, function_names: List[str], region: str, days: int = 7) -> Dict[str, Dict]:
    """Fetch Lambda invocation, error, and throttle metrics over a lookback window."""
    if not function_names:
        return {}
    cw = _get_cw_client(session, region)
    metrics: Dict[str, Dict] = {}
    for function_name in function_names:
        dimensions = [{"Name": "FunctionName", "Value": function_name}]
        invocations = _metric_sum_over_days(
            cw,
            "AWS/Lambda",
            "Invocations",
            dimensions,
            days=days,
        )
        errors = _metric_sum_over_days(
            cw,
            "AWS/Lambda",
            "Errors",
            dimensions,
            days=days,
        )
        throttles = _metric_sum_over_days(
            cw,
            "AWS/Lambda",
            "Throttles",
            dimensions,
            days=days,
        )
        metrics[function_name] = {
            "lambda_metric_lookback_days": days,
            "invocations_lookback": invocations,
            "errors_lookback": errors,
            "throttles_lookback": throttles,
            "error_rate": (
                round(errors / invocations, 6)
                if errors is not None and invocations
                else None
            ),
        }
    return metrics


def _collect_guardduty_eks_runtime_status(session, region: str) -> Dict[str, Optional[bool]]:
    """Return region-level GuardDuty EKS runtime monitoring status."""
    guardduty = session.client("guardduty", region_name=region) if session else boto3.client("guardduty", region_name=region)
    try:
        detector_ids = []
        paginator = guardduty.get_paginator("list_detectors")
        for page in paginator.paginate():
            detector_ids.extend(page.get("DetectorIds", []))
    except ClientError:
        return {
            "guardduty_detector_present": None,
            "guardduty_runtime_monitoring_enabled": None,
            "guardduty_eks_addon_management_enabled": None,
        }

    if not detector_ids:
        return {
            "guardduty_detector_present": False,
            "guardduty_runtime_monitoring_enabled": False,
            "guardduty_eks_addon_management_enabled": False,
        }

    runtime_enabled = False
    addon_management_enabled = False
    for detector_id in detector_ids:
        try:
            detector = guardduty.get_detector(DetectorId=detector_id)
        except ClientError:
            continue
        for feature in detector.get("Features", []) or []:
            feature_name = feature.get("Name")
            feature_enabled = feature.get("Status") == "ENABLED"
            if feature_name in {"EKS_RUNTIME_MONITORING", "RUNTIME_MONITORING"} and feature_enabled:
                runtime_enabled = True
            for additional in feature.get("AdditionalConfiguration", []) or []:
                if additional.get("Name") == "EKS_ADDON_MANAGEMENT" and additional.get("Status") == "ENABLED":
                    addon_management_enabled = True

    return {
        "guardduty_detector_present": True,
        "guardduty_runtime_monitoring_enabled": runtime_enabled,
        "guardduty_eks_addon_management_enabled": addon_management_enabled,
    }


def _get_wafv2_web_acl_for_resource(session, region: str, resource_arn: str) -> Dict[str, Any]:
    """Return WAFv2 association metadata for a regional resource."""
    wafv2 = session.client("wafv2", region_name=region) if session else boto3.client("wafv2", region_name=region)
    try:
        web_acl = wafv2.get_web_acl_for_resource(ResourceArn=resource_arn).get("WebACL")
    except ClientError as exc:
        code = _client_error_code(exc)
        if code in {"WAFNonexistentItemException", "WAFUnavailableEntityException"}:
            return {
                "web_acl_attached": False,
                "web_acl_arn": None,
                "web_acl_name": None,
                "web_acl_status": "none",
            }
        if ServiceCollector._is_permission_error(exc):
            return {
                "web_acl_attached": None,
                "web_acl_arn": None,
                "web_acl_name": None,
                "web_acl_status": "unknown_permission_denied",
            }
        return {
            "web_acl_attached": None,
            "web_acl_arn": None,
            "web_acl_name": None,
            "web_acl_status": f"unknown_{code or 'error'}",
        }

    if not web_acl:
        return {
            "web_acl_attached": False,
            "web_acl_arn": None,
            "web_acl_name": None,
            "web_acl_status": "none",
        }

    return {
        "web_acl_attached": True,
        "web_acl_arn": web_acl.get("ARN"),
        "web_acl_name": web_acl.get("Name"),
        "web_acl_status": "attached",
    }


# ---------------------------------------------------------------------------
# EC2 Collector — instances, volumes, snapshots, AMIs, EIPs
# ---------------------------------------------------------------------------

class EC2Collector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        ec2 = self._get_client("ec2", region, job.session)

        # Track running instance IDs for CloudWatch metrics enrichment
        running_instance_ids: List[str] = []
        instance_ebs_optimized: Dict[str, Optional[bool]] = {}
        existing_volume_ids: Optional[set] = None
        sg_rule_counts: Dict[str, int] = {}
        sg_ssh_access: Dict[str, bool] = {}
        try:
            for sg in self._paginate_with_retry(ec2, "describe_security_groups", "SecurityGroups"):
                gid = sg.get("GroupId")
                if not gid:
                    continue
                ingress_rules = sg.get("IpPermissions") or []
                sg_rule_counts[gid] = (
                    _count_security_group_rules(ingress_rules)
                    + _count_security_group_rules(sg.get("IpPermissionsEgress") or [])
                )
                sg_ssh_access[gid] = any(_permission_covers_port(rule, 22) for rule in ingress_rules)
        except Exception:
            sg_rule_counts = {}
            sg_ssh_access = {}

        # Instances
        def _instances():
            reservations = self._paginate_with_retry(ec2, "describe_instances", "Reservations")
            for res in reservations:
                for inst in res.get("Instances", []) if isinstance(res, dict) else []:
                    iid = inst.get("InstanceId")
                    if not iid:
                        continue
                    owner = acct or inst.get("OwnerId", "")
                    state = inst.get("State", {}).get("Name")
                    instance_ebs_optimized[iid] = inst.get("EbsOptimized")
                    security_group_ids = [sg.get("GroupId") for sg in inst.get("SecurityGroups", []) if sg.get("GroupId")]
                    ssh_security_group_count = sum(1 for gid in security_group_ids if sg_ssh_access.get(gid))
                    block_devices = inst.get("BlockDeviceMappings") or []
                    delete_on_termination_disabled_devices = [
                        mapping.get("DeviceName")
                        for mapping in block_devices
                        if mapping.get("Ebs") and mapping.get("Ebs", {}).get("DeleteOnTermination") is False
                    ]
                    result.resources.append({
                        "resource_arn": f"arn:aws:ec2:{region}:{owner}:instance/{iid}",
                        "resource_type": "AWS::EC2::Instance",
                        "service_name": "ec2",
                        "region": region,
                        "account_id": owner,
                        "resource_id": iid,
                        "created_at": inst.get("LaunchTime"),
                        "current_tags": self._extract_tags(inst.get("Tags")),
                        "metadata_json": {
                            "instance_type": inst.get("InstanceType"),
                            "state": state,
                            "vpc_id": inst.get("VpcId"),
                            "subnet_id": inst.get("SubnetId"),
                            "public_ip": inst.get("PublicIpAddress"),
                            "private_ip": inst.get("PrivateIpAddress"),
                            "platform": inst.get("Platform", "linux"),
                            "image_id": inst.get("ImageId"),
                            "security_group_ids": security_group_ids,
                            "security_group_rule_count": sum(sg_rule_counts.get(gid, 0) for gid in security_group_ids),
                            "ssh_security_group_count": ssh_security_group_count,
                            "source_dest_check": inst.get("SourceDestCheck"),
                            "delete_on_termination_disabled": bool(delete_on_termination_disabled_devices),
                            "delete_on_termination_disabled_devices": delete_on_termination_disabled_devices,
                        },
                    })
                    if state == "running":
                        running_instance_ids.append(iid)
        self._safe_collect(result, region, "EC2 instances", _instances)

        # Enrich running instances with CloudWatch CPU/Network metrics
        if running_instance_ids:
            try:
                cw_metrics = _collect_cloudwatch_metrics(job.session, running_instance_ids, region)
                if cw_metrics:
                    for res in result.resources:
                        if res.get("resource_type") != "AWS::EC2::Instance":
                            continue
                        iid = res.get("resource_id")
                        if iid in cw_metrics:
                            res["metadata_json"].update(cw_metrics[iid])
            except Exception:
                # CloudWatch enrichment is best-effort; don't fail the scan
                pass

        # Volumes — field names match tag-manager: size_gb (not allocated_storage_gb), availability_zone, throughput
        def _volumes():
            nonlocal existing_volume_ids
            volumes = self._paginate_with_retry(ec2, "describe_volumes", "Volumes")
            existing_volume_ids = {vol.get("VolumeId") for vol in volumes if vol.get("VolumeId")}
            for vol in volumes:
                vid = vol.get("VolumeId")
                if not vid:
                    continue
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:volume/{vid}",
                    "resource_type": "AWS::EC2::Volume",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": vid,
                    "created_at": vol.get("CreateTime"),
                    "current_tags": self._extract_tags(vol.get("Tags")),
                    "metadata_json": {
                        "volume_type": vol.get("VolumeType"),
                        "size_gb": vol.get("Size"),
                        "state": vol.get("State"),
                        "iops": vol.get("Iops"),
                        "throughput": vol.get("Throughput"),
                        "encrypted": vol.get("Encrypted"),
                        "availability_zone": vol.get("AvailabilityZone"),
                        "attachments": [
                            {
                                "instance_id": a.get("InstanceId"),
                                "device": a.get("Device"),
                                "state": a.get("State"),
                                "instance_ebs_optimized": instance_ebs_optimized.get(a.get("InstanceId")),
                            }
                            for a in vol.get("Attachments", [])
                        ],
                    },
                })
        self._safe_collect(result, region, "EBS volumes", _volumes)

        # Snapshots
        def _snapshots():
            snaps = self._paginate_with_retry(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
            now = datetime.now(timezone.utc)
            newest_snapshot_by_volume: Dict[str, datetime] = {}
            for snap in snaps:
                volume_id = snap.get("VolumeId")
                start_time = snap.get("StartTime")
                if not volume_id or not isinstance(start_time, datetime):
                    continue
                current = newest_snapshot_by_volume.get(volume_id)
                if current is None or start_time > current:
                    newest_snapshot_by_volume[volume_id] = start_time
            for snap in snaps:
                sid = snap.get("SnapshotId")
                if not sid:
                    continue
                volume_id = snap.get("VolumeId")
                start_time = snap.get("StartTime")
                age_days = None
                if isinstance(start_time, datetime):
                    age_days = (now - start_time).days
                newest_for_volume = newest_snapshot_by_volume.get(volume_id or "")
                is_older_duplicate = bool(
                    volume_id
                    and isinstance(start_time, datetime)
                    and newest_for_volume
                    and start_time < newest_for_volume
                )
                source_volume_exists = None
                if volume_id and existing_volume_ids is not None:
                    source_volume_exists = volume_id in existing_volume_ids
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:snapshot/{sid}",
                    "resource_type": "AWS::EC2::Snapshot",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or snap.get("OwnerId", ""),
                    "resource_id": sid,
                    "created_at": snap.get("StartTime"),
                    "current_tags": self._extract_tags(snap.get("Tags")),
                    "metadata_json": {
                        "volume_id": volume_id,
                        "volume_size": snap.get("VolumeSize"),
                        "state": snap.get("State"),
                        "encrypted": snap.get("Encrypted"),
                        "age_days": age_days,
                        "source_volume_exists": source_volume_exists,
                        "is_older_duplicate_snapshot": is_older_duplicate,
                        "is_unnecessary_snapshot": bool(
                            snap.get("State") == "completed"
                            and ((age_days is not None and age_days > 7) or is_older_duplicate)
                        ),
                        "is_orphaned_snapshot": bool(source_volume_exists is False),
                        # Shared-DB compat with tag-manager
                        "description": snap.get("Description"),
                    },
                })
        self._safe_collect(result, region, "EBS snapshots", _snapshots)

        # Elastic IPs
        def _eips():
            resp = ec2.describe_addresses()
            for eip in resp.get("Addresses", []):
                ip = eip.get("PublicIp", "")
                alloc_id = eip.get("AllocationId", ip)
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:elastic-ip/{alloc_id}",
                    "resource_type": "AWS::EC2::EIP",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": alloc_id,
                    "current_tags": self._extract_tags(eip.get("Tags")),
                    "metadata_json": {
                        "public_ip": ip,
                        "association_id": eip.get("AssociationId"),
                        "instance_id": eip.get("InstanceId"),
                        "domain": eip.get("Domain"),
                        # Shared-DB compat with tag-manager
                        "allocation_id": eip.get("AllocationId"),
                        "network_interface_id": eip.get("NetworkInterfaceId"),
                        "private_ip": eip.get("PrivateIpAddress"),
                    },
                })
        self._safe_collect(result, region, "Elastic IPs", _eips)

        # Reserved Instances (Phase C)
        def _reserved():
            resp = ec2.describe_reserved_instances()
            for ri in resp.get("ReservedInstances", []):
                ri_id = ri.get("ReservedInstancesId", "")
                state = ri.get("State", "")
                if state != "active":
                    continue
                end_time = ri.get("End")
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:reserved-instances/{ri_id}",
                    "resource_type": "AWS::EC2::ReservedInstances",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": ri_id,
                    "created_at": ri.get("Start"),
                    "current_tags": self._extract_tags(ri.get("Tags")),
                    "metadata_json": {
                        "instance_type": ri.get("InstanceType"),
                        "instance_count": ri.get("InstanceCount"),
                        "product_description": ri.get("ProductDescription"),
                        "offering_class": ri.get("OfferingClass"),
                        "offering_type": ri.get("OfferingType"),
                        "state": state,
                        "scope": ri.get("Scope"),
                        "start_time": ri.get("Start").isoformat() if ri.get("Start") else None,
                        "end_time": end_time.isoformat() if end_time else None,
                    },
                })
        self._safe_collect(result, region, "Reserved Instances", _reserved)

        return result


# ---------------------------------------------------------------------------
# S3 Collector (global — no region iteration)
# ---------------------------------------------------------------------------

class S3Collector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id

        def _buckets():
            s3 = self._get_client("s3", "us-east-1", job.session)
            cloudtrail_buckets = set()
            try:
                cloudtrail = self._get_client("cloudtrail", "us-east-1", job.session)
                for trail in cloudtrail.describe_trails(includeShadowTrails=True).get("trailList", []):
                    bucket_name = trail.get("S3BucketName")
                    if bucket_name:
                        cloudtrail_buckets.add(bucket_name)
            except ClientError:
                cloudtrail_buckets = set()
            resp = s3.list_buckets()
            for bucket in resp.get("Buckets", []):
                name = bucket.get("Name", "")
                # Get bucket region
                try:
                    loc = s3.get_bucket_location(Bucket=name)
                    bucket_region = loc.get("LocationConstraint") or "us-east-1"
                except ClientError:
                    bucket_region = "unknown"
                # Get tags
                tags = {}
                try:
                    tag_resp = s3.get_bucket_tagging(Bucket=name)
                    tags = self._extract_tags(tag_resp.get("TagSet"))
                except ClientError:
                    pass

                # Gather richer metadata for downstream resource analysis. `creation_date`
                # is included for shared-DB compat with tag-manager.
                creation = bucket.get("CreationDate")
                metadata = {
                    "bucket_name": name,
                    "creation_date": creation.isoformat() if hasattr(creation, "isoformat") else creation,
                    "is_cloudtrail_log_bucket": name in cloudtrail_buckets,
                }
                try:
                    enc = s3.get_bucket_encryption(Bucket=name)
                    rules = enc.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
                    if rules:
                        sse = rules[0].get("ApplyServerSideEncryptionByDefault", {})
                        metadata["encryption"] = sse.get("SSEAlgorithm", "none")
                        metadata["kms_key_id"] = sse.get("KMSMasterKeyID")
                    else:
                        metadata["encryption"] = "none"
                except ClientError as exc:
                    if _client_error_code(exc) == "ServerSideEncryptionConfigurationNotFoundError":
                        metadata["encryption"] = "none"
                    else:
                        metadata["encryption"] = None
                try:
                    ver = s3.get_bucket_versioning(Bucket=name)
                    metadata["versioning"] = ver.get("Status", "Disabled")
                    metadata["mfa_delete"] = ver.get("MFADelete", "Disabled")
                except ClientError:
                    metadata["versioning"] = None
                    metadata["mfa_delete"] = None
                try:
                    pub = s3.get_public_access_block(Bucket=name)
                    pac = pub.get("PublicAccessBlockConfiguration", {})
                    metadata["public_access_block"] = all([
                        pac.get("BlockPublicAcls", False),
                        pac.get("IgnorePublicAcls", False),
                        pac.get("BlockPublicPolicy", False),
                        pac.get("RestrictPublicBuckets", False),
                    ])
                except ClientError as exc:
                    if _client_error_code(exc) == "NoSuchPublicAccessBlockConfiguration":
                        metadata["public_access_block"] = False
                    else:
                        metadata["public_access_block"] = None
                try:
                    logging_resp = s3.get_bucket_logging(Bucket=name)
                    metadata["logging_enabled"] = bool(logging_resp.get("LoggingEnabled"))
                except ClientError:
                    metadata["logging_enabled"] = None
                try:
                    object_lock_resp = s3.get_object_lock_configuration(Bucket=name)
                    metadata["object_lock_enabled"] = (
                        object_lock_resp.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled") == "Enabled"
                    )
                except ClientError as exc:
                    code = _client_error_code(exc)
                    if code in {"ObjectLockConfigurationNotFoundError", "NoSuchObjectLockConfiguration"}:
                        metadata["object_lock_enabled"] = False
                    else:
                        metadata["object_lock_enabled"] = None
                try:
                    lifecycle_resp = s3.get_bucket_lifecycle_configuration(Bucket=name)
                    lifecycle_rules = lifecycle_resp.get("Rules", [])
                    metadata["lifecycle_enabled"] = any(
                        rule.get("Status") == "Enabled" for rule in lifecycle_rules
                    )
                    metadata["lifecycle_rule_count"] = len(lifecycle_rules)
                except ClientError as exc:
                    if _client_error_code(exc) == "NoSuchLifecycleConfiguration":
                        metadata["lifecycle_enabled"] = False
                        metadata["lifecycle_rule_count"] = 0
                    else:
                        metadata["lifecycle_enabled"] = None
                        metadata["lifecycle_rule_count"] = None
                try:
                    policy_status = s3.get_bucket_policy_status(Bucket=name)
                    metadata["bucket_policy_is_public"] = bool(
                        policy_status.get("PolicyStatus", {}).get("IsPublic")
                    )
                except ClientError as exc:
                    if _client_error_code(exc) == "NoSuchBucketPolicy":
                        metadata["bucket_policy_is_public"] = False
                    else:
                        metadata["bucket_policy_is_public"] = None
                try:
                    acl = s3.get_bucket_acl(Bucket=name)
                    metadata["acl_public"] = any(
                        grant.get("Grantee", {}).get("URI") in PUBLIC_GRANTEE_URIS
                        for grant in acl.get("Grants", [])
                    )
                except ClientError:
                    metadata["acl_public"] = None
                try:
                    policy_resp = s3.get_bucket_policy(Bucket=name)
                    metadata.update(_analyze_s3_bucket_policy(policy_resp.get("Policy", "")))
                except ClientError as exc:
                    if _client_error_code(exc) == "NoSuchBucketPolicy":
                        metadata.update(_empty_s3_policy_analysis())
                    else:
                        metadata.update({
                            "bucket_policy_allows_all_principals_all_actions": None,
                            "bucket_policy_allows_public_delete_actions": None,
                            "bucket_policy_enforces_ssl": None,
                            "bucket_policy_enforces_encrypted_writes": None,
                        })

                result.resources.append({
                    "resource_arn": f"arn:aws:s3:::{name}",
                    "resource_type": "AWS::S3::Bucket",
                    "service_name": "s3",
                    "region": bucket_region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": bucket.get("CreationDate"),
                    "current_tags": tags,
                    "metadata_json": metadata,
                })
        self._safe_collect(result, "global", "S3", _buckets)
        return result


# ---------------------------------------------------------------------------
# Lambda Collector
# ---------------------------------------------------------------------------

class LambdaCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _functions():
            lam = self._get_client("lambda", region, job.session)
            functions = self._paginate_with_retry(lam, "list_functions", "Functions")
            role_counts: Dict[str, int] = {}
            for fn in functions:
                role = fn.get("Role")
                if role:
                    role_counts[role] = role_counts.get(role, 0) + 1
            for fn in functions:
                arn = fn.get("FunctionArn", "")
                name = fn.get("FunctionName", "")
                role = fn.get("Role")
                tags = {}
                try:
                    tags = lam.list_tags(Resource=arn).get("Tags", {})
                except ClientError:
                    pass
                # Lambda returns LastModified as an ISO-ish string (e.g.
                # "2024-01-02T03:04:05.000+0000"); SQLAlchemy's DateTime
                # column rejects strings. Parse to datetime or fall through.
                last_modified = _parse_lambda_timestamp(fn.get("LastModified"))
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::Lambda::Function",
                    "service_name": "lambda",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": last_modified,
                    "current_tags": tags,
                    "metadata_json": {
                        "runtime": fn.get("Runtime"),
                        "handler": fn.get("Handler"),
                        "memory_size": fn.get("MemorySize"),
                        "timeout": fn.get("Timeout"),
                        "code_size": fn.get("CodeSize"),
                        "state": fn.get("State"),
                        "role_arn": role,
                        "execution_role_function_count": role_counts.get(role, 0) if role else None,
                        "tracing_mode": (fn.get("TracingConfig") or {}).get("Mode"),
                        "xray_tracing_enabled": (fn.get("TracingConfig") or {}).get("Mode") == "Active",
                        "last_modified_age_days": _age_days(last_modified),
                        # Shared-DB compat with tag-manager
                        "function_name": name,
                        "last_modified": fn.get("LastModified"),
                        "architectures": fn.get("Architectures", ["x86_64"]),
                    },
                })
        self._safe_collect(result, region, "Lambda", _functions)

        try:
            function_names = [
                r["resource_id"] for r in result.resources
                if r.get("resource_type") == "AWS::Lambda::Function"
            ]
            if function_names:
                metrics = _collect_lambda_metrics(job.session, function_names, region)
                for r in result.resources:
                    if r.get("resource_type") == "AWS::Lambda::Function":
                        function_metrics = metrics.get(r["resource_id"])
                        if function_metrics:
                            r["metadata_json"].update(function_metrics)
        except Exception as e:
            log.debug(f"Lambda metric enrichment failed in {region}: {e}")

        return result


# ---------------------------------------------------------------------------
# RDS Collector — instances + clusters
# ---------------------------------------------------------------------------

class RDSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        rds = self._get_client("rds", region, job.session)

        # DB Instances — field names match tag-manager: storage_gb (not allocated_storage_gb)
        def _instances():
            instances = self._paginate_with_retry(rds, "describe_db_instances", "DBInstances")
            for db in instances:
                db_id = db.get("DBInstanceIdentifier")
                if not db_id:
                    continue
                arn = db.get("DBInstanceArn", "")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::RDS::DBInstance",
                    "service_name": "rds",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": db_id,
                    "created_at": db.get("InstanceCreateTime"),
                    "current_tags": self._extract_tags(db.get("TagList")),
                    "metadata_json": {
                        "engine": db.get("Engine"),
                        "engine_version": db.get("EngineVersion"),
                        "instance_class": db.get("DBInstanceClass"),
                        "status": db.get("DBInstanceStatus"),
                        "storage_type": db.get("StorageType"),
                        "storage_gb": db.get("AllocatedStorage"),  # matches tag-manager field name
                        "max_allocated_storage_gb": db.get("MaxAllocatedStorage"),
                        "storage_autoscaling_enabled": bool(db.get("MaxAllocatedStorage")),
                        "storage_encrypted": db.get("StorageEncrypted"),
                        "multi_az": db.get("MultiAZ"),
                        "publicly_accessible": db.get("PubliclyAccessible"),
                        "deletion_protection": db.get("DeletionProtection"),
                        "backup_retention_period": db.get("BackupRetentionPeriod"),
                        "age_days": _age_days(db.get("InstanceCreateTime")),
                    },
                })
        self._safe_collect(result, region, "RDS instances", _instances)

        # DB Clusters
        def _clusters():
            clusters = self._paginate_with_retry(rds, "describe_db_clusters", "DBClusters")
            for cl in clusters:
                cl_id = cl.get("DBClusterIdentifier")
                if not cl_id:
                    continue
                arn = cl.get("DBClusterArn", "")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::RDS::DBCluster",
                    "service_name": "rds",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": cl_id,
                    "created_at": cl.get("ClusterCreateTime"),
                    "current_tags": self._extract_tags(cl.get("TagList")),
                    "metadata_json": {
                        "engine": cl.get("Engine"),
                        "engine_version": cl.get("EngineVersion"),
                        "status": cl.get("Status"),
                        "storage_encrypted": cl.get("StorageEncrypted"),
                        "multi_az": cl.get("MultiAZ"),
                        "deletion_protection": cl.get("DeletionProtection"),
                        # Shared-DB compat with tag-manager
                        "database_name": cl.get("DatabaseName"),
                    },
                })
        self._safe_collect(result, region, "RDS clusters", _clusters)

        # Enrich RDS instances with CloudWatch metrics (CPU, connections, memory)
        try:
            db_ids = [
                r["resource_id"] for r in result.resources
                if r.get("resource_type") == "AWS::RDS::DBInstance"
            ]
            if db_ids:
                metrics = _collect_rds_metrics(job.session, db_ids, region)
                for r in result.resources:
                    if r.get("resource_type") == "AWS::RDS::DBInstance":
                        m = metrics.get(r["resource_id"])
                        if m:
                            r["metadata_json"].update(m)
        except Exception as e:
            log.debug(f"RDS metric enrichment failed in {region}: {e}")

        return result


# ---------------------------------------------------------------------------
# DynamoDB Collector
# ---------------------------------------------------------------------------

class DynamoDBCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _tables():
            ddb = self._get_client("dynamodb", region, job.session)
            table_names = self._paginate_with_retry(ddb, "list_tables", "TableNames")
            for name in table_names:
                try:
                    desc = ddb.describe_table(TableName=name)["Table"]
                except ClientError:
                    continue
                arn = desc.get("TableArn", "")
                tags = {}
                try:
                    tags = self._extract_tags(ddb.list_tags_of_resource(ResourceArn=arn).get("Tags"))
                except ClientError:
                    pass
                billing_mode = desc.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
                provisioned = desc.get("ProvisionedThroughput") or {}
                table_class = (desc.get("TableClassSummary") or {}).get("TableClass")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::DynamoDB::Table",
                    "service_name": "dynamodb",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": desc.get("CreationDateTime"),
                    "current_tags": tags,
                    "metadata_json": {
                        "table_status": desc.get("TableStatus"),
                        "item_count": desc.get("ItemCount"),
                        "table_size_bytes": desc.get("TableSizeBytes"),
                        "billing_mode": billing_mode,
                        "table_class": table_class or "STANDARD",
                        "deletion_protection": desc.get("DeletionProtectionEnabled"),
                        "age_days": _age_days(desc.get("CreationDateTime")),
                        "provisioned_read_capacity_units": provisioned.get("ReadCapacityUnits"),
                        "provisioned_write_capacity_units": provisioned.get("WriteCapacityUnits"),
                    },
                })
        self._safe_collect(result, region, "DynamoDB", _tables)

        try:
            table_names = [
                r["resource_id"] for r in result.resources
                if r.get("resource_type") == "AWS::DynamoDB::Table"
            ]
            if table_names:
                metrics = _collect_dynamodb_metrics(job.session, table_names, region)
                for r in result.resources:
                    if r.get("resource_type") == "AWS::DynamoDB::Table":
                        table_metrics = metrics.get(r["resource_id"])
                        if table_metrics:
                            r["metadata_json"].update(table_metrics)
        except Exception as e:
            log.debug(f"DynamoDB metric enrichment failed in {region}: {e}")

        return result


# ---------------------------------------------------------------------------
# ECS Collector — clusters + services
# ---------------------------------------------------------------------------

class ECSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _ecs():
            ecs = self._get_client("ecs", region, job.session)
            cluster_arns = self._paginate_with_retry(ecs, "list_clusters", "clusterArns")
            if not cluster_arns:
                return
            clusters = ecs.describe_clusters(clusters=cluster_arns, include=["TAGS"]).get("clusters", [])
            for cl in clusters:
                arn = cl.get("clusterArn", "")
                name = cl.get("clusterName", "")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::ECS::Cluster",
                    "service_name": "ecs",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "current_tags": self._extract_tags(cl.get("tags")),
                    "metadata_json": {
                        "status": cl.get("status"),
                        # Key names match tag-manager's shared-DB contract
                        "running_tasks": cl.get("runningTasksCount"),
                        "pending_tasks": cl.get("pendingTasksCount"),
                        "active_services": cl.get("activeServicesCount"),
                        "registered_instances": cl.get("registeredContainerInstancesCount"),
                    },
                })
                # Services in this cluster
                try:
                    svc_arns = self._paginate_with_retry(ecs, "list_services", "serviceArns", cluster=arn)
                    if svc_arns:
                        for batch in [svc_arns[i:i+10] for i in range(0, len(svc_arns), 10)]:
                            svcs = ecs.describe_services(cluster=arn, services=batch, include=["TAGS"]).get("services", [])
                            for svc in svcs:
                                result.resources.append({
                                    "resource_arn": svc.get("serviceArn", ""),
                                    "resource_type": "AWS::ECS::Service",
                                    "service_name": "ecs",
                                    "region": region,
                                    "account_id": acct or "",
                                    "resource_id": svc.get("serviceName", ""),
                                    "current_tags": self._extract_tags(svc.get("tags")),
                                    "metadata_json": {
                                        "status": svc.get("status"),
                                        "desired_count": svc.get("desiredCount"),
                                        "running_count": svc.get("runningCount"),
                                        "launch_type": svc.get("launchType"),
                                        "platform_version": svc.get("platformVersion"),
                                        "assign_public_ip": (
                                            svc.get("networkConfiguration", {})
                                            .get("awsvpcConfiguration", {})
                                            .get("assignPublicIp")
                                        ),
                                        "deployment_circuit_breaker_enabled": (
                                            svc.get("deploymentConfiguration", {})
                                            .get("deploymentCircuitBreaker", {})
                                            .get("enable")
                                        ),
                                        "deployment_circuit_breaker_rollback": (
                                            svc.get("deploymentConfiguration", {})
                                            .get("deploymentCircuitBreaker", {})
                                            .get("rollback")
                                        ),
                                        # Shared-DB compat with tag-manager
                                        "pending_count": svc.get("pendingCount"),
                                        "cluster_arn": arn,
                                    },
                                })
                except ClientError:
                    pass
        self._safe_collect(result, region, "ECS", _ecs)

        def _task_definitions():
            ecs = self._get_client("ecs", region, job.session)
            task_definition_arns = []
            for status in ("ACTIVE", "INACTIVE"):
                try:
                    task_definition_arns.extend(
                        self._paginate_with_retry(
                            ecs,
                            "list_task_definitions",
                            "taskDefinitionArns",
                            status=status,
                        )
                    )
                except ClientError:
                    if status == "ACTIVE":
                        raise

            seen = set()
            for task_def_arn in task_definition_arns:
                if task_def_arn in seen:
                    continue
                seen.add(task_def_arn)
                try:
                    resp = ecs.describe_task_definition(
                        taskDefinition=task_def_arn,
                        include=["TAGS"],
                    )
                except ClientError:
                    continue

                task_def = resp.get("taskDefinition", {})
                tags = self._extract_tags(resp.get("tags"))
                family = task_def.get("family", "")
                revision = task_def.get("revision")
                container_defs = task_def.get("containerDefinitions", []) or []
                privileged_containers = [
                    c.get("name") for c in container_defs if c.get("privileged") is True
                ]
                writable_root_containers = [
                    c.get("name")
                    for c in container_defs
                    if c.get("readonlyRootFilesystem") is not True
                ]
                plaintext_secret_env_vars = []
                for container in container_defs:
                    container_name = container.get("name")
                    secret_names = {
                        item.get("name")
                        for item in (container.get("secrets") or [])
                        if item.get("name")
                    }
                    for item in container.get("environment") or []:
                        name = item.get("name")
                        value = item.get("value")
                        if name and value and name not in secret_names:
                            upper_name = name.upper()
                            if any(token in upper_name for token in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
                                plaintext_secret_env_vars.append(f"{container_name}:{name}")

                result.resources.append({
                    "resource_arn": task_def_arn,
                    "resource_type": "AWS::ECS::TaskDefinition",
                    "service_name": "ecs",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": f"{family}:{revision}" if revision else family,
                    "current_tags": tags,
                    "metadata_json": {
                        "family": family,
                        "revision": revision,
                        "status": task_def.get("status"),
                        "network_mode": task_def.get("networkMode"),
                        "requires_compatibilities": task_def.get("requiresCompatibilities", []),
                        "task_role_arn": task_def.get("taskRoleArn"),
                        "execution_role_arn": task_def.get("executionRoleArn"),
                        "container_count": len(container_defs),
                        "privileged_containers": privileged_containers,
                        "writable_root_containers": writable_root_containers,
                        "plaintext_secret_env_vars": plaintext_secret_env_vars,
                    },
                })
        self._safe_collect(result, region, "ECS task definitions", _task_definitions)
        return result


# ---------------------------------------------------------------------------
# ELB Collector — ALB/NLB with type suffix (matches tag-manager)
# ---------------------------------------------------------------------------

class ELBCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _lbs():
            elb = self._get_client("elbv2", region, job.session)
            lbs = self._paginate_with_retry(elb, "describe_load_balancers", "LoadBalancers")
            # Batch fetch tags
            lb_arns = [lb.get("LoadBalancerArn") for lb in lbs if lb.get("LoadBalancerArn")]
            tags_map = {}
            if lb_arns:
                try:
                    for batch in [lb_arns[i:i+20] for i in range(0, len(lb_arns), 20)]:
                        tag_resp = elb.describe_tags(ResourceArns=batch)
                        for td in tag_resp.get("TagDescriptions", []):
                            tags_map[td["ResourceArn"]] = self._extract_tags(td.get("Tags"))
                except ClientError:
                    pass

            for lb in lbs:
                arn = lb.get("LoadBalancerArn", "")
                name = lb.get("LoadBalancerName", "")
                lb_type = lb.get("Type", "application")
                lb_attributes = {}
                lb_attributes_read = False
                target_group_count = None
                registered_target_count = None
                healthy_target_count = None
                unhealthy_target_count = None
                listener_protocols = []
                listener_ssl_policies = []
                listener_certificate_arns = []
                waf_metadata = {
                    "web_acl_attached": None,
                    "web_acl_arn": None,
                    "web_acl_name": None,
                    "web_acl_status": "not_applicable",
                }
                try:
                    attr_resp = elb.describe_load_balancer_attributes(LoadBalancerArn=arn)
                    lb_attributes = {
                        attr.get("Key"): attr.get("Value")
                        for attr in attr_resp.get("Attributes", [])
                        if attr.get("Key")
                    }
                    lb_attributes_read = True
                except ClientError:
                    pass
                try:
                    target_groups = self._paginate_with_retry(
                        elb,
                        "describe_target_groups",
                        "TargetGroups",
                        LoadBalancerArn=arn,
                    )
                    target_group_count = len(target_groups)
                    registered_target_count = 0
                    healthy_target_count = 0
                    unhealthy_target_count = 0
                    for target_group in target_groups:
                        try:
                            health = elb.describe_target_health(
                                TargetGroupArn=target_group.get("TargetGroupArn", "")
                            )
                        except ClientError:
                            continue
                        descriptions = health.get("TargetHealthDescriptions", []) or []
                        registered_target_count += len(descriptions)
                        for desc in descriptions:
                            state = desc.get("TargetHealth", {}).get("State")
                            if state == "healthy":
                                healthy_target_count += 1
                            elif state:
                                unhealthy_target_count += 1
                except ClientError:
                    pass
                try:
                    listeners = self._paginate_with_retry(
                        elb,
                        "describe_listeners",
                        "Listeners",
                        LoadBalancerArn=arn,
                    )
                    for listener in listeners:
                        protocol = listener.get("Protocol")
                        if protocol:
                            listener_protocols.append(protocol)
                        ssl_policy = listener.get("SslPolicy")
                        if ssl_policy:
                            listener_ssl_policies.append(ssl_policy)
                        listener_arn = listener.get("ListenerArn")
                        if listener_arn and protocol in {"HTTPS", "TLS"}:
                            try:
                                certs = self._paginate_with_retry(
                                    elb,
                                    "describe_listener_certificates",
                                    "Certificates",
                                    ListenerArn=listener_arn,
                                )
                            except ClientError:
                                certs = []
                            for cert in certs:
                                cert_arn = cert.get("CertificateArn")
                                if cert_arn:
                                    listener_certificate_arns.append(cert_arn)
                except ClientError:
                    pass
                if lb_type == "application" and arn:
                    waf_metadata = _get_wafv2_web_acl_for_resource(job.session, region, arn)
                certificate_metadata = _acm_certificate_expiry_metadata(
                    job.session,
                    region,
                    listener_certificate_arns,
                )
                # Match tag-manager: append /Network or /Application suffix
                type_suffix = "/Network" if lb_type == "network" else "/Application"
                # CloudWatch dimension uses the ARN suffix: app/<name>/<id>
                cw_dimension = arn.split("loadbalancer/")[-1] if "loadbalancer/" in arn else ""
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": f"AWS::ElasticLoadBalancingV2::LoadBalancer{type_suffix}",
                    "service_name": "elbv2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": lb.get("CreatedTime"),
                    "current_tags": tags_map.get(arn, {}),
                    "metadata_json": {
                        "type": lb_type,
                        "scheme": lb.get("Scheme"),
                        "state": lb.get("State", {}).get("Code"),
                        "dns_name": lb.get("DNSName"),
                        "vpc_id": lb.get("VpcId"),
                        "availability_zones": [az.get("ZoneName") for az in lb.get("AvailabilityZones", [])],
                        "cw_dimension": cw_dimension,
                        "access_logs_enabled": (
                            lb_attributes.get("access_logs.s3.enabled") == "true"
                            if lb_attributes_read else None
                        ),
                        "target_group_count": target_group_count,
                        "registered_target_count": registered_target_count,
                        "healthy_target_count": healthy_target_count,
                        "unhealthy_target_count": unhealthy_target_count,
                        "listener_protocols": listener_protocols,
                        "listener_ssl_policies": listener_ssl_policies,
                        **certificate_metadata,
                        **waf_metadata,
                    },
                })
        self._safe_collect(result, region, "ELB", _lbs)

        # Enrich ALB/NLB with CloudWatch RequestCount metrics
        try:
            app_lbs = [
                r for r in result.resources
                if r.get("metadata_json", {}).get("type") == "application"
                and r.get("metadata_json", {}).get("cw_dimension")
            ]
            if app_lbs:
                dims = [r["metadata_json"]["cw_dimension"] for r in app_lbs]
                metrics = _collect_elb_metrics(job.session, dims, region, v2=True)
                for r in app_lbs:
                    m = metrics.get(r["metadata_json"]["cw_dimension"])
                    if m:
                        r["metadata_json"].update(m)
        except Exception as e:
            log.debug(f"ELB metric enrichment failed in {region}: {e}")

        return result


# ---------------------------------------------------------------------------
# SNS Collector
# ---------------------------------------------------------------------------

class SNSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _topics():
            sns = self._get_client("sns", region, job.session)
            topics = self._paginate_with_retry(sns, "list_topics", "Topics")
            for topic in topics:
                arn = topic.get("TopicArn", "")
                name = arn.split(":")[-1] if arn else ""
                tags = {}
                try:
                    tags = self._extract_tags(sns.list_tags_for_resource(ResourceArn=arn).get("Tags"))
                except ClientError:
                    pass
                # Fetch attributes for metadata aligned with tag-manager
                attrs: Dict[str, Any] = {}
                try:
                    attrs = sns.get_topic_attributes(TopicArn=arn).get("Attributes", {}) or {}
                except ClientError:
                    pass
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::SNS::Topic",
                    "service_name": "sns",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "current_tags": tags,
                    "metadata_json": {
                        "topic_name": name,
                        # Shared-DB compat with tag-manager
                        "display_name": attrs.get("DisplayName"),
                        "fifo_topic": name.endswith(".fifo"),
                        "kms_master_key_id": attrs.get("KmsMasterKeyId"),
                        "subscriptions_confirmed": int(attrs.get("SubscriptionsConfirmed") or 0),
                        "subscriptions_pending": int(attrs.get("SubscriptionsPending") or 0),
                    },
                })
        self._safe_collect(result, region, "SNS", _topics)
        return result


# ---------------------------------------------------------------------------
# SQS Collector
# ---------------------------------------------------------------------------

class SQSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _queues():
            sqs = self._get_client("sqs", region, job.session)
            resp = sqs.list_queues()
            for url in resp.get("QueueUrls", []):
                name = url.split("/")[-1]
                try:
                    attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"]).get("Attributes", {})
                except ClientError:
                    attrs = {}
                tags = {}
                try:
                    tags = sqs.list_queue_tags(QueueUrl=url).get("Tags", {})
                except ClientError:
                    pass
                arn = attrs.get("QueueArn", f"arn:aws:sqs:{region}:{acct}:{name}")
                # SQS returns CreatedTimestamp as a *string* unix epoch
                # (e.g. "1700000000"); the DateTime column rejects it.
                created_at = _parse_epoch_string(attrs.get("CreatedTimestamp"))
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::SQS::Queue",
                    "service_name": "sqs",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": created_at,
                    "current_tags": tags,
                    "metadata_json": {
                        "queue_name": name,
                        "approximate_messages": int(attrs.get("ApproximateNumberOfMessages", 0)),
                        "visibility_timeout": int(attrs.get("VisibilityTimeout", 0)),
                        # Shared-DB compat with tag-manager
                        "approximate_messages_delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
                        "fifo_queue": attrs.get("FifoQueue", "false") == "true" or name.endswith(".fifo"),
                        "kms_master_key_id": attrs.get("KmsMasterKeyId"),
                        "message_retention_period": int(attrs.get("MessageRetentionPeriod", 0)),
                        "queue_url": url,
                    },
                })
        self._safe_collect(result, region, "SQS", _queues)
        return result


# ---------------------------------------------------------------------------
# CloudWatch Collector — alarms + log groups
# ---------------------------------------------------------------------------

class CloudWatchCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        # Alarms
        def _alarms():
            cw = self._get_client("cloudwatch", region, job.session)
            alarms = self._paginate_with_retry(cw, "describe_alarms", "MetricAlarms")
            for alarm in alarms:
                arn = alarm.get("AlarmArn", "")
                name = alarm.get("AlarmName", "")
                tags = {}
                try:
                    tags = self._extract_tags(cw.list_tags_for_resource(ResourceARN=arn).get("Tags"))
                except ClientError:
                    pass
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::CloudWatch::Alarm",
                    "service_name": "cloudwatch",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "current_tags": tags,
                    "metadata_json": {
                        "state_value": alarm.get("StateValue"),
                        "metric_name": alarm.get("MetricName"),
                        "namespace": alarm.get("Namespace"),
                        "threshold": alarm.get("Threshold"),
                        # Shared-DB compat with tag-manager
                        "actions_enabled": alarm.get("ActionsEnabled"),
                        "comparison_operator": alarm.get("ComparisonOperator"),
                    },
                })
        self._safe_collect(result, region, "CloudWatch alarms", _alarms)

        # Log groups
        def _log_groups():
            logs = self._get_client("logs", region, job.session)
            groups = self._paginate_with_retry(logs, "describe_log_groups", "logGroups")
            for lg in groups:
                name = lg.get("logGroupName", "")
                arn = lg.get("arn", "").rstrip("*").rstrip(":")
                tags = {}
                try:
                    tags = logs.list_tags_for_resource(resourceArn=arn).get("tags", {})
                except ClientError:
                    pass
                # metric_filter_count needs a dedicated call; tolerate failures.
                metric_filter_count = 0
                try:
                    mf_resp = logs.describe_metric_filters(logGroupName=name, limit=1)
                    metric_filter_count = mf_resp.get("metricFilters")
                    # Page count may be limited; use the reported total if any.
                    metric_filter_count = len(metric_filter_count or [])
                except ClientError:
                    pass
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::Logs::LogGroup",
                    "service_name": "cloudwatch",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "current_tags": tags,
                    "metadata_json": {
                        "retention_days": lg.get("retentionInDays"),
                        "stored_bytes": lg.get("storedBytes"),
                        # Shared-DB compat with tag-manager
                        "kms_key_id": lg.get("kmsKeyId"),
                        "metric_filter_count": metric_filter_count,
                    },
                })
        self._safe_collect(result, region, "CloudWatch log groups", _log_groups)
        return result


# ---------------------------------------------------------------------------
# CloudTrail Collector
# ---------------------------------------------------------------------------

class CloudTrailCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _trails():
            cloudtrail = self._get_client("cloudtrail", region, job.session)
            trails = cloudtrail.describe_trails(includeShadowTrails=True).get("trailList", [])
            logging_count = 0
            multi_region_present = False

            for trail in trails:
                arn = trail.get("TrailARN", "")
                name = trail.get("Name", "")
                status = {}
                try:
                    status = cloudtrail.get_trail_status(Name=arn or name)
                except ClientError:
                    pass
                is_logging = status.get("IsLogging")
                if is_logging:
                    logging_count += 1
                if trail.get("IsMultiRegionTrail"):
                    multi_region_present = True

                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::CloudTrail::Trail",
                    "service_name": "cloudtrail",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "current_tags": {},
                    "metadata_json": {
                        "trail_name": name,
                        "home_region": trail.get("HomeRegion"),
                        "is_logging": is_logging,
                        "is_multi_region_trail": trail.get("IsMultiRegionTrail"),
                        "log_file_validation_enabled": trail.get("LogFileValidationEnabled"),
                        "kms_key_id": trail.get("KmsKeyId"),
                        "cloud_watch_logs_log_group_arn": trail.get("CloudWatchLogsLogGroupArn"),
                        "s3_bucket_name": trail.get("S3BucketName"),
                    },
                })

            result.resources.append({
                "resource_arn": f"arn:aws:cloudtrail:{region}:{acct or ''}:region/{region}",
                "resource_type": "AWS::CloudTrail::Region",
                "service_name": "cloudtrail",
                "region": region,
                "account_id": acct or "",
                "resource_id": region,
                "current_tags": {},
                "metadata_json": {
                    "trail_count": len(trails),
                    "logging_trail_count": logging_count,
                    "multi_region_trail_present": multi_region_present,
                },
            })
        self._safe_collect(result, region, "CloudTrail", _trails)
        return result


# ---------------------------------------------------------------------------
# ACM Collector
# ---------------------------------------------------------------------------

ACM_CERTIFICATE_KEY_TYPES = [
    "RSA_1024",
    "RSA_2048",
    "RSA_3072",
    "RSA_4096",
    "EC_prime256v1",
    "EC_secp384r1",
    "EC_secp521r1",
]


class ACMCollector(ServiceCollector):
    def _list_certificates(self, acm) -> List[Dict[str, Any]]:
        try:
            return self._paginate_with_retry(
                acm,
                "list_certificates",
                "CertificateSummaryList",
                Includes={"keyTypes": ACM_CERTIFICATE_KEY_TYPES},
            )
        except ParamValidationError:
            return self._paginate_with_retry(acm, "list_certificates", "CertificateSummaryList")

    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _certificates():
            acm = self._get_client("acm", region, job.session)
            summaries = self._list_certificates(acm)
            for summary in summaries:
                arn = summary.get("CertificateArn")
                if not arn:
                    continue
                try:
                    cert = acm.describe_certificate(CertificateArn=arn).get("Certificate", {})
                except ClientError:
                    continue

                tags = {}
                try:
                    tags = self._extract_tags(acm.list_tags_for_certificate(CertificateArn=arn).get("Tags"))
                except ClientError:
                    pass

                not_after = cert.get("NotAfter")
                key_algorithm = cert.get("KeyAlgorithm") or summary.get("KeyAlgorithm")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::CertificateManager::Certificate",
                    "service_name": "acm",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": arn.rsplit("/", 1)[-1],
                    "created_at": cert.get("CreatedAt"),
                    "current_tags": tags,
                    "metadata_json": {
                        "domain_name": cert.get("DomainName"),
                        "status": cert.get("Status"),
                        "type": cert.get("Type"),
                        "key_algorithm": key_algorithm,
                        "key_size_bits": _certificate_key_size_bits(key_algorithm),
                        "not_before": cert.get("NotBefore").isoformat() if cert.get("NotBefore") else None,
                        "not_after": not_after.isoformat() if not_after else None,
                        "days_until_expiration": _days_until(not_after),
                        "renewal_eligibility": cert.get("RenewalEligibility"),
                        "in_use": bool(cert.get("InUseBy")),
                        "in_use_by_count": len(cert.get("InUseBy") or []),
                    },
                })

        self._safe_collect(result, region, "ACM certificates", _certificates)
        return result


# ---------------------------------------------------------------------------
# CloudFront Collector
# ---------------------------------------------------------------------------

class CloudFrontCollector(ServiceCollector):
    def _list_distributions(self, cloudfront) -> List[Dict[str, Any]]:
        distributions: List[Dict[str, Any]] = []
        paginator = cloudfront.get_paginator("list_distributions")
        for page in paginator.paginate():
            distributions.extend(page.get("DistributionList", {}).get("Items", []) or [])
        return distributions

    @staticmethod
    def _cache_behavior_viewer_protocol_policies(config: Dict[str, Any]) -> List[str]:
        policies = []
        default_policy = (config.get("DefaultCacheBehavior") or {}).get("ViewerProtocolPolicy")
        if default_policy:
            policies.append(default_policy)
        cache_behaviors = (config.get("CacheBehaviors") or {}).get("Items", []) or []
        for behavior in cache_behaviors:
            policy = behavior.get("ViewerProtocolPolicy")
            if policy:
                policies.append(policy)
        return sorted(set(policies))

    @staticmethod
    def _origin_protocol_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
        origins = (config.get("Origins") or {}).get("Items", []) or []
        protocol_policies = []
        origins_without_https_only = []
        origins_http_only = []
        for origin in origins:
            custom_origin = origin.get("CustomOriginConfig") or {}
            policy = custom_origin.get("OriginProtocolPolicy")
            if not policy:
                continue
            protocol_policies.append(policy)
            origin_id = origin.get("Id") or origin.get("DomainName") or "unknown"
            if policy != "https-only":
                origins_without_https_only.append(origin_id)
            if policy == "http-only":
                origins_http_only.append(origin_id)

        return {
            "origin_protocol_policies": sorted(set(protocol_policies)),
            "origins_without_https_only": sorted(origins_without_https_only),
            "origins_http_only": sorted(origins_http_only),
        }

    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id
        region = "global"

        def _distributions():
            cloudfront = self._get_client("cloudfront", "us-east-1", job.session)
            summaries = self._list_distributions(cloudfront)
            for summary in summaries:
                dist_id = summary.get("Id")
                if not dist_id:
                    continue
                arn = summary.get("ARN") or f"arn:aws:cloudfront::{acct or ''}:distribution/{dist_id}"
                distribution = summary
                try:
                    distribution = cloudfront.get_distribution(Id=dist_id).get("Distribution", summary)
                except ClientError:
                    pass

                config = distribution.get("DistributionConfig") or summary
                viewer_certificate = config.get("ViewerCertificate") or {}
                web_acl_id = config.get("WebACLId")
                tags = {}
                try:
                    tags = self._extract_tags(
                        cloudfront.list_tags_for_resource(Resource=arn).get("Tags", {}).get("Items")
                    )
                except ClientError:
                    pass

                origin_metadata = self._origin_protocol_metadata(config)
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::CloudFront::Distribution",
                    "service_name": "cloudfront",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": dist_id,
                    "current_tags": tags,
                    "metadata_json": {
                        "domain_name": distribution.get("DomainName") or summary.get("DomainName"),
                        "enabled": config.get("Enabled"),
                        "status": distribution.get("Status") or summary.get("Status"),
                        "last_modified_time": (
                            distribution.get("LastModifiedTime").isoformat()
                            if distribution.get("LastModifiedTime")
                            else None
                        ),
                        "web_acl_id": web_acl_id,
                        "web_acl_attached": bool(web_acl_id),
                        "minimum_protocol_version": viewer_certificate.get("MinimumProtocolVersion"),
                        "ssl_support_method": viewer_certificate.get("SSLSupportMethod"),
                        "viewer_protocol_policies": self._cache_behavior_viewer_protocol_policies(config),
                        "origin_count": (config.get("Origins") or {}).get("Quantity", 0),
                        **origin_metadata,
                    },
                })

        self._safe_collect(result, region, "CloudFront", _distributions)
        return result


# ---------------------------------------------------------------------------
# GuardDuty Collector
# ---------------------------------------------------------------------------

class GuardDutyCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _guardduty():
            metadata = _collect_guardduty_eks_runtime_status(job.session, region)
            result.resources.append({
                "resource_arn": f"arn:aws:guardduty:{region}:{acct or ''}:detector-region/{region}",
                "resource_type": "AWS::GuardDuty::Region",
                "service_name": "guardduty",
                "region": region,
                "account_id": acct or "",
                "resource_id": region,
                "current_tags": {},
                "metadata_json": {
                    "detector_present": metadata.get("guardduty_detector_present"),
                    **metadata,
                },
            })

        self._safe_collect(result, region, "GuardDuty", _guardduty)
        return result


# ---------------------------------------------------------------------------
# Inspector Collector
# ---------------------------------------------------------------------------

class InspectorCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _findings():
            inspector = self._get_client("inspector2", region, job.session)
            findings = self._paginate_with_retry(
                inspector,
                "list_findings",
                "findings",
                filterCriteria={
                    "findingStatus": [{"comparison": "EQUALS", "value": "ACTIVE"}],
                    "severity": [
                        {"comparison": "EQUALS", "value": "HIGH"},
                        {"comparison": "EQUALS", "value": "CRITICAL"},
                    ],
                },
            )
            for finding in findings:
                finding_arn = finding.get("findingArn")
                if not finding_arn:
                    continue
                first_observed_at = finding.get("firstObservedAt")
                last_observed_at = finding.get("lastObservedAt")
                result.resources.append({
                    "resource_arn": finding_arn,
                    "resource_type": "AWS::InspectorV2::Finding",
                    "service_name": "inspector",
                    "region": region,
                    "account_id": finding.get("awsAccountId") or acct or "",
                    "resource_id": finding_arn.rsplit("/", 1)[-1],
                    "created_at": first_observed_at,
                    "current_tags": {},
                    "metadata_json": {
                        "title": finding.get("title"),
                        "description": finding.get("description"),
                        "severity": finding.get("severity"),
                        "status": finding.get("status"),
                        "type": finding.get("type"),
                        "first_observed_at": (
                            first_observed_at.isoformat()
                            if hasattr(first_observed_at, "isoformat")
                            else first_observed_at
                        ),
                        "last_observed_at": (
                            last_observed_at.isoformat()
                            if hasattr(last_observed_at, "isoformat")
                            else last_observed_at
                        ),
                        "resources": finding.get("resources") or [],
                    },
                })

        self._safe_collect(result, region, "Inspector", _findings)
        return result


# ---------------------------------------------------------------------------
# EKS Collector
# ---------------------------------------------------------------------------

class EKSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _clusters():
            eks = self._get_client("eks", region, job.session)
            guardduty_metadata = _collect_guardduty_eks_runtime_status(job.session, region)
            names = self._paginate_with_retry(eks, "list_clusters", "clusters")
            for name in names:
                try:
                    desc = eks.describe_cluster(name=name).get("cluster", {})
                except ClientError:
                    continue
                arn = desc.get("arn", "")
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::EKS::Cluster",
                    "service_name": "eks",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": desc.get("createdAt"),
                    "current_tags": desc.get("tags", {}),
                    "metadata_json": {
                        "status": desc.get("status"),
                        "version": desc.get("version"),
                        "platform_version": desc.get("platformVersion"),
                        "endpoint": desc.get("endpoint"),
                        **guardduty_metadata,
                    },
                })
        self._safe_collect(result, region, "EKS", _clusters)
        return result


# ---------------------------------------------------------------------------
# Security Hub Collector
# ---------------------------------------------------------------------------

class SecurityHubCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _security_hub():
            securityhub = self._get_client("securityhub", region, job.session)
            hub_enabled: Optional[bool] = None
            hub_arn = None
            finding_aggregator_count: Optional[int] = None
            finding_aggregator_present: Optional[bool] = None

            try:
                hub = securityhub.describe_hub()
                hub_enabled = True
                hub_arn = hub.get("HubArn")
            except ClientError as exc:
                code = _client_error_code(exc)
                if code in {"InvalidAccessException", "ResourceNotFoundException"}:
                    hub_enabled = False
                else:
                    raise

            if hub_enabled:
                try:
                    aggregators = self._paginate_with_retry(
                        securityhub,
                        "list_finding_aggregators",
                        "FindingAggregators",
                    )
                    finding_aggregator_count = len(aggregators)
                    finding_aggregator_present = finding_aggregator_count > 0
                except ClientError as exc:
                    if not self._is_permission_error(exc):
                        raise

            result.resources.append({
                "resource_arn": hub_arn or f"arn:aws:securityhub:{region}:{acct or ''}:hub/default",
                "resource_type": "AWS::SecurityHub::Region",
                "service_name": "security-hub",
                "region": region,
                "account_id": acct or "",
                "resource_id": region,
                "current_tags": {},
                "metadata_json": {
                    "hub_enabled": hub_enabled,
                    "hub_arn": hub_arn,
                    "finding_aggregator_count": finding_aggregator_count,
                    "finding_aggregator_present": finding_aggregator_present,
                },
            })

        self._safe_collect(result, region, "Security Hub", _security_hub)
        return result


# ---------------------------------------------------------------------------
# ElastiCache Collector — with tags
# ---------------------------------------------------------------------------

class ElastiCacheCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id

        def _clusters():
            ec = self._get_client("elasticache", region, job.session)
            clusters = self._paginate_with_retry(ec, "describe_cache_clusters", "CacheClusters")
            for cluster in clusters:
                cid = cluster.get("CacheClusterId", "")
                arn = cluster.get("ARN", "")
                tags = {}
                if arn:
                    try:
                        tags = self._extract_tags(ec.list_tags_for_resource(ResourceName=arn).get("TagList"))
                    except ClientError:
                        pass
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::ElastiCache::CacheCluster",
                    "service_name": "elasticache",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": cid,
                    "created_at": cluster.get("CacheClusterCreateTime"),
                    "current_tags": tags,
                    "metadata_json": {
                        "engine": cluster.get("Engine"),
                        "engine_version": cluster.get("EngineVersion"),
                        "cache_node_type": cluster.get("CacheNodeType"),
                        "num_cache_nodes": cluster.get("NumCacheNodes"),
                        "status": cluster.get("CacheClusterStatus"),
                    },
                })
        self._safe_collect(result, region, "ElastiCache", _clusters)

        # Collect Reserved Cache Nodes separately so we can detect "on-demand without reservation"
        def _reserved():
            try:
                ec = self._get_client("elasticache", region, job.session)
                reserved = self._paginate_with_retry(
                    ec, "describe_reserved_cache_nodes", "ReservedCacheNodes"
                )
                reserved_node_types = set()
                for rn in reserved:
                    if rn.get("State") == "active":
                        reserved_node_types.add(rn.get("CacheNodeType"))
                # Mark each on-demand cluster that has no matching reservation
                for r in result.resources:
                    if r.get("resource_type") == "AWS::ElastiCache::CacheCluster":
                        node_type = r["metadata_json"].get("cache_node_type")
                        r["metadata_json"]["is_on_demand"] = node_type not in reserved_node_types
            except ClientError:
                pass
        self._safe_collect(result, region, "ElastiCache reservations", _reserved)

        # Enrich ElastiCache clusters with CloudWatch CPU and connection metrics
        try:
            cluster_ids = [
                r["resource_id"] for r in result.resources
                if r.get("resource_type") == "AWS::ElastiCache::CacheCluster"
            ]
            if cluster_ids:
                metrics = _collect_elasticache_metrics(job.session, cluster_ids, region)
                for r in result.resources:
                    if r.get("resource_type") == "AWS::ElastiCache::CacheCluster":
                        m = metrics.get(r["resource_id"])
                        if m:
                            r["metadata_json"].update(m)
        except Exception as e:
            log.debug(f"ElastiCache metric enrichment failed in {region}: {e}")

        return result


# ---------------------------------------------------------------------------
# Account Governance Collectors
# ---------------------------------------------------------------------------

class AccountCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id or ""
        account = self._get_client("account", "us-east-1", job.session)
        security_contact_present = None

        try:
            response = account.get_alternate_contact(AlternateContactType="SECURITY")
            security_contact_present = bool(response.get("AlternateContact"))
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in {"ResourceNotFoundException", "ValidationException"}:
                security_contact_present = False

        result.resources.append({
            "resource_arn": f"arn:aws:account::{acct}:account",
            "resource_type": "AWS::Account::Account",
            "service_name": "account",
            "region": "global",
            "account_id": acct,
            "resource_id": acct or "account",
            "current_tags": {},
            "metadata_json": {
                "alternate_security_contact_present": security_contact_present,
            },
        })
        return result


class OrganizationsCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id or ""
        org = self._get_client("organizations", "us-east-1", job.session)
        organization_present = None
        organization_id = None
        master_account_id = None

        try:
            organization = org.describe_organization().get("Organization", {}) or {}
            organization_present = bool(organization)
            organization_id = organization.get("Id")
            master_account_id = organization.get("MasterAccountId") or organization.get("ManagementAccountId")
        except ClientError as exc:
            if _client_error_code(exc) == "AWSOrganizationsNotInUseException":
                organization_present = False

        result.resources.append({
            "resource_arn": f"arn:aws:organizations::{acct}:organization/{organization_id or 'none'}",
            "resource_type": "AWS::Organizations::Organization",
            "service_name": "organizations",
            "region": "global",
            "account_id": acct,
            "resource_id": organization_id or acct or "organization",
            "current_tags": {},
            "metadata_json": {
                "organization_present": organization_present,
                "organization_id": organization_id,
                "management_account_id": master_account_id,
            },
        })
        return result


class AWSConfigCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id or ""
        config = self._get_client("config", region, job.session)

        def _recorders():
            recorders = config.describe_configuration_recorders().get("ConfigurationRecorders", []) or []
            statuses = {
                status.get("name"): status
                for status in (config.describe_configuration_recorder_status().get("ConfigurationRecordersStatus", []) or [])
            }
            if not recorders:
                result.resources.append({
                    "resource_arn": f"arn:aws:config:{region}:{acct}:configuration-recorder/default",
                    "resource_type": "AWS::Config::ConfigurationRecorder",
                    "service_name": "config",
                    "region": region,
                    "account_id": acct,
                    "resource_id": f"{region}:missing",
                    "current_tags": {},
                    "metadata_json": {
                        "recorder_present": False,
                        "recording": False,
                    },
                })
                return

            for recorder in recorders:
                name = recorder.get("name") or "default"
                status = statuses.get(name, {}) or {}
                recording_group = recorder.get("recordingGroup") or {}
                recording_mode = recorder.get("recordingMode") or {}
                result.resources.append({
                    "resource_arn": f"arn:aws:config:{region}:{acct}:configuration-recorder/{name}",
                    "resource_type": "AWS::Config::ConfigurationRecorder",
                    "service_name": "config",
                    "region": region,
                    "account_id": acct,
                    "resource_id": name,
                    "current_tags": {},
                    "metadata_json": {
                        "recorder_present": True,
                        "recording": bool(status.get("recording")),
                        "all_supported": bool(recording_group.get("allSupported")),
                        "include_global_resource_types": bool(recording_group.get("includeGlobalResourceTypes")),
                        "resource_types": recording_group.get("resourceTypes") or [],
                        "recording_frequency": recording_mode.get("recordingFrequency"),
                    },
                })
        self._safe_collect(result, region, "AWS Config", _recorders)
        return result


class Route53Collector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id or ""
        route53 = self._get_client("route53", "us-east-1", job.session)

        def _record_sets():
            zones = self._paginate_with_retry(route53, "list_hosted_zones", "HostedZones")
            for zone in zones:
                zone_id = str(zone.get("Id", "")).split("/")[-1]
                zone_name = zone.get("Name", "")
                private_zone = bool((zone.get("Config") or {}).get("PrivateZone"))
                if not zone_id:
                    continue
                records = self._paginate_with_retry(
                    route53,
                    "list_resource_record_sets",
                    "ResourceRecordSets",
                    HostedZoneId=zone_id,
                )
                for record in records:
                    name = record.get("Name", "")
                    record_type = record.get("Type", "")
                    record_values = [
                        value.get("Value", "")
                        for value in record.get("ResourceRecords", []) or []
                        if value.get("Value")
                    ]
                    alias_target = record.get("AliasTarget") or {}
                    target = alias_target.get("DNSName") or (record_values[0] if record_values else "")
                    target_lower = target.lower().rstrip(".")
                    resource_id = f"{zone_id}:{name}:{record_type}:{record.get('SetIdentifier', '')}"
                    result.resources.append({
                        "resource_arn": f"arn:aws:route53:::{zone_id}/{name}/{record_type}",
                        "resource_type": "AWS::Route53::RecordSet",
                        "service_name": "route53",
                        "region": "global",
                        "account_id": acct,
                        "resource_id": resource_id,
                        "current_tags": {},
                        "metadata_json": {
                            "hosted_zone_id": zone_id,
                            "hosted_zone_name": zone_name,
                            "private_zone": private_zone,
                            "record_name": name,
                            "record_type": record_type,
                            "record_values": record_values,
                            "alias_target_dns_name": alias_target.get("DNSName"),
                            "target_dns_name": target,
                            "is_cname": record_type == "CNAME",
                            "cname_to_s3_website": record_type == "CNAME" and ".s3-website-" in target_lower,
                            "cname_to_cloudfront": record_type == "CNAME" and target_lower.endswith(".cloudfront.net"),
                            "cname_to_elb": record_type == "CNAME" and ".elb.amazonaws.com" in target_lower,
                            "weighted_record": "Weight" in record,
                            "latency_record": "Region" in record,
                            "geolocation_record": "GeoLocation" in record,
                            "health_check_id": record.get("HealthCheckId"),
                        },
                    })
        self._safe_collect(result, "global", "Route 53", _record_sets)
        return result


class RedshiftCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id or ""
        redshift = self._get_client("redshift", region, job.session)
        cluster_ids: List[str] = []

        def _clusters():
            clusters = self._paginate_with_retry(redshift, "describe_clusters", "Clusters")
            for cluster in clusters:
                cluster_id = cluster.get("ClusterIdentifier")
                if not cluster_id:
                    continue
                cluster_ids.append(cluster_id)
                result.resources.append({
                    "resource_arn": cluster.get("ClusterNamespaceArn")
                    or f"arn:aws:redshift:{region}:{acct}:cluster:{cluster_id}",
                    "resource_type": "AWS::Redshift::Cluster",
                    "service_name": "redshift",
                    "region": region,
                    "account_id": acct,
                    "resource_id": cluster_id,
                    "created_at": cluster.get("ClusterCreateTime"),
                    "current_tags": self._extract_tags(cluster.get("Tags")),
                    "metadata_json": {
                        "cluster_identifier": cluster_id,
                        "cluster_status": cluster.get("ClusterStatus"),
                        "node_type": cluster.get("NodeType"),
                        "number_of_nodes": cluster.get("NumberOfNodes"),
                        "encrypted": cluster.get("Encrypted"),
                        "publicly_accessible": cluster.get("PubliclyAccessible"),
                    },
                })
        self._safe_collect(result, region, "Redshift", _clusters)

        if cluster_ids:
            metrics = _collect_redshift_metrics(job.session, cluster_ids, region)
            for res in result.resources:
                if res.get("resource_type") != "AWS::Redshift::Cluster":
                    continue
                metric = metrics.get(res.get("resource_id"))
                if metric:
                    res["metadata_json"].update(metric)
        return result


class KinesisCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id or ""
        kinesis = self._get_client("kinesis", region, job.session)

        def _streams():
            stream_names = self._paginate_with_retry(kinesis, "list_streams", "StreamNames")
            for stream_name in stream_names:
                try:
                    summary = kinesis.describe_stream_summary(StreamName=stream_name).get("StreamDescriptionSummary", {})
                except ClientError:
                    summary = {}
                try:
                    tags = {
                        item.get("Key", ""): item.get("Value", "")
                        for item in self._paginate_with_retry(kinesis, "list_tags_for_stream", "Tags", StreamName=stream_name)
                        if item.get("Key")
                    }
                except ClientError:
                    tags = {}
                encryption_type = summary.get("EncryptionType")
                key_id = summary.get("KeyId")
                result.resources.append({
                    "resource_arn": summary.get("StreamARN") or f"arn:aws:kinesis:{region}:{acct}:stream/{stream_name}",
                    "resource_type": "AWS::Kinesis::Stream",
                    "service_name": "kinesis",
                    "region": region,
                    "account_id": acct,
                    "resource_id": stream_name,
                    "created_at": summary.get("StreamCreationTimestamp"),
                    "current_tags": tags,
                    "metadata_json": {
                        "stream_name": stream_name,
                        "stream_status": summary.get("StreamStatus"),
                        "stream_mode": (summary.get("StreamModeDetails") or {}).get("StreamMode"),
                        "open_shard_count": summary.get("OpenShardCount"),
                        "encryption_type": encryption_type,
                        "key_id": key_id,
                        "encrypted": encryption_type == "KMS",
                        "customer_managed_kms_key": bool(key_id and not str(key_id).startswith("alias/aws/")),
                    },
                })
        self._safe_collect(result, region, "Kinesis", _streams)
        return result


# ---------------------------------------------------------------------------
# VPC Collector — VPCs, subnets, security groups
# ---------------------------------------------------------------------------

class VPCCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        ec2 = self._get_client("ec2", region, job.session)
        instance_azs_by_vpc: Dict[str, set] = {}
        nat_gateway_azs_by_vpc: Dict[str, set] = {}
        nat_gateways_by_id: Dict[str, Dict[str, Any]] = {}
        subnet_azs: Dict[str, str] = {}
        nat_route_counts: Dict[str, int] = {}
        nat_cross_az_route_counts: Dict[str, int] = {}
        endpoint_services_by_vpc: Dict[str, set] = {}

        try:
            reservations = self._paginate_with_retry(ec2, "describe_instances", "Reservations")
            for reservation in reservations:
                for inst in reservation.get("Instances", []) if isinstance(reservation, dict) else []:
                    if inst.get("State", {}).get("Name") != "running":
                        continue
                    vpc_id = inst.get("VpcId")
                    az = (inst.get("Placement") or {}).get("AvailabilityZone")
                    if vpc_id and az:
                        instance_azs_by_vpc.setdefault(vpc_id, set()).add(az)
        except Exception:
            instance_azs_by_vpc = {}

        try:
            nat_gateways = self._paginate_with_retry(ec2, "describe_nat_gateways", "NatGateways")
            for nat_gateway in nat_gateways:
                if nat_gateway.get("State") not in {"available", "pending"}:
                    continue
                nat_gateway_id = nat_gateway.get("NatGatewayId")
                vpc_id = nat_gateway.get("VpcId")
                subnet_id = nat_gateway.get("SubnetId")
                if not nat_gateway_id or not vpc_id or not subnet_id:
                    continue
                if subnet_id not in subnet_azs:
                    try:
                        subnets = ec2.describe_subnets(SubnetIds=[subnet_id]).get("Subnets", [])
                        subnet_azs[subnet_id] = subnets[0].get("AvailabilityZone") if subnets else ""
                    except ClientError:
                        subnet_azs[subnet_id] = ""
                az = subnet_azs.get(subnet_id)
                if az:
                    nat_gateway_azs_by_vpc.setdefault(vpc_id, set()).add(az)
                nat_gateways_by_id[nat_gateway_id] = nat_gateway
        except Exception:
            nat_gateway_azs_by_vpc = {}

        try:
            endpoints = self._paginate_with_retry(ec2, "describe_vpc_endpoints", "VpcEndpoints")
            for endpoint in endpoints:
                vpc_id = endpoint.get("VpcId")
                service_name = endpoint.get("ServiceName", "")
                if vpc_id and service_name:
                    endpoint_services_by_vpc.setdefault(vpc_id, set()).add(service_name.rsplit(".", 1)[-1].lower())
        except Exception:
            endpoints = []

        try:
            route_tables = self._paginate_with_retry(ec2, "describe_route_tables", "RouteTables")
            for route_table in route_tables:
                associated_subnet_ids = [
                    assoc.get("SubnetId")
                    for assoc in route_table.get("Associations", [])
                    if assoc.get("SubnetId")
                ]
                for subnet_id in associated_subnet_ids:
                    if subnet_id not in subnet_azs:
                        try:
                            subnets = ec2.describe_subnets(SubnetIds=[subnet_id]).get("Subnets", [])
                            subnet_azs[subnet_id] = subnets[0].get("AvailabilityZone") if subnets else ""
                        except ClientError:
                            subnet_azs[subnet_id] = ""
                for route in route_table.get("Routes", []) or []:
                    nat_gateway_id = route.get("NatGatewayId")
                    if not nat_gateway_id:
                        continue
                    nat_route_counts[nat_gateway_id] = nat_route_counts.get(nat_gateway_id, 0) + 1
                    nat_gateway = nat_gateways_by_id.get(nat_gateway_id) or {}
                    nat_subnet_id = nat_gateway.get("SubnetId")
                    nat_az = subnet_azs.get(nat_subnet_id or "")
                    if not nat_az:
                        continue
                    for subnet_id in associated_subnet_ids:
                        subnet_az = subnet_azs.get(subnet_id)
                        if subnet_az and subnet_az != nat_az:
                            nat_cross_az_route_counts[nat_gateway_id] = (
                                nat_cross_az_route_counts.get(nat_gateway_id, 0) + 1
                            )
        except Exception:
            route_tables = []

        # VPCs
        def _vpcs():
            flow_logs_by_resource = {}
            try:
                flow_logs = self._paginate_with_retry(ec2, "describe_flow_logs", "FlowLogs")
                for flow_log in flow_logs:
                    resource_id = flow_log.get("ResourceId")
                    if not resource_id:
                        continue
                    flow_logs_by_resource.setdefault(resource_id, []).append(flow_log)
            except ClientError:
                pass
            vpcs = self._paginate_with_retry(ec2, "describe_vpcs", "Vpcs")
            for vpc in vpcs:
                vid = vpc.get("VpcId", "")
                vpc_flow_logs = flow_logs_by_resource.get(vid, [])
                active_flow_logs = [
                    flow_log for flow_log in vpc_flow_logs
                    if flow_log.get("FlowLogStatus") == "ACTIVE"
                ]
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:vpc/{vid}",
                    "resource_type": "AWS::EC2::VPC",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": vid,
                    "current_tags": self._extract_tags(vpc.get("Tags")),
                    "metadata_json": {
                        "cidr_block": vpc.get("CidrBlock"),
                        "is_default": vpc.get("IsDefault"),
                        "state": vpc.get("State"),
                        # Shared-DB compat with tag-manager
                        "dhcp_options_id": vpc.get("DhcpOptionsId"),
                        "flow_logs_enabled": bool(active_flow_logs),
                        "flow_log_count": len(active_flow_logs),
                        "running_instance_az_count": len(instance_azs_by_vpc.get(vid, set())),
                        "nat_gateway_az_count": len(nat_gateway_azs_by_vpc.get(vid, set())),
                        "nat_gateway_count": sum(
                            1 for nat_gateway in nat_gateways_by_id.values()
                            if nat_gateway.get("VpcId") == vid
                        ),
                        "has_s3_gateway_endpoint": "s3" in endpoint_services_by_vpc.get(vid, set()),
                        "has_dynamodb_gateway_endpoint": "dynamodb" in endpoint_services_by_vpc.get(vid, set()),
                    },
                })
        self._safe_collect(result, region, "VPCs", _vpcs)

        def _nat_gateways():
            for nat_gateway_id, nat_gateway in nat_gateways_by_id.items():
                subnet_id = nat_gateway.get("SubnetId")
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:natgateway/{nat_gateway_id}",
                    "resource_type": "AWS::EC2::NatGateway",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": nat_gateway_id,
                    "created_at": nat_gateway.get("CreateTime"),
                    "current_tags": self._extract_tags(nat_gateway.get("Tags")),
                    "metadata_json": {
                        "nat_gateway_id": nat_gateway_id,
                        "vpc_id": nat_gateway.get("VpcId"),
                        "subnet_id": subnet_id,
                        "availability_zone": subnet_azs.get(subnet_id or ""),
                        "state": nat_gateway.get("State"),
                        "active_route_count": nat_route_counts.get(nat_gateway_id, 0),
                        "cross_az_route_count": nat_cross_az_route_counts.get(nat_gateway_id, 0),
                    },
                })
        self._safe_collect(result, region, "NAT Gateways", _nat_gateways)

        def _vpc_endpoints():
            for endpoint in endpoints:
                endpoint_id = endpoint.get("VpcEndpointId")
                if not endpoint_id:
                    continue
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:vpc-endpoint/{endpoint_id}",
                    "resource_type": "AWS::EC2::VPCEndpoint",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": endpoint_id,
                    "created_at": endpoint.get("CreationTimestamp"),
                    "current_tags": self._extract_tags(endpoint.get("Tags")),
                    "metadata_json": {
                        "vpc_endpoint_id": endpoint_id,
                        "vpc_id": endpoint.get("VpcId"),
                        "service_name": endpoint.get("ServiceName"),
                        "endpoint_type": endpoint.get("VpcEndpointType"),
                        "state": endpoint.get("State"),
                        "subnet_count": len(endpoint.get("SubnetIds", []) or []),
                        "route_table_count": len(endpoint.get("RouteTableIds", []) or []),
                        "network_interface_count": len(endpoint.get("NetworkInterfaceIds", []) or []),
                    },
                })
        self._safe_collect(result, region, "VPC Endpoints", _vpc_endpoints)

        # Security Groups
        def _sgs():
            sgs = self._paginate_with_retry(ec2, "describe_security_groups", "SecurityGroups")
            for sg in sgs:
                gid = sg.get("GroupId", "")
                ingress_rules = sg.get("IpPermissions", []) or []
                egress_rules = sg.get("IpPermissionsEgress", []) or []
                rule_analysis = _analyze_security_group_rules(ingress_rules)
                inbound_rules_count = _count_security_group_rules(ingress_rules)
                outbound_rules_count = _count_security_group_rules(egress_rules)
                is_default = sg.get("GroupName") == "default"
                result.resources.append({
                    "resource_arn": f"arn:aws:ec2:{region}:{acct}:security-group/{gid}",
                    "resource_type": "AWS::EC2::SecurityGroup",
                    "service_name": "ec2",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": gid,
                    "current_tags": self._extract_tags(sg.get("Tags")),
                    "metadata_json": {
                        "group_name": sg.get("GroupName"),
                        "description": sg.get("Description"),
                        "vpc_id": sg.get("VpcId"),
                        "is_default_security_group": is_default,
                        "default_sg_has_rules": bool(is_default and (ingress_rules or egress_rules)),
                        # Shared-DB compat with tag-manager
                        "inbound_rules_count": inbound_rules_count,
                        "outbound_rules_count": outbound_rules_count,
                        "total_rules_count": inbound_rules_count + outbound_rules_count,
                        **rule_analysis,
                    },
                })
        self._safe_collect(result, region, "Security Groups", _sgs)
        return result


# ---------------------------------------------------------------------------
# EFS Collector
# ---------------------------------------------------------------------------

class EFSCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        efs = self._get_client("efs", region, job.session)
        kms = self._get_client("kms", region, job.session)
        file_system_ids: List[str] = []

        def _file_systems():
            file_systems = self._paginate_with_retry(efs, "describe_file_systems", "FileSystems")
            for fs in file_systems:
                fs_id = fs.get("FileSystemId")
                if not fs_id:
                    continue
                file_system_ids.append(fs_id)
                mount_targets = []
                lifecycle_policies = []
                replication_configs = []
                tags = {}

                try:
                    mount_targets = self._paginate_with_retry(
                        efs,
                        "describe_mount_targets",
                        "MountTargets",
                        FileSystemId=fs_id,
                    )
                except ClientError:
                    pass

                try:
                    lifecycle_policies = efs.describe_lifecycle_configuration(
                        FileSystemId=fs_id,
                    ).get("LifecyclePolicies", [])
                except ClientError:
                    pass

                try:
                    replication_configs = efs.describe_replication_configurations(
                        FileSystemId=fs_id,
                    ).get("Replications", [])
                except ClientError:
                    pass

                try:
                    tags = self._extract_tags(efs.list_tags_for_resource(ResourceId=fs_id).get("Tags", []))
                except ClientError:
                    pass

                kms_key_id = fs.get("KmsKeyId")
                kms_key_manager = None
                if kms_key_id:
                    try:
                        kms_key_manager = kms.describe_key(KeyId=kms_key_id).get("KeyMetadata", {}).get("KeyManager")
                    except ClientError:
                        pass

                lifecycle_transitions = [
                    key
                    for policy in lifecycle_policies
                    for key in policy
                    if key.startswith("Transition")
                ]

                result.resources.append({
                    "resource_arn": fs.get("FileSystemArn") or f"arn:aws:elasticfilesystem:{region}:{acct}:file-system/{fs_id}",
                    "resource_type": "AWS::EFS::FileSystem",
                    "service_name": "efs",
                    "region": region,
                    "account_id": acct or fs.get("OwnerId", ""),
                    "resource_id": fs_id,
                    "created_at": fs.get("CreationTime"),
                    "current_tags": tags,
                    "metadata_json": {
                        "name": fs.get("Name"),
                        "encrypted": fs.get("Encrypted"),
                        "kms_key_id": kms_key_id,
                        "kms_key_manager": kms_key_manager,
                        "customer_managed_kms_key": kms_key_manager == "CUSTOMER",
                        "performance_mode": fs.get("PerformanceMode"),
                        "throughput_mode": fs.get("ThroughputMode"),
                        "provisioned_throughput_in_mibps": fs.get("ProvisionedThroughputInMibps"),
                        "size_bytes": (fs.get("SizeInBytes") or {}).get("Value"),
                        "storage_class": "ONE_ZONE" if fs.get("AvailabilityZoneName") else "STANDARD",
                        "availability_zone_name": fs.get("AvailabilityZoneName"),
                        "mount_target_count": len(mount_targets),
                        "lifecycle_policy_count": len(lifecycle_policies),
                        "lifecycle_transitions": lifecycle_transitions,
                        "replication_configuration_count": len(replication_configs),
                    },
                })
        self._safe_collect(result, region, "EFS", _file_systems)

        if file_system_ids:
            try:
                efs_metrics = _collect_efs_metrics(job.session, file_system_ids, region)
                for res in result.resources:
                    if res.get("resource_type") != "AWS::EFS::FileSystem":
                        continue
                    fs_id = res.get("resource_id")
                    if fs_id in efs_metrics:
                        res["metadata_json"].update(efs_metrics[fs_id])
            except Exception:
                pass

        return result


# ---------------------------------------------------------------------------
# IAM Collector (global)
# ---------------------------------------------------------------------------

class IAMCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id
        iam = self._get_client("iam", "us-east-1", job.session)
        support_role_present = {"value": False}

        def _credential_report_summary() -> Dict[str, Any]:
            try:
                iam.generate_credential_report()
                report = iam.get_credential_report().get("Content", b"")
            except ClientError:
                return {}
            if isinstance(report, bytes):
                report = report.decode("utf-8", errors="replace")
            rows = list(csv.DictReader(str(report).splitlines()))
            root_row = next((row for row in rows if row.get("user") == "<root_account>"), None)
            if not root_row:
                return {}
            last_used = root_row.get("password_last_used")
            root_last_used_days = None
            if last_used and last_used not in {"N/A", "no_information"}:
                root_last_used_days = _age_days(last_used)
            return {
                "root_mfa_active": str(root_row.get("mfa_active", "")).lower() == "true",
                "root_user_last_used_days": root_last_used_days,
            }

        # Roles — enriched with RoleLastUsed for inactive role detection
        def _roles():
            roles = self._paginate_with_retry(iam, "list_roles", "Roles")
            for role in roles:
                arn = role.get("Arn", "")
                name = role.get("RoleName", "")
                # RoleLastUsed only returned by get_role, not list_roles
                last_used_date = None
                last_used_region = None
                try:
                    full_role = iam.get_role(RoleName=name)["Role"]
                    rlu = full_role.get("RoleLastUsed") or {}
                    if rlu.get("LastUsedDate"):
                        last_used_date = rlu["LastUsedDate"].isoformat()
                        last_used_region = rlu.get("Region")
                except ClientError:
                    pass
                attached_policy_arns = []
                try:
                    attached = self._paginate_with_retry(
                        iam,
                        "list_attached_role_policies",
                        "AttachedPolicies",
                        RoleName=name,
                    )
                    attached_policy_arns = [
                        item.get("PolicyArn")
                        for item in attached
                        if item.get("PolicyArn")
                    ]
                    if "arn:aws:iam::aws:policy/AWSSupportAccess" in attached_policy_arns:
                        support_role_present["value"] = True
                except ClientError:
                    pass

                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::IAM::Role",
                    "service_name": "iam",
                    "region": "global",
                    "account_id": acct or "",
                    "resource_id": name,
                    "created_at": role.get("CreateDate"),
                    "current_tags": self._extract_tags(role.get("Tags")),
                    "metadata_json": {
                        "role_name": name,
                        "path": role.get("Path"),
                        "description": role.get("Description", ""),
                        "max_session_duration": role.get("MaxSessionDuration"),
                        "last_used_date": last_used_date,
                        "last_used_region": last_used_region,
                        "attached_policy_arns": attached_policy_arns,
                        "support_access_policy_attached": (
                            "arn:aws:iam::aws:policy/AWSSupportAccess" in attached_policy_arns
                        ),
                    },
                })
        self._safe_collect(result, "global", "IAM roles", _roles)

        def _account():
            summary = {}
            try:
                summary = iam.get_account_summary().get("SummaryMap", {}) or {}
            except ClientError:
                pass

            password_policy = {}
            password_policy_present = False
            try:
                password_policy = iam.get_account_password_policy().get("PasswordPolicy", {}) or {}
                password_policy_present = True
            except ClientError as exc:
                if _client_error_code(exc) != "NoSuchEntity":
                    password_policy = {}

            result.resources.append({
                "resource_arn": f"arn:aws:iam::{acct or ''}:account",
                "resource_type": "AWS::IAM::Account",
                "service_name": "iam",
                "region": "global",
                "account_id": acct or "",
                "resource_id": acct or "account",
                "current_tags": {},
                "metadata_json": {
                    "account_mfa_enabled": bool(summary.get("AccountMFAEnabled")),
                    "account_access_keys_present": int(summary.get("AccountAccessKeysPresent") or 0),
                    "support_role_present": support_role_present["value"],
                    **_credential_report_summary(),
                    "password_policy_present": password_policy_present,
                    "minimum_password_length": password_policy.get("MinimumPasswordLength"),
                    "require_symbols": password_policy.get("RequireSymbols"),
                    "require_numbers": password_policy.get("RequireNumbers"),
                    "require_uppercase_characters": password_policy.get("RequireUppercaseCharacters"),
                    "require_lowercase_characters": password_policy.get("RequireLowercaseCharacters"),
                    "allow_users_to_change_password": password_policy.get("AllowUsersToChangePassword"),
                    "max_password_age": password_policy.get("MaxPasswordAge"),
                    "password_reuse_prevention": password_policy.get("PasswordReusePrevention"),
                },
            })
        self._safe_collect(result, "global", "IAM account", _account)

        def _policies():
            policies = self._paginate_with_retry(iam, "list_policies", "Policies", Scope="Local")
            for policy in policies:
                arn = policy.get("Arn", "")
                if not arn:
                    continue
                document = {}
                entities = {}
                try:
                    version = iam.get_policy_version(
                        PolicyArn=arn,
                        VersionId=policy.get("DefaultVersionId"),
                    )
                    document = version.get("PolicyVersion", {}).get("Document", {}) or {}
                except ClientError:
                    document = {}
                try:
                    entities = iam.list_entities_for_policy(PolicyArn=arn)
                except ClientError:
                    entities = {}
                result.resources.append({
                    "resource_arn": arn,
                    "resource_type": "AWS::IAM::Policy",
                    "service_name": "iam",
                    "region": "global",
                    "account_id": acct or "",
                    "resource_id": policy.get("PolicyName") or arn,
                    "created_at": policy.get("CreateDate"),
                    "current_tags": {},
                    "metadata_json": {
                        "policy_name": policy.get("PolicyName"),
                        "path": policy.get("Path"),
                        "default_version_id": policy.get("DefaultVersionId"),
                        "attachment_count": policy.get("AttachmentCount"),
                        "policy_document": document,
                        "attached_user_count": len(entities.get("PolicyUsers", []) or []),
                        "attached_group_count": len(entities.get("PolicyGroups", []) or []),
                        "attached_role_count": len(entities.get("PolicyRoles", []) or []),
                    },
                })
        self._safe_collect(result, "global", "IAM policies", _policies)

        def _users():
            users = self._paginate_with_retry(iam, "list_users", "Users")
            for user in users:
                user_name = user.get("UserName", "")
                password_enabled = False
                try:
                    iam.get_login_profile(UserName=user_name)
                    password_enabled = True
                except ClientError as exc:
                    if _client_error_code(exc) != "NoSuchEntity":
                        password_enabled = None
                mfa_devices = []
                try:
                    mfa_devices = self._paginate_with_retry(
                        iam,
                        "list_mfa_devices",
                        "MFADevices",
                        UserName=user_name,
                    )
                except ClientError:
                    pass
                result.resources.append({
                    "resource_arn": user.get("Arn", ""),
                    "resource_type": "AWS::IAM::User",
                    "service_name": "iam",
                    "region": "global",
                    "account_id": acct or "",
                    "resource_id": user_name,
                    "created_at": user.get("CreateDate"),
                    "current_tags": {},
                    "metadata_json": {
                        "user_name": user_name,
                        "path": user.get("Path"),
                        "password_enabled": password_enabled,
                        "mfa_device_count": len(mfa_devices),
                    },
                })
        self._safe_collect(result, "global", "IAM users", _users)

        # Access Keys
        def _keys():
            users = self._paginate_with_retry(iam, "list_users", "Users")
            for user in users:
                try:
                    keys = iam.list_access_keys(UserName=user["UserName"]).get("AccessKeyMetadata", [])
                except ClientError:
                    continue
                keys = sorted(keys, key=lambda item: item.get("CreateDate") or datetime.min.replace(tzinfo=timezone.utc))
                for index, key in enumerate(keys, start=1):
                    kid = key.get("AccessKeyId", "")
                    create_date = key.get("CreateDate")
                    result.resources.append({
                        "resource_arn": f"arn:aws:iam::{acct or ''}:access-key/{kid}",
                        "resource_type": "AWS::IAM::AccessKey",
                        "service_name": "iam",
                        "region": "global",
                        "account_id": acct or "",
                        "resource_id": kid,
                        "created_at": create_date,
                        "current_tags": {},
                        "metadata_json": {
                            "user_name": key.get("UserName"),
                            "status": key.get("Status"),
                            "access_key_index": index,
                            "age_days": _age_days(create_date),
                        },
                    })
        self._safe_collect(result, "global", "IAM keys", _keys)
        return result


# ---------------------------------------------------------------------------
# Elastic Beanstalk Collector
# ---------------------------------------------------------------------------

class ElasticBeanstalkCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        eb = self._get_client("elasticbeanstalk", region, job.session)

        def _environments():
            environments = self._paginate_with_retry(eb, "describe_environments", "Environments")
            for env in environments:
                env_id = env.get("EnvironmentId") or env.get("EnvironmentName")
                if not env_id:
                    continue
                platform_lifecycle_state = None
                platform_status = None
                platform_arn = env.get("PlatformArn")
                if platform_arn:
                    try:
                        platform = eb.describe_platform_version(PlatformArn=platform_arn).get("PlatformDescription", {})
                        platform_lifecycle_state = platform.get("PlatformLifecycleState")
                        platform_status = platform.get("PlatformStatus")
                    except ClientError:
                        pass
                result.resources.append({
                    "resource_arn": env.get("EnvironmentArn") or f"arn:aws:elasticbeanstalk:{region}:{acct}:environment/{env_id}",
                    "resource_type": "AWS::ElasticBeanstalk::Environment",
                    "service_name": "elasticbeanstalk",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": env_id,
                    "created_at": env.get("DateCreated"),
                    "current_tags": {},
                    "metadata_json": {
                        "environment_id": env.get("EnvironmentId"),
                        "environment_name": env.get("EnvironmentName"),
                        "application_name": env.get("ApplicationName"),
                        "status": env.get("Status"),
                        "health": env.get("Health"),
                        "health_status": env.get("HealthStatus"),
                        "platform_arn": platform_arn,
                        "platform_lifecycle_state": platform_lifecycle_state,
                        "platform_status": platform_status,
                    },
                })
        self._safe_collect(result, region, "Elastic Beanstalk environments", _environments)
        return result


# ---------------------------------------------------------------------------
# EMR Collector
# ---------------------------------------------------------------------------

class EMRCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        emr = self._get_client("emr", region, job.session)

        def _clusters():
            clusters = self._paginate_with_retry(
                emr,
                "list_clusters",
                "Clusters",
                ClusterStates=["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING"],
            )
            for summary in clusters:
                cluster_id = summary.get("Id")
                if not cluster_id:
                    continue
                try:
                    cluster = emr.describe_cluster(ClusterId=cluster_id).get("Cluster", summary)
                except ClientError:
                    cluster = summary

                task_on_demand_capacity = 0
                task_spot_capacity = 0
                try:
                    groups = self._paginate_with_retry(
                        emr,
                        "list_instance_groups",
                        "InstanceGroups",
                        ClusterId=cluster_id,
                    )
                except ClientError:
                    groups = []
                for group in groups:
                    if group.get("InstanceGroupType") != "TASK":
                        continue
                    requested = group.get("RequestedInstanceCount") or group.get("RunningInstanceCount") or 0
                    if group.get("Market") == "SPOT":
                        task_spot_capacity += requested
                    else:
                        task_on_demand_capacity += requested

                try:
                    fleets = self._paginate_with_retry(
                        emr,
                        "list_instance_fleets",
                        "InstanceFleets",
                        ClusterId=cluster_id,
                    )
                except ClientError:
                    fleets = []
                for fleet in fleets:
                    if fleet.get("InstanceFleetType") != "TASK":
                        continue
                    provisioned = fleet.get("ProvisionedSpotCapacity") or 0
                    target_spot = fleet.get("TargetSpotCapacity") or 0
                    target_on_demand = fleet.get("TargetOnDemandCapacity") or 0
                    task_spot_capacity += provisioned or target_spot
                    task_on_demand_capacity += target_on_demand

                result.resources.append({
                    "resource_arn": f"arn:aws:elasticmapreduce:{region}:{acct}:cluster/{cluster_id}",
                    "resource_type": "AWS::EMR::Cluster",
                    "service_name": "emr",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": cluster_id,
                    "created_at": (cluster.get("Status") or {}).get("Timeline", {}).get("CreationDateTime"),
                    "current_tags": self._extract_tags(cluster.get("Tags")),
                    "metadata_json": {
                        "cluster_id": cluster_id,
                        "name": cluster.get("Name") or summary.get("Name"),
                        "state": (cluster.get("Status") or {}).get("State") or summary.get("Status", {}).get("State"),
                        "task_on_demand_capacity": task_on_demand_capacity,
                        "task_spot_capacity": task_spot_capacity,
                        "task_capacity": task_on_demand_capacity + task_spot_capacity,
                    },
                })
        self._safe_collect(result, region, "EMR clusters", _clusters)
        return result


# ---------------------------------------------------------------------------
# Network Firewall Collector
# ---------------------------------------------------------------------------

class NetworkFirewallCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        nfw = self._get_client("network-firewall", region, job.session)

        def _firewalls():
            firewalls = self._paginate_with_retry(nfw, "list_firewalls", "Firewalls")
            for item in firewalls:
                firewall_name = item.get("FirewallName")
                firewall_arn = item.get("FirewallArn")
                if not firewall_name and not firewall_arn:
                    continue
                firewall = item
                firewall_policy = {}
                try:
                    response = nfw.describe_firewall(FirewallArn=firewall_arn) if firewall_arn else nfw.describe_firewall(
                        FirewallName=firewall_name
                    )
                    firewall = response.get("Firewall", item)
                except ClientError:
                    firewall = item
                policy_arn = firewall.get("FirewallPolicyArn")
                if policy_arn:
                    try:
                        firewall_policy = nfw.describe_firewall_policy(
                            FirewallPolicyArn=policy_arn,
                        ).get("FirewallPolicy", {})
                    except ClientError:
                        firewall_policy = {}

                rule_group_arns = [
                    ref.get("ResourceArn", "")
                    for ref in (firewall_policy.get("StatefulRuleGroupReferences") or [])
                    + (firewall_policy.get("StatelessRuleGroupReferences") or [])
                    if ref.get("ResourceArn")
                ]
                managed_threat_rule_group_present = any(
                    ":aws:" in arn and any(
                        marker in arn.lower()
                        for marker in ("threat", "malware", "botnet", "domain", "abused", "strict")
                    )
                    for arn in rule_group_arns
                )

                result.resources.append({
                    "resource_arn": firewall.get("FirewallArn") or firewall_arn or "",
                    "resource_type": "AWS::NetworkFirewall::Firewall",
                    "service_name": "network-firewall",
                    "region": region,
                    "account_id": acct or "",
                    "resource_id": firewall.get("FirewallName") or firewall_name or firewall_arn,
                    "current_tags": {},
                    "metadata_json": {
                        "firewall_name": firewall.get("FirewallName") or firewall_name,
                        "firewall_policy_arn": policy_arn,
                        "rule_group_arns": rule_group_arns,
                        "managed_threat_rule_group_present": managed_threat_rule_group_present,
                    },
                })
        self._safe_collect(result, region, "Network Firewall", _firewalls)
        return result


# ---------------------------------------------------------------------------
# Resource Explorer Collector
# ---------------------------------------------------------------------------

class ResourceExplorerCollector(ServiceCollector):
    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        region = job.region
        acct = job.account_id
        resource_explorer = self._get_client("resource-explorer-2", region, job.session)

        def _indexes():
            indexes = []
            try:
                indexes = self._paginate_with_retry(resource_explorer, "list_indexes", "Indexes")
            except ClientError:
                indexes = []
            result.resources.append({
                "resource_arn": f"arn:aws:resource-explorer-2:{region}:{acct}:index-status/{region}",
                "resource_type": "AWS::ResourceExplorer2::Index",
                "service_name": "resource-explorer-2",
                "region": region,
                "account_id": acct or "",
                "resource_id": region,
                "current_tags": {},
                "metadata_json": {
                    "index_enabled": bool(indexes),
                    "index_count": len(indexes),
                    "index_types": sorted({idx.get("Type") for idx in indexes if idx.get("Type")}),
                },
            })
        self._safe_collect(result, region, "Resource Explorer", _indexes)
        return result


# ---------------------------------------------------------------------------
# Collector Registry
# ---------------------------------------------------------------------------

COLLECTORS: Dict[str, ServiceCollector] = {
    "ec2": EC2Collector(),
    "s3": S3Collector(),
    "lambda": LambdaCollector(),
    "rds": RDSCollector(),
    "dynamodb": DynamoDBCollector(),
    "ecs": ECSCollector(),
    "elb": ELBCollector(),
    "sns": SNSCollector(),
    "sqs": SQSCollector(),
    "cloudwatch": CloudWatchCollector(),
    "cloudtrail": CloudTrailCollector(),
    "acm": ACMCollector(),
    "cloudfront": CloudFrontCollector(),
    "guardduty": GuardDutyCollector(),
    "account": AccountCollector(),
    "organizations": OrganizationsCollector(),
    "config": AWSConfigCollector(),
    "aws-config": AWSConfigCollector(),
    "route53": Route53Collector(),
    "route-53": Route53Collector(),
    "redshift": RedshiftCollector(),
    "kinesis": KinesisCollector(),
    "inspector": InspectorCollector(),
    "eks": EKSCollector(),
    "security-hub": SecurityHubCollector(),
    "elasticache": ElastiCacheCollector(),
    "elasticbeanstalk": ElasticBeanstalkCollector(),
    "elastic-beanstalk": ElasticBeanstalkCollector(),
    "emr": EMRCollector(),
    "network-firewall": NetworkFirewallCollector(),
    "resource-explorer": ResourceExplorerCollector(),
    "resource-explorer-2": ResourceExplorerCollector(),
    "efs": EFSCollector(),
    "vpc": VPCCollector(),
    "iam": IAMCollector(),
}

# Register collectors defined in sibling modules. Imported here (after the
# base ``ServiceCollector`` class is defined) to avoid circular imports.
from modules.collection.cost_optimization_hub import CostOptimizationHubCollector  # noqa: E402
from modules.collection.compute_optimizer import ComputeOptimizerCollector  # noqa: E402
from modules.collection.logs_collector import LogsCollector  # noqa: E402

COLLECTORS["cost_optimization_hub"] = CostOptimizationHubCollector()
# Compute Optimizer is consolidated across regions — one call returns findings
# for every opted-in region, so we register it as a global service and skip
# per-region iteration in the scanner.
COLLECTORS["compute_optimizer"] = ComputeOptimizerCollector()
# CloudWatch Logs analysis runs alongside regular collectors; produces
# LogScan + LogFinding rows instead of Resource rows.
COLLECTORS["logs"] = LogsCollector()

# Global services don't iterate over regions. Cost Optimization Hub is only
# reachable via its us-east-1 endpoint, so we treat it as global. Compute
# Optimizer is regional but consolidated, so we only call it once per account.
GLOBAL_SERVICES = {
    "iam",
    "s3",
    "cloudfront",
    "cost_optimization_hub",
    "compute_optimizer",
    "account",
    "organizations",
    "route53",
    "route-53",
}

# Priority order (matches tag-manager)
SERVICE_PRIORITIES = {
    "s3": 1,
    "ec2": 2,
    "rds": 3,
    "lambda": 4,
    "dynamodb": 5,
    "ecs": 6,
    "elb": 7,
    "elasticache": 8,
    "sns": 9,
    "sqs": 10,
    "cloudwatch": 11,
    "eks": 12,
    "guardduty": 13,
    "inspector": 14,
    "vpc": 15,
    "iam": 16,
    "cost_optimization_hub": 17,
    "compute_optimizer": 19,
    "account": 18,
    "organizations": 18,
    "config": 18,
    "aws-config": 18,
    "route53": 18,
    "route-53": 18,
    "acm": 20,
    "cloudfront": 21,
    "security-hub": 22,
    "efs": 23,
    "redshift": 24,
    "kinesis": 25,
    # Logs analysis runs last so findings can reference resources populated
    # by the earlier collectors in the same scan.
    "logs": 99,
}
