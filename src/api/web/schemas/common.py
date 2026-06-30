"""Shared Pydantic schemas — pagination, generic responses."""

from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 50


class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
