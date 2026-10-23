from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.models import (
    ErrorResponse,
    Task,
    TaskCreate,
    TaskList,
    TaskPriority,
    TaskStatus,
    TaskUpdate,
)
from app.repository import TaskRepository

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Task not found"}}


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository


Repo = Annotated[TaskRepository, Depends(get_repository)]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, repo: Repo, request: Request, response: Response) -> Task:
    task = repo.create(payload)
    response.headers["Location"] = str(request.url_for("get_task", task_id=task.id))
    return task


@router.get("", response_model=TaskList)
def list_tasks(
    repo: Repo,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    priority: TaskPriority | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskList:
    items, total = repo.list(status=status_filter, priority=priority, limit=limit, offset=offset)
    return TaskList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=Task, responses=_NOT_FOUND)
def get_task(task_id: UUID, repo: Repo) -> Task:
    return repo.get(task_id)


@router.patch("/{task_id}", response_model=Task, responses=_NOT_FOUND)
def update_task(task_id: UUID, payload: TaskUpdate, repo: Repo) -> Task:
    return repo.update(task_id, payload.changes())


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_NOT_FOUND)
def delete_task(task_id: UUID, repo: Repo) -> Response:
    repo.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
