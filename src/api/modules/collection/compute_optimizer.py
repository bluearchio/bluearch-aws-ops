"""AWS Compute Optimizer collector and recommendation mappers.

The Compute Optimizer service is consolidated across regions: a single API
call returns recommendations for every region where the service is enabled.
For that reason, this collector runs once per account using a fixed home
region (defaults to ``us-east-1``). It is registered as a "global" service
in the scanner so the normal per-region iteration is skipped.

The collector writes one ``Resource`` row per Compute Optimizer finding:

    ``AWS::ComputeOptimizer::EC2InstanceRecommendation``
    ``AWS::ComputeOptimizer::EBSVolumeRecommendation``
    ``AWS::ComputeOptimizer::LambdaFunctionRecommendation``
    ``AWS::ComputeOptimizer::AutoScalingGroupRecommendation``
    ``AWS::ComputeOptimizer::ECSServiceRecommendation``
    ``AWS::ComputeOptimizer::RDSDatabaseRecommendation``

The full raw finding (current type, recommended options, savings, risk,
finding reason codes) is persisted in ``metadata_json``. Recommendation
mappers in this module turn those resource rows into 28 distinct
``Recommendation`` rows mapped from ``findingReasonCodes``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List, Optional

from botocore.exceptions import ClientError

from database.models import Resource
from modules.collection.collectors import ServiceCollector
from modules.collection.models import CollectionJob, CollectorResult
from utils.logger_config import log


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Home region to talk to Compute Optimizer from. The service is regional but
#: returns a consolidated view across all regions it has been enabled in.
COMPUTE_OPTIMIZER_HOME_REGION = "us-east-1"

#: Resource type strings written by the collector.
RT_EC2 = "AWS::ComputeOptimizer::EC2InstanceRecommendation"
RT_EBS = "AWS::ComputeOptimizer::EBSVolumeRecommendation"
RT_LAMBDA = "AWS::ComputeOptimizer::LambdaFunctionRecommendation"
RT_ASG = "AWS::ComputeOptimizer::AutoScalingGroupRecommendation"
RT_ECS = "AWS::ComputeOptimizer::ECSServiceRecommendation"
RT_RDS = "AWS::ComputeOptimizer::RDSDatabaseRecommendation"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class ComputeOptimizerCollector(ServiceCollector):
    """Collects AWS Compute Optimizer findings into Resource rows.

    The collector wraps six Compute Optimizer paginated APIs and is tolerant
    of the ``OptInRequiredException`` raised when the service has not been
    enrolled for the account. Individual API failures (throttling, access
    denied) are captured via :meth:`ServiceCollector._safe_collect` and do
    not abort sibling collections.
    """

    #: Set of exception codes that indicate the service is not opted in.
    OPT_IN_ERROR_CODES = {"OptInRequiredException", "AccessDeniedException"}

    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id or ""
        # Compute Optimizer is consolidated — always talk to it from the home
        # region regardless of what the job requested.
        region = job.region or COMPUTE_OPTIMIZER_HOME_REGION

        try:
            co = self._get_client("compute-optimizer", region, job.session)
        except Exception as e:  # pragma: no cover - defensive
            result.errors.append(f"ComputeOptimizer client init failed: {e}")
            return result

        # Each sub-collection is wrapped in an opt-in guard so that a single
        # missing service enrollment does not abort the others.
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer EC2",
            lambda: self._collect_ec2(co, result, acct, region),
        )
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer EBS",
            lambda: self._collect_ebs(co, result, acct, region),
        )
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer Lambda",
            lambda: self._collect_lambda(co, result, acct, region),
        )
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer ASG",
            lambda: self._collect_asg(co, result, acct, region),
        )
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer ECS",
            lambda: self._collect_ecs(co, result, acct, region),
        )
        self._safe_collect(
            result,
            region,
            "ComputeOptimizer RDS",
            lambda: self._collect_rds(co, result, acct, region),
        )
        return result

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _guarded_call(
        self,
        fn: Callable[[], Dict[str, Any]],
        result: CollectorResult,
        account_id: str,
        region: str,
    ) -> Optional[Dict[str, Any]]:
        """Call a Compute Optimizer API, tolerating opt-in errors.

        Returns ``None`` if the service is not opted in, otherwise returns
        the raw response dict. Other ClientErrors propagate so that
        :meth:`ServiceCollector._safe_collect` can count them.
        """
        try:
            return fn()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.OPT_IN_ERROR_CODES:
                self._record_opt_in_warning(result, code, account_id, region)
                log.warning(
                    "Compute Optimizer not opted-in (%s); skipping collection",
                    code,
                )
                return None
            raise

    @staticmethod
    def _record_opt_in_warning(
        result: CollectorResult,
        code: str,
        account_id: str,
        region: str,
    ) -> None:
        """Record one frontend-visible opt-in warning per account."""
        if any(
            w.get("type") == "opt_in_required"
            and w.get("service") == "compute-optimizer"
            and w.get("account_id") == account_id
            for w in result.warnings
        ):
            return

        account_label = account_id or "this account"
        result.warnings.append({
            "type": "opt_in_required",
            "service": "compute-optimizer",
            "severity": "warning",
            "account_id": account_id,
            "region": region,
            "code": code,
            "message": (
                f"Compute Optimizer is not active for account {account_label}; "
                "Compute Optimizer recommendations were skipped."
            ),
            "suggestion": (
                "Open Opt-In Hub and activate Compute Optimizer for this account."
            ),
            "action_label": "Open Opt-In Hub",
            "action_route": "/optin-hub",
        })

    @staticmethod
    def _paginate_all(
        client,
        method: str,
        result_key: str,
    ) -> List[Dict[str, Any]]:
        """Manually paginate a Compute Optimizer API.

        The compute-optimizer service defines ``nextToken`` pagination which
        boto3 exposes through its native paginator. We use the paginator to
        stay consistent with other collectors but fall back to manual looping
        when a paginator is not registered for a given method.
        """
        try:
            paginator = client.get_paginator(method)
            items: List[Dict[str, Any]] = []
            for page in paginator.paginate():
                items.extend(page.get(result_key, []) or [])
            return items
        except Exception:
            # Fall back to manual pagination.
            items = []
            token: Optional[str] = None
            while True:
                kwargs = {"nextToken": token} if token else {}
                resp = getattr(client, method)(**kwargs)
                items.extend(resp.get(result_key, []) or [])
                token = resp.get("nextToken")
                if not token:
                    break
            return items

    # ------------------------------------------------------------------
    # Per-API collectors
    # ------------------------------------------------------------------

    def _collect_ec2(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "instanceRecommendations": self._paginate_all(
                    co,
                    "get_ec2_instance_recommendations",
                    "instanceRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["instanceRecommendations"]:
            arn = rec.get("instanceArn") or ""
            instance_id = arn.rsplit("/", 1)[-1] if arn else ""
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "ec2-rec", acct, region, instance_id or arn
                    ),
                    "resource_type": RT_EC2,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": instance_id or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "instance_arn": arn,
                        "instance_name": rec.get("instanceName"),
                        "current_instance_type": rec.get("currentInstanceType"),
                        "finding": rec.get("finding"),
                        "finding_reason_codes": list(
                            rec.get("findingReasonCodes") or []
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                        "recommendation_options": _sanitize_options(
                            rec.get("recommendationOptions")
                        ),
                        "current_performance_risk": rec.get(
                            "currentPerformanceRisk"
                        ),
                        "effective_recommendation_preferences": rec.get(
                            "effectiveRecommendationPreferences"
                        ),
                    },
                }
            )

    def _collect_ebs(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "volumeRecommendations": self._paginate_all(
                    co,
                    "get_ebs_volume_recommendations",
                    "volumeRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["volumeRecommendations"]:
            arn = rec.get("volumeArn") or ""
            volume_id = arn.rsplit("/", 1)[-1] if arn else ""
            current = rec.get("currentConfiguration") or {}
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "ebs-rec", acct, region, volume_id or arn
                    ),
                    "resource_type": RT_EBS,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": volume_id or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "volume_arn": arn,
                        "finding": rec.get("finding"),
                        "current_configuration": current,
                        "volume_recommendation_options": _sanitize_options(
                            rec.get("volumeRecommendationOptions")
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                    },
                }
            )

    def _collect_lambda(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "lambdaFunctionRecommendations": self._paginate_all(
                    co,
                    "get_lambda_function_recommendations",
                    "lambdaFunctionRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["lambdaFunctionRecommendations"]:
            arn = rec.get("functionArn") or ""
            fn_name = arn.split(":function:", 1)[-1] if ":function:" in arn else arn
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "lambda-rec", acct, region, fn_name or arn
                    ),
                    "resource_type": RT_LAMBDA,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": fn_name or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "function_arn": arn,
                        "function_version": rec.get("functionVersion"),
                        "current_memory_size": rec.get("currentMemorySize"),
                        "number_of_invocations": rec.get("numberOfInvocations"),
                        "finding": rec.get("finding"),
                        "finding_reason_codes": list(
                            rec.get("findingReasonCodes") or []
                        ),
                        "memory_size_recommendation_options": _sanitize_options(
                            rec.get("memorySizeRecommendationOptions")
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                        "current_performance_risk": rec.get(
                            "currentPerformanceRisk"
                        ),
                    },
                }
            )

    def _collect_asg(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "autoScalingGroupRecommendations": self._paginate_all(
                    co,
                    "get_auto_scaling_group_recommendations",
                    "autoScalingGroupRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["autoScalingGroupRecommendations"]:
            arn = rec.get("autoScalingGroupArn") or ""
            asg_name = (
                rec.get("autoScalingGroupName")
                or (arn.rsplit("/", 1)[-1] if arn else "")
            )
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "asg-rec", acct, region, asg_name or arn
                    ),
                    "resource_type": RT_ASG,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": asg_name or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "auto_scaling_group_arn": arn,
                        "auto_scaling_group_name": asg_name,
                        "finding": rec.get("finding"),
                        "finding_reason_codes": list(
                            rec.get("findingReasonCodes") or []
                        ),
                        "current_configuration": rec.get(
                            "currentConfiguration"
                        ),
                        "recommendation_options": _sanitize_options(
                            rec.get("recommendationOptions")
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                        "current_performance_risk": rec.get(
                            "currentPerformanceRisk"
                        ),
                    },
                }
            )

    def _collect_ecs(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "ecsServiceRecommendations": self._paginate_all(
                    co,
                    "get_ecs_service_recommendations",
                    "ecsServiceRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["ecsServiceRecommendations"]:
            arn = rec.get("serviceArn") or ""
            svc_name = arn.rsplit("/", 1)[-1] if arn else ""
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "ecs-rec", acct, region, svc_name or arn
                    ),
                    "resource_type": RT_ECS,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": svc_name or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "service_arn": arn,
                        "launch_type": rec.get("launchType"),
                        "finding": rec.get("finding"),
                        "finding_reason_codes": list(
                            rec.get("findingReasonCodes") or []
                        ),
                        "current_service_configuration": rec.get(
                            "currentServiceConfiguration"
                        ),
                        "service_recommendation_options": _sanitize_options(
                            rec.get("serviceRecommendationOptions")
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                        "current_performance_risk": rec.get(
                            "currentPerformanceRisk"
                        ),
                    },
                }
            )

    def _collect_rds(
        self, co, result: CollectorResult, acct: str, region: str
    ) -> None:
        items = self._guarded_call(
            lambda: {
                "rdsDBRecommendations": self._paginate_all(
                    co,
                    "get_rds_database_recommendations",
                    "rdsDBRecommendations",
                )
            },
            result,
            acct,
            region,
        )
        if items is None:
            return
        for rec in items["rdsDBRecommendations"]:
            arn = rec.get("resourceArn") or ""
            db_id = arn.rsplit(":", 1)[-1] if arn else ""
            result.resources.append(
                {
                    "resource_arn": self._synthetic_arn(
                        "rds-rec", acct, region, db_id or arn
                    ),
                    "resource_type": RT_RDS,
                    "service_name": "compute-optimizer",
                    "region": rec.get("currentRegion") or region,
                    "account_id": acct,
                    "resource_id": db_id or arn,
                    "current_tags": {},
                    "metadata_json": {
                        "resource_arn": arn,
                        "engine": rec.get("engine"),
                        "engine_version": rec.get("engineVersion"),
                        "current_db_instance_class": rec.get(
                            "currentDBInstanceClass"
                        ),
                        "instance_finding": rec.get("instanceFinding"),
                        "storage_finding": rec.get("storageFinding"),
                        "instance_finding_reason_codes": list(
                            rec.get("instanceFindingReasonCodes") or []
                        ),
                        "storage_finding_reason_codes": list(
                            rec.get("storageFindingReasonCodes") or []
                        ),
                        "instance_recommendation_options": _sanitize_options(
                            rec.get("instanceRecommendationOptions")
                        ),
                        "storage_recommendation_options": _sanitize_options(
                            rec.get("storageRecommendationOptions")
                        ),
                        "current_instance_performance_risk": rec.get(
                            "currentInstancePerformanceRisk"
                        ),
                        "look_back_period_in_days": rec.get(
                            "lookBackPeriodInDays"
                        ),
                    },
                }
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _synthetic_arn(kind: str, account_id: str, region: str, ident: str) -> str:
        """Generate a stable synthetic ARN for a Compute Optimizer finding.

        Compute Optimizer recommendations do not themselves have ARNs, so we
        synthesize one from the service, account, region, and target resource
        identifier. Uniqueness matters because ``Resource.resource_arn`` has a
        UNIQUE constraint at the database level.
        """
        safe = (ident or "unknown").replace("/", "_").replace(":", "_")
        return f"arn:aws:compute-optimizer:{region}:{account_id}:{kind}/{safe}"


def _sanitize_options(options: Any) -> List[Dict[str, Any]]:
    """Strip non-JSON-safe fields from recommendation option lists.

    The Compute Optimizer SDK returns nested dicts with datetimes and floats;
    we preserve scalars and nested dicts/lists but coerce anything exotic to
    strings so the whole payload survives SQLite JSON serialization.
    """
    if not options:
        return []
    cleaned: List[Dict[str, Any]] = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        cleaned.append({k: _coerce(v) for k, v in opt.items()})
    return cleaned


def _coerce(value: Any) -> Any:
    """Recursively coerce values into JSON-safe primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


