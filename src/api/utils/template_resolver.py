"""Centralized CloudFormation template resolution.

Resolves bundled CloudFormation templates from the local package.
"""

import os
import sys
from pathlib import Path
from typing import Dict


# All available CloudFormation templates
TEMPLATE_NAMES = [
    "single_account_role.yaml",
    "cross_account_stack.yaml",
    "management_account_resources.yaml",
    "event_tracking_stack.yaml",
    "cur_stack.yaml",
]

# Default stack and role names
DEFAULT_STACK_NAME = "BlueArchCLI-Role"
DEFAULT_ROLE_NAME = "BlueArchCLIRole"
STACKSET_NAME = "BlueArchCLI-CrossAccount-Infrastructure"
CROSS_ACCOUNT_ROLE_NAME = "BlueArchRole"


def _get_version() -> str:
    """Get current CLI version from version_controller."""
    try:
        from aws.misc.version_controller import CURRENT_VERSION
        return CURRENT_VERSION
    except Exception:
        return "LOCAL"


def _get_stage() -> str:
    """Determine deployment stage from environment or version."""
    stage = os.environ.get("BLUEARCH_STAGE", "").lower()
    if stage in ("prod", "dev"):
        return stage
    version = _get_version()
    return "dev" if version == "LOCAL" else "prod"


def _get_template_path(filename: str) -> Path:
    """Get local template path, supporting PyInstaller."""
    if getattr(sys, "_MEIPASS", None):
        meipass = Path(sys._MEIPASS)
        for path in [
            meipass / "templates" / filename,
            meipass / "api" / "templates" / filename,
        ]:
            if path.exists():
                return path
    return Path(__file__).parent.parent / "templates" / filename


def _load_local_template(filename: str) -> str:
    """Load template content from local filesystem."""
    path = _get_template_path(filename)
    with open(path, "r") as f:
        return f.read()


def get_template_url_by_name(
    template_name: str, stage: str = "prod", cdn: bool = False
) -> str:
    """Return an empty URL because public builds use bundled templates."""
    return ""


def resolve_template(template_name: str) -> Dict[str, str]:
    """Resolve a CloudFormation template to a TemplateBody.

    The returned dict can be spread directly into boto3 kwargs:
        cfn_client.create_stack(StackName=..., **resolve_template("single_account_role.yaml"))

    Args:
        template_name: Filename of the template (e.g. "single_account_role.yaml")

    Returns:
        Dict with either "TemplateURL" or "TemplateBody" key
    """
    body = _load_local_template(template_name)
    return {"TemplateBody": body}


def get_template_content(template_name: str) -> str:
    """Always load the local template content (for serving via API).

    Args:
        template_name: Filename of the template

    Returns:
        Template YAML content as string
    """
    return _load_local_template(template_name)


def get_template_metadata(template_name: str) -> dict:
    """Return metadata about a template including its public URL.

    Args:
        template_name: Filename of the template

    Returns:
        Dict with name, description, public_url, version
    """
    version = _get_version()

    descriptions = {
        "single_account_role.yaml": "IAM role for single-account assume-role authentication",
        "cross_account_stack.yaml": "Cross-account IAM role with event tracking deployed via StackSet",
        "management_account_resources.yaml": "Management account resources (DynamoDB, Secrets Manager, IAM)",
        "event_tracking_stack.yaml": "EventBridge rules and SQS queue for real-time resource tracking",
        "cur_stack.yaml": "CUR infrastructure for FinOps (S3, Glue, Cost Report)",
    }

    return {
        "name": template_name,
        "description": descriptions.get(template_name, ""),
        "public_url": None,
        "version": version,
    }
