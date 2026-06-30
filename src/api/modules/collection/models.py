"""Data classes for the collection system."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CollectionJob:
    """Represents a single collection job (service + region)."""

    service: str
    region: Optional[str]  # None for global services (IAM)
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    session: Any = None  # boto3.Session for cross-account


@dataclass
class CollectorResult:
    """Result from a single service collector run."""

    resources: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    permission_errors: int = 0
    permission_error_details: List[Dict[str, Any]] = field(default_factory=list)