# ---------------------------------------------------------------------------
# Recommendation mappers
# ---------------------------------------------------------------------------

# Imported lazily in the mapper functions to avoid a circular import:
# ``recommendations.py`` imports this module to extend ``RECOMMENDATION_FUNCTIONS``.


def _co_rec_id(rec_type: str, resource_id: str, account_id: str, region: str) -> str:
    """Deterministic recommendation unique_id (SHA256) — mirrors recommendations.py."""
    raw = f"{rec_type}:{resource_id}:{account_id}:{region}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _top_recommended(meta: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """Return the first (top-ranked) recommendation option if present."""
    opts = meta.get(key) or []
    return opts[0] if opts else None


def _best_savings(option: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract the monthly savings value from a recommendation option."""
    if not option:
        return None
    saving = option.get("savingsOpportunity") or {}
    monthly = saving.get("estimatedMonthlySavings") or {}
    return monthly.get("value")


def _base_attrs(r: Resource, meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "resource_id": r.resource_id,
        "CurrentRegion": r.region,
        "Finding": meta.get("finding"),
        "FindingReasonCodes": meta.get("finding_reason_codes"),
    }


def _make(rec_type: str, r: Resource, attrs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unique_id": _co_rec_id(rec_type, r.resource_id, r.account_id, r.region),
        "recommendation_type": rec_type,
        "region_name": r.region,
        "account_id": r.account_id,
        "db_resource_id": r.id,
        "attributes": attrs,
    }


