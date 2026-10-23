"""Task storage.

An in-memory store keeps the assignment self-contained (no database to
provision). The route handlers only talk to the TaskRepository interface,
so swapping in DynamoDB or RDS later means writing one new class.
"""

import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.models import Task, TaskCreate, TaskPriority, TaskStatus


class TaskNotFoundError(Exception):
    def __init__(self, task_id: UUID):
        self.task_id = task_id
        super().__init__(f"Task {task_id} not found")


class TaskRepository(ABC):
    @abstractmethod
    def create(self, data: TaskCreate) -> Task: ...

    @abstractmethod
    def get(self, task_id: UUID) -> Task: ...

    @abstractmethod
    def list(
        self,
        *,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Task], int]: ...

    @abstractmethod
    def update(self, task_id: UUID, changes: dict[str, Any]) -> Task: ...

    @abstractmethod
    def delete(self, task_id: UUID) -> None: ...


class InMemoryTaskRepository(TaskRepository):
    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}
        # uvicorn runs sync endpoints in a thread pool, so guard writes.
        self._lock = threading.Lock()

    def create(self, data: TaskCreate) -> Task:
        now = datetime.now(UTC)
        task = Task(id=uuid4(), created_at=now, updated_at=now, **data.model_dump())
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get(self, task_id: UUID) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise TaskNotFoundError(task_id) from None

    def list(self, *, status, priority, limit, offset):
        with self._lock:
            tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        if priority is not None:
            tasks = [t for t in tasks if t.priority == priority]
        tasks.sort(key=lambda t: t.created_at)
        return tasks[offset : offset + limit], len(tasks)

    def update(self, task_id: UUID, changes: dict[str, Any]) -> Task:
        with self._lock:
            current = self.get(task_id)
            updated = current.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
            self._tasks[task_id] = updated
        return updated

    def delete(self, task_id: UUID) -> None:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            del self._tasks[task_id]
