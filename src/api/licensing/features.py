"""Feature tiers and gate definitions.

Each feature maps to a minimum tier required to use it.
"""

from enum import Enum
from typing import Dict


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


TIER_LEVEL: Dict[Tier, int] = {
    Tier.FREE: 0,
    Tier.PRO: 1,
    Tier.ENTERPRISE: 2,
}

# Feature -> minimum tier required
FEATURE_GATES: Dict[str, Tier] = {
    # Scan & Recommendations
    "scan": Tier.FREE,
    "recommendations:list": Tier.FREE,
    "recommendations:types": Tier.FREE,

    # Alerting
    "alarm:config": Tier.PRO,
    "alarm:targets": Tier.PRO,

    # Web Dashboard
    "web:start": Tier.PRO,
    "web:write_operations": Tier.PRO,

    # Cross-account
    "cross_account": Tier.PRO,
    "optin_hub": Tier.PRO,

    # Log Analysis (scanning runs via `collector:logs`, not a dedicated gate)
    "log_analysis:errors": Tier.PRO,
    "log_analysis:ai_analyze": Tier.PRO,

    # Collectors
    "collector:ec2": Tier.FREE,
    "collector:s3": Tier.FREE,
    "collector:rds": Tier.FREE,
    "collector:iam": Tier.FREE,
    "collector:lambda": Tier.FREE,
    "collector:dynamodb": Tier.PRO,
    "collector:ecs": Tier.PRO,
    "collector:elb": Tier.PRO,
    "collector:sns": Tier.PRO,
    "collector:sqs": Tier.PRO,
    "collector:cloudwatch": Tier.PRO,
    "collector:eks": Tier.PRO,
    "collector:guardduty": Tier.PRO,
    "collector:inspector": Tier.PRO,
    "collector:acm": Tier.PRO,
    "collector:cloudfront": Tier.PRO,
    "collector:security-hub": Tier.PRO,
    "collector:elasticache": Tier.PRO,
    "collector:vpc": Tier.PRO,
    "collector:logs": Tier.PRO,
}