# ---- EC2 mappers (9) ----------------------------------------------------


def _ec2_mapper(reason_code: str, rec_type: str):
    """Build a recommendation function filtering EC2 findings by reason code."""

    def _fn(resources: List[Resource]) -> List[Dict]:
        out: List[Dict] = []
        for r in resources:
            if r.resource_type != RT_EC2:
                continue
            meta = r.metadata_json or {}
            codes = meta.get("finding_reason_codes") or []
            if reason_code not in codes:
                continue
            top = _top_recommended(meta, "recommendation_options")
            attrs = _base_attrs(r, meta)
            attrs.update(
                {
                    "CurrentInstanceType": meta.get("current_instance_type"),
                    "RecommendedInstanceType": (top or {}).get("instanceType"),
                    "PerformanceRisk": (top or {}).get("performanceRisk"),
                    "EstimatedMonthlySavingsUSD": _best_savings(top),
                    "ActionRationale": f"Compute Optimizer: {reason_code}",
                }
            )
            out.append(_make(rec_type, r, attrs))
        return out

    _fn.__name__ = rec_type
    return _fn


ec2_cpu_overprovisioned = _ec2_mapper("CPUOverprovisioned", "ec2_cpu_overprovisioned")
ec2_cpu_underprovisioned = _ec2_mapper("CPUUnderprovisioned", "ec2_cpu_underprovisioned")
ec2_memory_overprovisioned = _ec2_mapper(
    "MemoryOverprovisioned", "ec2_memory_overprovisioned"
)
ec2_memory_underprovisioned = _ec2_mapper(
    "MemoryUnderprovisioned", "ec2_memory_underprovisioned"
)
ec2_network_bandwidth_overprovisioned = _ec2_mapper(
    "NetworkBandwidthOverprovisioned", "ec2_network_bandwidth_overprovisioned"
)
ec2_network_bandwidth_underprovisioned = _ec2_mapper(
    "NetworkBandwidthUnderprovisioned", "ec2_network_bandwidth_underprovisioned"
)
ec2_network_pps_overprovisioned = _ec2_mapper(
    "NetworkPPSOverprovisioned", "ec2_network_pps_overprovisioned"
)
ec2_network_pps_underprovisioned = _ec2_mapper(
    "NetworkPPSUnderprovisioned", "ec2_network_pps_underprovisioned"
)


