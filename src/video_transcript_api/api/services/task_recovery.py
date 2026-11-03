"""Recover explicitly persisted local URL work without replaying paid jobs."""

from ...utils.task_status import TaskStatus


def prepare_task_recovery(cache_manager, user_manager, *, protected_task_ids=()):
    """Revalidate task ownership and recover only bounded, safe local requests."""
    protected = set(protected_task_ids)
    tasks = []
    for stored in cache_manager.get_recoverable_task_requests():
        task = dict(stored)
        task_id = task["id"]
        if task_id in protected:
            continue
        owner = task.pop("owner_user_id", None)
        user = user_manager.get_user_by_id(owner) if owner else None
        if not user or not user.get("enabled", True):
            continue
        task["notification_webhooks"] = {}
        if task.pop("restore_notifications", False):
            if user.get("feishu_webhook"):
                task["notification_webhooks"]["feishu"] = user["feishu_webhook"]
        task.pop("wechat_webhook", None)
        if task.get("notification_channel") not in (None, "feishu"):
            task["notification_channel"] = None
        task["recovered"] = True
        cache_manager.record_task_recovery(task_id)
        cache_manager.update_task_status(task_id, TaskStatus.QUEUED, force=True)
        cache_manager.update_task_progress(
            task_id, stage="queued", stage_label="已恢复，等待继续处理",
            basis="startup_recovery", confidence="high",
        )
        tasks.append(task)
    return tasks


async def enqueue_recovered_tasks(tasks, task_queue):
    """Feed recovery through normal admission capacity instead of bypassing it."""
    for task in tasks:
        await task_queue.put(task)
