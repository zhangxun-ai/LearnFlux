from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import BackgroundTasks
from fastapi import HTTPException
import pytest

from video_transcript_api.api.routes import tasks


def test_local_quote_route_queues_only_the_winning_claim(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks.cache_manager,
        "get_task_by_id",
        lambda task_id: {"task_id": task_id, "owner_user_id": "user-1"},
    )
    monkeypatch.setattr(tasks, "_require_task_owner", lambda *args, **kwargs: None)
    quote = SimpleNamespace(media_ref="opaque-ref")
    outcomes = iter(((quote, True), (quote, False)))
    monkeypatch.setattr(
        tasks,
        "claim_cloud_quote_local_selection",
        lambda task_id, owner: next(outcomes),
    )

    winning_tasks = BackgroundTasks()
    winning = asyncio.run(
        tasks.use_local_for_cloud_quote(
            "task-1", winning_tasks, {"user_id": "user-1"}
        )
    )
    duplicate_tasks = BackgroundTasks()
    duplicate = asyncio.run(
        tasks.use_local_for_cloud_quote(
            "task-1", duplicate_tasks, {"user_id": "user-1"}
        )
    )

    assert winning.code == duplicate.code == 202
    assert len(winning_tasks.tasks) == 1
    assert winning_tasks.tasks[0].func is tasks.resume_cloud_quote_locally
    assert winning_tasks.tasks[0].kwargs["claim_owner"].startswith("local:")
    assert duplicate_tasks.tasks == []


def test_cancel_task_marks_owned_nonterminal_task_canceled(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks.cache_manager,
        "get_task_by_id",
        lambda task_id: {
            "task_id": task_id,
            "owner_user_id": "user-1",
            "status": tasks.TaskStatus.PROCESSING,
        },
    )
    monkeypatch.setattr(tasks, "_require_task_owner", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, "cancel_cloud_quote", lambda task_id: True)
    updates = []
    monkeypatch.setattr(
        tasks.cache_manager,
        "update_task_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    response = asyncio.run(tasks.cancel_task("task-1", {"user_id": "user-1"}))

    assert response.code == 200
    assert response.message == "任务已取消"
    assert updates == [
        (
            ("task-1", tasks.TaskStatus.CANCELED),
            {"error_message": "用户已取消任务"},
        )
    ]


def test_cancel_task_rejects_completed_task(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks.cache_manager,
        "get_task_by_id",
        lambda task_id: {
            "task_id": task_id,
            "owner_user_id": "user-1",
            "status": tasks.TaskStatus.SUCCESS,
        },
    )
    monkeypatch.setattr(tasks, "_require_task_owner", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(tasks.cancel_task("task-1", {"user_id": "user-1"}))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "task_not_cancellable"
