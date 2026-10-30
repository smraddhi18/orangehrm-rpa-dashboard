"""Local dashboard and automation API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.jobs import JobStore
from app.schemas import AutomationInput, JobView
from app.services.automation import run_automation
from app.services.employee_export import employees_to_csv

ROOT = Path(__file__).resolve().parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def create_app(
    runner: Callable[[str, AutomationInput, JobStore], None] = run_automation,
) -> FastAPI:
    app = FastAPI(title="OrangeHRM Automation Dashboard")
    app.state.jobs = JobStore()
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(
            ROOT / "templates" / "index.html", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/automation/run", response_model=JobView, status_code=202)
    def start(data: AutomationInput, background: BackgroundTasks) -> JobView:
        job = app.state.jobs.create()
        if job is None:
            raise HTTPException(
                status_code=409, detail="An automation job is already running."
            )
        background.add_task(runner, job.job_id, data, app.state.jobs)
        return job

    @app.get("/api/automation/{job_id}/status", response_model=JobView)
    def status(job_id: str) -> JobView:
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job

    @app.get("/api/automation/{job_id}/export")
    def export(job_id: str) -> Response:
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if not job.export_ready:
            raise HTTPException(
                status_code=409, detail="CSV export is not available for this job."
            )
        return Response(
            content=employees_to_csv(job.employees).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="orangehrm-employees-{job_id[:8]}.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/automation/{job_id}/preview")
    def preview(job_id: str) -> Response:
        if app.state.jobs.get(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        image = app.state.jobs.get_preview(job_id)
        if image is None:
            raise HTTPException(status_code=409, detail="Preview is not ready yet.")
        return Response(
            content=image,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
