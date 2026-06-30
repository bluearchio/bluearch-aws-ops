"""Centralized bluearch:* tag definitions for all CloudFormation infrastructure."""

import os
from typing import Dict, List


COMPONENT_CROSS_ACCOUNT = "cross-account"
COMPONENT_ASSUME_ROLE = "assume-role"
COMPONENT_EVENT_TRACKING = "event-tracking"


def _get_app_version() -> str:
    override = os.environ.get("BLUEARCH_CLI_VERSION")
    if override:
        return override
    try:
        from aws.misc.version_controller import CURRENT_VERSION
        return CURRENT_VERSION
    except Exception:
        return "LOCAL"


def get_infrastructure_tags(component: str) -> List[Dict[str, str]]:
    """Return CF-format tags for a given component (bluearch:* + legacy).

    Args:
        component: One of the COMPONENT_* constants above.

    Returns:
        List of {"Key": ..., "Value": ...} dicts suitable for boto3 Tag parameters.
    """
    version = _get_app_version()
    return [
        {"Key": "bluearch:product", "Value": "bluearch"},
        {"Key": "bluearch:component", "Value": component},
        {"Key": "bluearch:managed-by", "Value": "bluearch-cli"},
        {"Key": "bluearch:version", "Value": version},
        {"Key": "Application", "Value": "BlueArchCLI"},
        {"Key": "ManagedBy", "Value": "bluearch-cli"},
    ]
