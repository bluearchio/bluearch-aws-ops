"""Pydantic schemas for account endpoints."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    account_name: str
    account_email: Optional[str] = None
    role_arn: Optional[str] = None
    enabled_for_discovery: bool = False
    access_check_status: Optional[str] = None
    last_discovery_at: Optional[datetime] = None
    total_resources_discovered: int = 0
    regions: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
