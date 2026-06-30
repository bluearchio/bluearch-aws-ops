"""FastAPI dependency injection for job manager and local request context."""
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from web.jobs import job_manager, JobManager


@dataclass(frozen=True)
class LocalUser:
    sub: str = "local"
    email: str | None = None
    groups: tuple[str, ...] = ("admin", "operator", "viewer")


async def get_db() -> AsyncGenerator[None, None]:
    """Legacy dependency kept only to fail closed during the core cutover."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Direct product database sessions moved to bluearch-core APIs.",
    )
    yield None


def get_job_manager() -> JobManager:
    """Return the global job manager singleton."""
    return job_manager


def get_current_user(request: Request) -> LocalUser:
    """Return a local dashboard user context.

    Public builds do not use BlueArch-hosted browser authentication. The local web
    dashboard is protected by loopback binding and the core service-token
    boundary between product backends and bluearch-core.
    """
    user = getattr(request.state, "user", None)
    return user if isinstance(user, LocalUser) else LocalUser()
