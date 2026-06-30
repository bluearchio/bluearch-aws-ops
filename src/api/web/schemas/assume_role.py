"""Pydantic schemas for assume-role endpoints."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AssumeRoleConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    role_arn: str
    role_name: str = "BlueArchCLIRole"
    external_id: Optional[str] = None
    is_active: bool = False
    enabled: bool = True
    alias: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class AddAssumeRoleRequest(BaseModel):
    account_id: str = Field(..., min_length=12, max_length=12)
    role_name: str = Field(default="BlueArchCLIRole", max_length=64)
    external_id: Optional[str] = None
    alias: Optional[str] = Field(default=None, max_length=64)


class TestResultResponse(BaseModel):
    success: bool
    account_id: str
    role_arn: str
    assumed_identity: Optional[str] = None
    error: Optional[str] = None