def ec2_license_not_optimized(resources: List[Resource]) -> List[Dict]:
    """EC2 licenses flagged by Compute Optimizer as not optimized."""
    out: List[Dict] = []
    license_codes = {
        "LicenseOverprovisioned",
        "LicenseUnderprovisioned",
        "LicenseNotOptimized",
    }
    for r in resources:
        if r.resource_type != RT_EC2:
            continue
        meta = r.metadata_json or {}
        codes = set(meta.get("finding_reason_codes") or [])
        if not codes & license_codes:
            continue
        top = _top_recommended(meta, "recommendation_options")
        attrs = _base_attrs(r, meta)
        attrs.update(
            {
                "CurrentInstanceType": meta.get("current_instance_type"),
                "RecommendedInstanceType": (top or {}).get("instanceType"),
                "EstimatedMonthlySavingsUSD": _best_savings(top),
                "ActionRationale": "Compute Optimizer: license not optimized",
            }
        )
        out.append(_make("ec2_license_not_optimized", r, attrs))
    return out


# ---- EBS mappers (3) ----------------------------------------------------


def _ebs_mapper(reason_code: str, rec_type: str):
    def _fn(resources: List[Resource]) -> List[Dict]:
        out: List[Dict] = []
        for r in resources:
            if r.resource_type != RT_EBS:
                continue
            meta = r.metadata_json or {}
            # EBS findings expose reason info indirectly through
            # currentConfiguration vs volumeRecommendationOptions[0].configuration.
            current = meta.get("current_configuration") or {}
            top = _top_recommended(meta, "volume_recommendation_options")
            recommended = (top or {}).get("configuration") or {}
            if reason_code == "VolumeType":
                if (
                    current.get("volumeType")
                    and recommended.get("volumeType")
                    and current.get("volumeType") != recommended.get("volumeType")
                ):
                    pass
                else:
                    continue
            elif reason_code == "VolumeIOPS":
                if current.get("volumeBaselineIOPS") != recommended.get(
                    "volumeBaselineIOPS"
                ):
                    pass
                else:
                    continue
            elif reason_code == "VolumeSize":
                if current.get("volumeSize") != recommended.get("volumeSize"):
                    pass
                else:
                    continue
            attrs = _base_attrs(r, meta)
            attrs.update(
                {
                    "CurrentConfiguration": current,
                    "RecommendedConfiguration": recommended,
                    "EstimatedMonthlySavingsUSD": _best_savings(top),
                    "ActionRationale": f"Compute Optimizer EBS: {reason_code}",
                }
            )
            out.append(_make(rec_type, r, attrs))
        return out

    _fn.__name__ = rec_type
    return _fn


