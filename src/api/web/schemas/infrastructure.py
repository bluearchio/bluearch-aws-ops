"""Pydantic schemas for infrastructure status endpoints.

Shared schema structure with Tag Manager CLI so frontend views can be
identical across both apps.
"""

from typing import List, Optional
from pydantic import BaseModel


class StackSetSummary(BaseModel):
    name: str
    component: str = ""
    status: str = "UNKNOWN"
    instance_count: int = 0
    healthy_count: int = 0
    failed_count: int = 0
    version: Optional[str] = None


class StackInfo(BaseModel):
    stack_name: str
    stack_type: str = ""
    component: str = ""
    status: str = "UNKNOWN"
    region: str = ""
    last_updated: Optional[str] = None
    version: Optional[str] = None
    outputs: Optional[dict] = None


class ResourceGroupInfo(BaseModel):
    exists: bool = False
    name: str = ""
    arn: Optional[str] = None
    resource_count: int = 0
    error: Optional[str] = None


class InfrastructureHealthSummary(BaseModel):
    total_stacksets: int = 0
    total_instances: int = 0
    total_stacks: int = 0
    healthy: int = 0
    degraded: int = 0
    failed: int = 0
    overall_status: str = "not_deployed"


class InfrastructureStatusResponse(BaseModel):
    health: InfrastructureHealthSummary
    stacksets: List[StackSetSummary] = []
    stacks: List[StackInfo] = []
    resource_group: ResourceGroupInfo
    account_id: Optional[str] = None
    organization_id: Optional[str] = None
    region: Optional[str] = None
    local_version: Optional[str] = None
