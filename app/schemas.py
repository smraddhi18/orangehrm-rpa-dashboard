"""Request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

STEP_NAMES = (
    "opening",
    "login",
    "pim",
    "creation",
    "verification",
    "extraction",
    "logout",
    "completed",
)
StepState = Literal["pending", "running", "success", "failed", "skipped"]


class AutomationInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    first_name: str = Field(min_length=1, max_length=30)
    last_name: str = Field(min_length=1, max_length=30)
    employee_id: str = Field(min_length=1, max_length=10)

    @field_validator(
        "username", "first_name", "last_name", "employee_id", mode="before"
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("username", "first_name", "last_name", "employee_id")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Must contain visible text without control characters")
        return value

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password is required")
        return value


class Employee(BaseModel):
    employee_id: str
    first_name: str
    last_name: str


class Step(BaseModel):
    key: str
    label: str
    state: StepState = "pending"
    message: str = ""
    next_action: str = ""
    at: datetime | None = None


class JobView(BaseModel):
    job_id: str
    status: Literal["running", "success", "partial", "failed"]
    created_at: datetime
    finished_at: datetime | None = None
    steps: list[Step]
    verified_employee: Employee | None = None
    employees: list[Employee] = Field(default_factory=list)
    extracted_count: int = 0
    error: str | None = None
    export_ready: bool = False
    preview_version: int = 0