ebs_rightsize_volume_type = _ebs_mapper("VolumeType", "ebs_rightsize_volume_type")
ebs_rightsize_volume_iops = _ebs_mapper("VolumeIOPS", "ebs_rightsize_volume_iops")
ebs_rightsize_volume_size = _ebs_mapper("VolumeSize", "ebs_rightsize_volume_size")


# ---- Lambda mapper (1) --------------------------------------------------


def lambda_rightsize_memory(resources: List[Resource]) -> List[Dict]:
    """Lambda functions that Compute Optimizer recommends resizing."""
    out: List[Dict] = []
    actionable = {"NotOptimized", "Optimized"}  # anything but Unavailable
    for r in resources:
        if r.resource_type != RT_LAMBDA:
            continue
        meta = r.metadata_json or {}
        finding = meta.get("finding")
        if finding not in actionable or finding == "Optimized":
            continue
        top = _top_recommended(meta, "memory_size_recommendation_options")
        attrs = _base_attrs(r, meta)
        attrs.update(
            {
                "CurrentMemorySize": meta.get("current_memory_size"),
                "RecommendedMemorySize": (top or {}).get("memorySize"),
                "EstimatedMonthlySavingsUSD": _best_savings(top),
                "ActionRationale": "Compute Optimizer: Lambda memory not optimized",
            }
        )
        out.append(_make("lambda_rightsize_memory", r, attrs))
    return out


