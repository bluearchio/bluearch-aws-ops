"""Resource correlation for CloudWatch Log Groups.

Two-step priority matching:
1. Naming convention (no AWS API calls) — e.g. /aws/lambda/foo -> Lambda foo
2. Tag-based fallback — ListTagsForResource on unmatched groups
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from database.models import Resource

logger = logging.getLogger(__name__)


# Naming conventions — (pattern, service_name, resource_type).
# Patterns capture the resource identifier in group 1.
_NAMING_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"^/aws/lambda/(.+)$"), "lambda", "AWS::Lambda::Function"),
    (re.compile(r"^/aws/rds/instance/([^/]+)/.*$"), "rds", "AWS::RDS::DBInstance"),
    (re.compile(r"^/aws/rds/cluster/([^/]+)/.*$"), "rds", "AWS::RDS::DBCluster"),
    (re.compile(r"^/aws/ecs/containerinsights/[^/]+/([^/]+)/.*$"), "ecs", "AWS::ECS::Service"),
    (re.compile(r"^/aws/eks/([^/]+)/.*$"), "eks", "AWS::EKS::Cluster"),
    (re.compile(r"^/aws/elasticache/([^/]+).*$"), "elasticache", "AWS::ElastiCache::CacheCluster"),
    # API Gateway — expose service but no resource match in collection today
    (re.compile(r"^/aws/apigateway/([^/]+).*$"), "apigateway", "AWS::ApiGateway::RestApi"),
]

# Tag keys consulted during tag-based fallback (first present wins)
_TAG_MATCH_KEYS = (
    "ResourceId",
    "ServiceName",
    "aws:cloudformation:stack-name",
    "Name",
)


class LogGroupMapper:
    """Resolves CloudWatch Log Groups to collected Resource rows.

    Usage:
        mapper = LogGroupMapper(db_session, logs_client=boto3_logs_client)
        match = mapper.match("/aws/lambda/my-func")
        # match is None, or {"resource_id": "<uuid>", "resource_type": ..., "service_name": ...}
    """

    def __init__(self, db_session: Session, logs_client=None):
        self.db = db_session
        self.logs_client = logs_client  # Optional — only needed for tag fallback

    # -- Public --------------------------------------------------------------

    def match(self, log_group_name: str, region: Optional[str] = None) -> Optional[Dict]:
        """Match a log group to a Resource.

        Returns the linkage dict (resource_id / resource_type / service_name)
        or None if no match is found.
        """
        match = self._match_by_naming(log_group_name, region)
        if match:
            return match

        if self.logs_client is not None:
            match = self._match_by_tags(log_group_name, region)
            if match:
                return match

        return None

    # -- Naming convention ---------------------------------------------------

    def _match_by_naming(self, log_group_name: str, region: Optional[str]) -> Optional[Dict]:
        for pattern, service_name, resource_type in _NAMING_PATTERNS:
            m = pattern.match(log_group_name)
            if not m:
                continue
            candidate_id = m.group(1)

            # Query by service + resource_id substring. The resource_id stored
            # may be a full ARN or just the logical name — try both.
            resource = self._find_resource(
                service_name=service_name,
                resource_type=resource_type,
                identifier=candidate_id,
                region=region,
            )
            if resource is not None:
                return {
                    "resource_id": resource.id,
                    "resource_type": resource.resource_type,
                    "service_name": resource.service_name,
                }

            # Naming matched but resource isn't in our DB — still return hint
            # so the UI shows what it _would_ have linked to.
            return None

        return None

    def _find_resource(
        self,
        service_name: str,
        resource_type: str,
        identifier: str,
        region: Optional[str],
    ) -> Optional[Resource]:
        """Look up a Resource by service + identifier. Falls back to wider
        queries when the strict lookup misses."""
        q = self.db.query(Resource).filter(Resource.service_name == service_name)
        if region:
            q = q.filter(Resource.region == region)

        # 1) exact resource_id match
        hit = q.filter(Resource.resource_id == identifier).first()
        if hit:
            return hit

        # 2) resource_arn ends with the identifier (ARN suffix)
        hit = q.filter(Resource.resource_arn.like(f"%{identifier}")).first()
        if hit:
            return hit

        # 3) resource_id contains the identifier (e.g. cluster/service composite)
        hit = q.filter(Resource.resource_id.like(f"%{identifier}%")).first()
        return hit

    # -- Tag-based fallback --------------------------------------------------

    def _match_by_tags(self, log_group_name: str, region: Optional[str]) -> Optional[Dict]:
        try:
            resp = self.logs_client.list_tags_for_resource(
                resourceArn=self._log_group_arn(log_group_name, region)
            )
        except Exception as exc:
            logger.debug("list_tags_for_resource failed for %s: %s", log_group_name, exc)
            return None

        tags = resp.get("tags", {}) or {}
        for key in _TAG_MATCH_KEYS:
            candidate = tags.get(key)
            if not candidate:
                continue

            q = self.db.query(Resource)
            if region:
                q = q.filter(Resource.region == region)

            hit = q.filter(
                (Resource.resource_id == candidate)
                | (Resource.resource_arn == candidate)
                | (Resource.resource_arn.like(f"%{candidate}"))
            ).first()
            if hit:
                return {
                    "resource_id": hit.id,
                    "resource_type": hit.resource_type,
                    "service_name": hit.service_name,
                }

        return None

    @staticmethod
    def _log_group_arn(log_group_name: str, region: Optional[str]) -> str:
        """Build the ARN needed for ListTagsForResource.

        Falls back to a wildcard region when caller didn't supply one.
        """
        region_part = region or "*"
        # account_id omitted -> boto3 fills from caller identity; use "*" as placeholder
        return f"arn:aws:logs:{region_part}:*:log-group:{log_group_name}"
