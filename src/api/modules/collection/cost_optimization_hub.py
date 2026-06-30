"""Cost Optimization Hub collector.

Collects recommendations from AWS Cost Optimization Hub (a us-east-1 only
service) and stores them as Resource rows so they can be surfaced through the
standard recommendation pipeline.

Notes
-----
- Cost Optimization Hub must be explicitly enabled in the account. When the
  opt-in is missing, ``list_recommendations`` raises ``NotFoundException`` or
  ``AccessDeniedException``; we treat both as an empty result and log a
  warning.
- The service is global but only exposes a single regional endpoint in
  ``us-east-1``. Because of this it is listed in ``GLOBAL_SERVICES`` in the
  collectors registry and always queried against ``us-east-1``.
"""

from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from modules.collection.collectors import ServiceCollector
from modules.collection.models import CollectionJob, CollectorResult
from utils.logger_config import log


# Upper bound on the number of recommendations collected per scan. The
# paginator will stop once this many items have been accumulated.
_MAX_RECOMMENDATIONS = 1000
_PAGE_SIZE = 1000  # service max for list_recommendations


class CostOptimizationHubCollector(ServiceCollector):
    """Collect AWS Cost Optimization Hub recommendations.

    Produces Resource rows of type ``AWS::CostOptimizationHub::Recommendation``
    that the local recommendation engine fans out into standard
    Recommendation rows.
    """

    REGION = "us-east-1"
    SERVICE_NAME = "cost-optimization-hub"

    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()
        acct = job.account_id or ""

        try:
            client = self._get_client(self.SERVICE_NAME, self.REGION, job.session)
        except Exception as e:  # pragma: no cover - defensive
            result.errors.append(f"cost-optimization-hub client init failed: {e}")
            return result

        def _list_recommendations() -> None:
            items = self._list_all_recommendations(client)
            for rec in items:
                resource = self._build_resource(rec, acct)
                if resource is not None:
                    result.resources.append(resource)

        self._safe_collect(result, self.REGION, "Cost Optimization Hub", _list_recommendations)
        return result

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _list_all_recommendations(self, client) -> List[Dict[str, Any]]:
        """Page through ``list_recommendations`` with graceful opt-in handling."""
        items: List[Dict[str, Any]] = []
        next_token: Optional[str] = None

        while True:
            kwargs: Dict[str, Any] = {"maxResults": _PAGE_SIZE}
            if next_token:
                kwargs["nextToken"] = next_token

            try:
                resp = client.list_recommendations(**kwargs)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("NotFoundException", "AccessDeniedException"):
                    log.warning(
                        "Cost Optimization Hub not enabled for this account "
                        f"(error: {code}). Enable it via 'aws cost-optimization-hub "
                        "update-enrollment-status --status Active'."
                    )
                    return []
                raise

            batch = resp.get("items") or []
            items.extend(batch)

            if len(items) >= _MAX_RECOMMENDATIONS:
                return items[:_MAX_RECOMMENDATIONS]

            next_token = resp.get("nextToken")
            if not next_token:
                break

        return items

    # ------------------------------------------------------------------
    # Shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _build_resource(rec: Dict[str, Any], account_id: str) -> Optional[Dict[str, Any]]:
        """Convert a Cost Optimization Hub recommendation into a Resource dict."""
        rec_id = rec.get("recommendationId") or ""
        if not rec_id:
            return None

        # Some SDK versions return ``recommendationArn`` for the ARN, others use
        # ``resourceArn`` for the underlying resource. Prefer the recommendation
        # ARN when present and fall back to a synthetic ARN built from the id.
        rec_arn = (
            rec.get("recommendationArn")
            or rec.get("resourceArn")
            or f"arn:aws:cost-optimization-hub::{account_id}:recommendation/{rec_id}"
        )

        estimated_savings = rec.get("estimatedMonthlySavings")
        savings_percentage = rec.get("estimatedSavingsPercentage")

        metadata: Dict[str, Any] = {
            "recommendation_id": rec_id,
            "actionType": rec.get("actionType"),
            "currentResourceType": rec.get("currentResourceType"),
            "recommendedResourceType": rec.get("recommendedResourceType"),
            "estimatedMonthlySavings": estimated_savings,
            "estimatedSavingsPercentage": savings_percentage,
            "currencyCode": rec.get("currencyCode"),
            "implementationEffort": rec.get("implementationEffort"),
            "restartNeeded": rec.get("restartNeeded"),
            "source": rec.get("source"),
            "recommendationLookbackPeriodInDays": rec.get("recommendationLookbackPeriodInDays"),
            "currentResourceSummary": rec.get("currentResourceSummary"),
            "recommendedResourceSummary": rec.get("recommendedResourceSummary"),
        }

        return {
            "resource_arn": rec_arn,
            "resource_type": "AWS::CostOptimizationHub::Recommendation",
            "service_name": "cost-optimization-hub",
            "region": rec.get("region") or "us-east-1",
            "account_id": rec.get("accountId") or account_id,
            "resource_id": rec_id,
            "created_at": rec.get("lastRefreshTimestamp"),
            "current_tags": {},
            "metadata_json": metadata,
        }
