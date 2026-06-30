"""In-memory job manager for async scan operations.

No persistence — jobs are lost on server restart. This is intentional:
scans are cheap to re-trigger and the job list is only for tracking
in-flight operations in the web dashboard.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field
from utils.logger_config import log


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str = ""
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    total: int = 0
    message: str = ""
    progress_message: Optional[str] = None
    progress_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobManager:
    MAX_COMPLETED = 100

    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        return self._jobs.get(job_id)

    def update_progress(self, job_id: str, progress: int, message: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        """Update job progress (0-100) with optional message and structured data."""
        job = self._jobs.get(job_id)
        if job:
            job.progress = min(max(progress, 0), 100)
            if message:
                job.progress_message = message
            if data:
                job.progress_data = data

    def list_jobs(self, job_type: Optional[str] = None) -> List[JobRecord]:
        jobs = list(self._jobs.values())
        if job_type:
            jobs = [j for j in jobs if j.job_type == job_type]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def submit_async(
        self,
        job_type: str,
        coro_fn: Callable[..., Coroutine],
        *args,
        **kwargs,
    ) -> JobRecord:
        """Submit an async job. Returns the JobRecord immediately."""
        job = JobRecord(job_type=job_type)
        self._jobs[job.id] = job

        async def _wrapper():
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            try:
                result = await coro_fn(job, *args, **kwargs)
                job.status = JobStatus.COMPLETED
                job.result = result if isinstance(result, dict) else {"result": result}
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                log.debug(f"Job {job.id} failed: {e}")
            finally:
                job.completed_at = datetime.now(timezone.utc)
                self._cleanup_old_jobs()

        task = asyncio.create_task(_wrapper())
        self._tasks[job.id] = task
        return job

    def _cleanup_old_jobs(self):
        terminal = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
        ]
        if len(terminal) > self.MAX_COMPLETED:
            terminal.sort(key=lambda j: j.completed_at or j.created_at)
            for j in terminal[: len(terminal) - self.MAX_COMPLETED]:
                self._jobs.pop(j.id, None)
                self._tasks.pop(j.id, None)


job_manager = JobManager()