# ---- ASG mapper (1) -----------------------------------------------------


def asg_not_optimized(resources: List[Resource]) -> List[Dict]:
    """Auto Scaling Groups flagged as NotOptimized."""
    out: List[Dict] = []
    for r in resources:
        if r.resource_type != RT_ASG:
            continue
        meta = r.metadata_json or {}
        if meta.get("finding") != "NotOptimized":
            continue
        top = _top_recommended(meta, "recommendation_options")
        current = meta.get("current_configuration") or {}
        attrs = _base_attrs(r, meta)
        attrs.update(
            {
                "AutoScalingGroupName": meta.get("auto_scaling_group_name"),
                "CurrentInstanceType": current.get("instanceType"),
                "RecommendedInstanceType": (top or {}).get("instanceType"),
                "EstimatedMonthlySavingsUSD": _best_savings(top),
                "ActionRationale": "Compute Optimizer: ASG not optimized",
            }
        )
        out.append(_make("asg_not_optimized", r, attrs))
    return out


# ---- ECS/Fargate mappers (4) -------------------------------------------


def _ecs_mapper(reason_code: str, rec_type: str):
    def _fn(resources: List[Resource]) -> List[Dict]:
        out: List[Dict] = []
        for r in resources:
            if r.resource_type != RT_ECS:
                continue
            meta = r.metadata_json or {}
            codes = meta.get("finding_reason_codes") or []
            if reason_code not in codes:
                continue
            top = _top_recommended(meta, "service_recommendation_options")
            current = meta.get("current_service_configuration") or {}
            attrs = _base_attrs(r, meta)
            attrs.update(
                {
                    "CurrentCPU": current.get("cpu"),
                    "CurrentMemory": current.get("memory"),
                    "RecommendedCPU": (top or {}).get("cpu"),
                    "RecommendedMemory": (top or {}).get("memory"),
                    "EstimatedMonthlySavingsUSD": _best_savings(top),
                    "ActionRationale": f"Compute Optimizer ECS/Fargate: {reason_code}",
                }
            )
            out.append(_make(rec_type, r, attrs))
        return out

    _fn.__name__ = rec_type
    return _fn


ecs4fargate_cpu_overprovisioned = _ecs_mapper(
    "CPUOverprovisioned", "ecs4fargate_cpu_overprovisioned"
)
ecs4fargate_cpu_underprovisioned = _ecs_mapper(
    "CPUUnderprovisioned", "ecs4fargate_cpu_underprovisioned"
)
ecs4fargate_memory_overprovisioned = _ecs_mapper(
    "MemoryOverprovisioned", "ecs4fargate_memory_overprovisioned"
)
ecs4fargate_memory_underprovisioned = _ecs_mapper(
    "MemoryUnderprovisioned", "ecs4fargate_memory_underprovisioned"
)


# ---- RDS mappers (11) --------------------------------------------------


def _rds_mapper(reason_code: str, rec_type: str, *, storage: bool = False):
    """Build a recommendation function for an RDS finding reason code.

    ``storage=True`` reads from storage_finding_reason_codes instead of the
    instance side, because Compute Optimizer splits RDS findings across two
    dimensions.
    """
    reason_key = (
        "storage_finding_reason_codes" if storage else "instance_finding_reason_codes"
    )
    options_key = (
        "storage_recommendation_options"
        if storage
        else "instance_recommendation_options"
    )

    def _fn(resources: List[Resource]) -> List[Dict]:
        out: List[Dict] = []
        for r in resources:
            if r.resource_type != RT_RDS:
                continue
            meta = r.metadata_json or {}
            codes = meta.get(reason_key) or []
            if reason_code not in codes:
                continue
            top = _top_recommended(meta, options_key)
            attrs = _base_attrs(r, meta)
            attrs.update(
                {
                    "Engine": meta.get("engine"),
                    "EngineVersion": meta.get("engine_version"),
                    "CurrentDBInstanceClass": meta.get("current_db_instance_class"),
                    "RecommendedOption": top,
                    "EstimatedMonthlySavingsUSD": _best_savings(top),
                    "ActionRationale": f"Compute Optimizer RDS: {reason_code}",
                }
            )
            out.append(_make(rec_type, r, attrs))
        return out

    _fn.__name__ = rec_type
    return _fn


