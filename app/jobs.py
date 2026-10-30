"""Thread-safe, process-local job tracking. Passwords never enter this store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from app.schemas import STEP_NAMES, Employee, JobView, Step, StepState

LABELS = (
    "Opening OrangeHRM",
    "Logging in",
    "Navigating to PIM",
    "Adding employee",
    "Verifying employee",
    "Extracting employees",
    "Logging out",
    "Completed",
)
logger = logging.getLogger(__name__)


class JobStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, JobView] = {}
        self._previews: dict[str, bytes] = {}
        self._active: str | None = None

    def create(self) -> JobView | None:
        with self._lock:
            if self._active is not None:
                return None
            job = JobView(
                job_id=uuid4().hex,
                status="running",
                created_at=datetime.now(timezone.utc),
                steps=[
                    Step(key=key, label=label) for key, label in zip(STEP_NAMES, LABELS)
                ],
            )
            self._jobs[job.job_id] = job
            self._active = job.job_id
            logger.info("job=%s started", job.job_id)
            return job.model_copy(deep=True)

    def get(self, job_id: str) -> JobView | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def step(
        self,
        job_id: str,
        key: str,
        state: StepState,
        message: str = "",
        next_action: str = "",
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            step = next(item for item in job.steps if item.key == key)
            step.state = state
            step.message = message
            step.next_action = next_action
            step.at = datetime.now(timezone.utc)
            logger.info(
                "job=%s step=%s state=%s message=%s", job_id, key, state, message
            )

    def set_verified(self, job_id: str, employee: Employee) -> None:
        with self._lock:
            self._jobs[job_id].verified_employee = employee

    def set_employees(self, job_id: str, employees: list[Employee]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.employees = employees
            job.extracted_count = len(employees)
            job.export_ready = True

    def set_preview(self, job_id: str, image: bytes) -> None:
        with self._lock:
            self._previews[job_id] = image
            self._jobs[job_id].preview_version += 1

    def get_preview(self, job_id: str) -> bytes | None:
        with self._lock:
            return self._previews.get(job_id)

    def finish(self, job_id: str, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            failures = [step for step in job.steps if step.state == "failed"]
            job.status = (
                "partial"
                if failures and job.verified_employee
                else "failed"
                if failures
                else "success"
            )
            job.error = error
            job.finished_at = datetime.now(timezone.utc)
            if self._active == job_id:
                self._active = None
            logger.info("job=%s finished status=%s", job_id, job.status)
