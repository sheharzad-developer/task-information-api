"""Request and response schemas.

Pydantic does the input validation: anything that doesn't match these
models is rejected with a 422 before it reaches the route handlers.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


TITLE_MAX = 200
DESCRIPTION_MAX = 2000


def _reject_past_date(value: date | None) -> date | None:
    if value is not None and value < date.today():
        raise ValueError("due_date cannot be in the past")
    return value


class _StrictModel(BaseModel):
    # extra="forbid": unknown fields are an error, not silently dropped.
    # str_strip_whitespace: "   " becomes "" and then fails min_length.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskCreate(_StrictModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX, examples=["Write deployment docs"])
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None

    _check_due_date = field_validator("due_date")(_reject_past_date)


class TaskUpdate(_StrictModel):
    """Partial update: only the fields sent are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None

    _check_due_date = field_validator("due_date")(_reject_past_date)

    @model_validator(mode="after")
    def _check_fields(self) -> "TaskUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        # description and due_date may be cleared with null; these may not.
        for name in ("title", "status", "priority"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class Task(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    created_at: datetime
    updated_at: datetime


class TaskList(BaseModel):
    items: list[Task]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    uptime_seconds: float
    timestamp: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