rds_cpu_overprovisioned = _rds_mapper("CPUOverprovisioned", "rds_cpu_overprovisioned")
rds_cpu_underprovisioned = _rds_mapper(
    "CPUUnderprovisioned", "rds_cpu_underprovisioned"
)
rds_new_engine_version_available = _rds_mapper(
    "NewEngineVersionAvailable", "rds_new_engine_version_available"
)
rds_new_generation_instance_class_available = _rds_mapper(
    "NewGenerationDBInstanceClassAvailable",
    "rds_new_generation_instance_class_available",
)
rds_network_bandwidth_overprovisioned = _rds_mapper(
    "NetworkBandwidthOverprovisioned", "rds_network_bandwidth_overprovisioned"
)
rds_network_bandwidth_underprovisioned = _rds_mapper(
    "NetworkBandwidthUnderprovisioned", "rds_network_bandwidth_underprovisioned"
)
rds_ebs_throughput_overprovisioned = _rds_mapper(
    "EBSThroughputOverprovisioned",
    "rds_ebs_throughput_overprovisioned",
    storage=True,
)
rds_ebs_throughput_underprovisioned = _rds_mapper(
    "EBSThroughputUnderprovisioned",
    "rds_ebs_throughput_underprovisioned",
    storage=True,
)
rds_ebs_iops_overprovisioned = _rds_mapper(
    "EBSIOPSOverprovisioned", "rds_ebs_iops_overprovisioned", storage=True
)
rds_ebs_new_generation_storage_type_available = _rds_mapper(
    "NewGenerationStorageTypeAvailable",
    "rds_ebs_new_generation_storage_type_available",
    storage=True,
)
rds_ebs_volume_allocated_storage_underprovisioned = _rds_mapper(
    "EBSVolumeAllocatedStorageUnderprovisioned",
    "rds_ebs_volume_allocated_storage_underprovisioned",
    storage=True,
)


# ---------------------------------------------------------------------------
# Exported registry of all 28 mapper functions
# ---------------------------------------------------------------------------

COMPUTE_OPTIMIZER_RECOMMENDATION_FUNCTIONS: List[Callable[[List[Resource]], List[Dict]]] = [
    # EC2 (9)
    ec2_cpu_overprovisioned,
    ec2_cpu_underprovisioned,
    ec2_memory_overprovisioned,
    ec2_memory_underprovisioned,
    ec2_network_bandwidth_overprovisioned,
    ec2_network_bandwidth_underprovisioned,
    ec2_network_pps_overprovisioned,
    ec2_network_pps_underprovisioned,
    ec2_license_not_optimized,
    # EBS (3)
    ebs_rightsize_volume_type,
    ebs_rightsize_volume_iops,
    ebs_rightsize_volume_size,
    # Lambda (1)
    lambda_rightsize_memory,
    # ASG (1)
    asg_not_optimized,
    # ECS/Fargate (4)
    ecs4fargate_cpu_overprovisioned,
    ecs4fargate_cpu_underprovisioned,
    ecs4fargate_memory_overprovisioned,
    ecs4fargate_memory_underprovisioned,
    # RDS (11)
    rds_cpu_overprovisioned,
    rds_cpu_underprovisioned,
    rds_new_engine_version_available,
    rds_new_generation_instance_class_available,
    rds_network_bandwidth_overprovisioned,
    rds_network_bandwidth_underprovisioned,
    rds_ebs_throughput_overprovisioned,
    rds_ebs_throughput_underprovisioned,
    rds_ebs_iops_overprovisioned,
    rds_ebs_new_generation_storage_type_available,
    rds_ebs_volume_allocated_storage_underprovisioned,
]

assert len(COMPUTE_OPTIMIZER_RECOMMENDATION_FUNCTIONS) == 29, (
    "Expected 29 Compute Optimizer recommendation types, "
    f"got {len(COMPUTE_OPTIMIZER_RECOMMENDATION_FUNCTIONS)}"
)
