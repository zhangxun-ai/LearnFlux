import threading
from datetime import datetime, timezone

import pytest


def _create_collection(repository):
    return repository.create_collection(
        title="Restart-safe summary",
        creator_name="Codex",
        collection_type="video_course",
        owner_user_id="u1",
    )


def _module(index, source_number):
    return {
        "index": index,
        "title": f"Module {index + 1}",
        "role": "Test role",
        "rationale": "Test rationale",
        "source_numbers": [source_number],
    }


def test_summary_job_recovery_preserves_completed_modules(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=600)

    claimed = repository.claim_next_summary_job(
        worker_id="worker-1",
        lease_seconds=60,
    )
    assert claimed["job_id"] == job["job_id"]
    assert claimed["status"] == "running"

    repository.save_summary_plan(
        job["job_id"],
        [_module(0, 1), _module(1, 2)],
    )
    repository.mark_summary_module_running(job["job_id"], 0)
    repository.complete_summary_module(job["job_id"], 0, "Module one summary")
    repository.mark_summary_module_running(job["job_id"], 1)

    recovered = repository.recover_interrupted_summary_jobs()

    assert recovered["requeued_jobs"] == 1
    updated_job = repository.get_summary_job(collection["id"])
    assert updated_job["status"] == "queued"
    assert updated_job["phase"] == "modules"
    assert updated_job["completed_modules"] == 1
    modules = repository.list_summary_modules(job["job_id"])
    assert [module["status"] for module in modules] == ["success", "queued"]
    assert modules[0]["markdown"] == "Module one summary"


def test_completed_module_renews_summary_progress_deadline(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=120)
    repository.claim_next_summary_job(worker_id="worker-1", lease_seconds=60)
    repository.save_summary_plan(job["job_id"], [_module(0, 1)])
    repository.mark_summary_module_running(job["job_id"], 0)
    with repository._get_cursor(write=True) as cursor:
        cursor.execute(
            """
            UPDATE learning_collection_summary_jobs
            SET deadline_at = '2000-01-01T00:00:00+00:00'
            WHERE job_id = ?
            """,
            (job["job_id"],),
        )

    repository.complete_summary_module(job["job_id"], 0, "Module one summary")

    updated = repository.get_summary_job_by_id(job["job_id"])
    deadline = datetime.fromisoformat(updated["deadline_at"])
    assert deadline > datetime.now(timezone.utc)


def test_requeue_does_not_mutate_an_active_summary_job(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=120)
    repository.claim_next_summary_job(worker_id="worker-1", lease_seconds=60)
    repository.save_summary_plan(job["job_id"], [_module(0, 1)])
    repository.mark_summary_module_running(job["job_id"], 0)

    requeued = repository.requeue_summary_job(
        job["job_id"],
        deadline_seconds=120,
    )

    assert requeued is False
    assert repository.get_summary_job_by_id(job["job_id"])["status"] == "running"
    assert repository.list_summary_modules(job["job_id"])[0]["status"] == "running"


def test_legacy_processing_without_job_becomes_retryable_failure(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    repository.mark_summary_processing(collection["id"])

    recovered = repository.recover_interrupted_summary_jobs()

    assert recovered["legacy_failed"] == 1
    updated = repository.get_collection_detail(collection["id"])
    assert updated["summary_status"] == "failed"
    job = repository.get_summary_job(collection["id"])
    assert job["status"] == "failed"
    assert "restart" in job["error_message"].lower()


def test_layered_summary_resumes_modules_and_runs_pending_work_concurrently(
    tmp_path,
    monkeypatch,
):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=600)
    repository.claim_next_summary_job(worker_id="worker-1", lease_seconds=60)
    modules = [_module(0, 1), _module(1, 2), _module(2, 3)]
    repository.save_summary_plan(job["job_id"], modules)
    repository.mark_summary_module_running(job["job_id"], 0)
    repository.complete_summary_module(job["job_id"], 0, "Checkpointed module")

    service = LearningCollectionService(
        repository=repository,
        cache_manager=object(),
        llm_config={"collection_summary_module_concurrency": 2},
    )
    sources = [
        {"title": f"Source {index}", "transcript": f"Transcript {index}", "position": index}
        for index in range(1, 4)
    ]
    barrier = threading.Barrier(2)
    called_prompts = []

    def fake_call(model, prompt, reasoning_effort, task_type, system_prompt):
        called_prompts.append((task_type, prompt))
        if task_type == "collection_module_summary":
            barrier.wait(timeout=2)
            return f"Summary for {prompt.split('模块名称：', 1)[1].splitlines()[0]}"
        if task_type == "collection_summary":
            return "# Final summary"
        raise AssertionError(f"Unexpected task type: {task_type}")

    monkeypatch.setattr(service, "_call_collection_llm_text", fake_call)

    markdown = service._generate_layered_summary_with_llm(
        collection,
        sources,
        "test-model",
        None,
        "system",
        job_id=job["job_id"],
    )

    assert markdown == "# Final summary"
    module_calls = [call for call in called_prompts if call[0] == "collection_module_summary"]
    assert len(module_calls) == 2
    assert all("Module 1" not in prompt for _, prompt in module_calls)
    updated_modules = repository.list_summary_modules(job["job_id"])
    assert [module["status"] for module in updated_modules] == [
        "success",
        "success",
        "success",
    ]


def test_empty_module_summary_is_rejected_and_persisted(tmp_path, monkeypatch):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=600)
    repository.claim_next_summary_job(worker_id="worker-1", lease_seconds=60)
    repository.save_summary_plan(job["job_id"], [_module(0, 1)])
    service = LearningCollectionService(
        repository=repository,
        cache_manager=object(),
        llm_config={"collection_summary_module_concurrency": 1},
    )
    monkeypatch.setattr(service, "_call_collection_llm_text", lambda *args: "")

    with pytest.raises(ValueError, match="empty module summary"):
        service._generate_layered_summary_with_llm(
            collection,
            [{"title": "Source 1", "transcript": "Transcript", "position": 1}],
            "test-model",
            None,
            "system",
            job_id=job["job_id"],
        )

    module = repository.list_summary_modules(job["job_id"])[0]
    assert module["status"] == "failed"
    assert "empty module summary" in module["error_message"]


def test_summary_worker_claims_and_completes_queued_job(tmp_path):
    from video_transcript_api.cache.cache_manager import CacheManager
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService
    from video_transcript_api.collections.summary_worker import CollectionSummaryWorker

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = cache_manager.create_task(
        url="local://summary/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="summary-worker-source",
    )
    cache_manager.save_cache(
        platform="generic",
        url="local://summary/1.mp4",
        media_id="summary-worker-source",
        use_speaker_recognition=False,
        transcript_data="A ready transcript",
        transcript_type="capswriter",
        title="1.mp4",
        author="Local",
        description="",
    )
    cache_manager.update_task_status(
        task["task_id"],
        "success",
        platform="generic",
        media_id="summary-worker-source",
    )
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    service = LearningCollectionService(
        repository=repository,
        cache_manager=cache_manager,
        summary_generator=lambda collection, sources: "# Durable summary",
    )
    collection = _create_collection(repository)
    repository.add_source(
        collection_id=collection["id"],
        task_id=task["task_id"],
        view_token=task["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )
    queued = service.begin_summary_generation(collection["id"])
    duplicate = service.begin_summary_generation(collection["id"])
    worker = CollectionSummaryWorker(
        service,
        heartbeat_interval_seconds=0.05,
        poll_interval_seconds=0.05,
    )

    assert queued["summary_job"]["status"] == "queued"
    assert duplicate["summary_job"]["job_id"] == queued["summary_job"]["job_id"]
    assert duplicate["summary_created"] is False
    assert worker.run_once() is True

    completed = service.get_collection_detail(collection["id"])
    assert completed["summary_status"] == "success"
    assert completed["summary_markdown"] == "# Durable summary"
    assert completed["summary_job"]["status"] == "success"


def test_source_change_invalidates_queued_summary_job(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    job = repository.enqueue_summary_job(collection["id"], deadline_seconds=600)

    repository.add_source(
        collection_id=collection["id"],
        task_id="new-task",
        view_token="new-view",
        title="new.mp4",
        source_type="video",
        position=1,
    )

    assert repository.get_summary_job_by_id(job["job_id"]) is None
    updated = repository.get_collection_detail(collection["id"])
    assert updated["summary_status"] == "not_started"


def test_expired_running_job_is_requeued_with_checkpoints_when_user_retries(
    tmp_path,
    monkeypatch,
):
    from video_transcript_api.cache.cache_manager import CacheManager
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = cache_manager.create_task(
        url="local://summary/retry.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="expired-summary-source",
    )
    cache_manager.save_cache(
        platform="generic",
        url="local://summary/retry.mp4",
        media_id="expired-summary-source",
        use_speaker_recognition=False,
        transcript_data="Retryable transcript",
        transcript_type="capswriter",
        title="retry.mp4",
        author="Local",
        description="",
    )
    cache_manager.update_task_status(
        task["task_id"],
        "success",
        platform="generic",
        media_id="expired-summary-source",
    )
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    collection = _create_collection(repository)
    repository.add_source(
        collection_id=collection["id"],
        task_id=task["task_id"],
        view_token=task["view_token"],
        title="retry.mp4",
        source_type="video",
        position=1,
    )
    first_job = repository.enqueue_summary_job(collection["id"], deadline_seconds=600)
    repository.claim_next_summary_job(worker_id="dead-worker", lease_seconds=60)
    repository.save_summary_plan(first_job["job_id"], [_module(0, 1)])
    repository.mark_summary_module_running(first_job["job_id"], 0)
    repository.complete_summary_module(
        first_job["job_id"],
        0,
        "Checkpointed module",
    )
    with repository._get_cursor(write=True) as cursor:
        cursor.execute(
            """
            UPDATE learning_collection_summary_jobs
            SET lease_until = '2000-01-01T00:00:00+00:00'
            WHERE job_id = ?
            """,
            (first_job["job_id"],),
        )
    service = LearningCollectionService(
        repository=repository,
        cache_manager=cache_manager,
    )
    requeue_summary_job = repository.requeue_summary_job

    def simulate_competing_retry(job_id, *, deadline_seconds):
        assert requeue_summary_job(
            job_id,
            deadline_seconds=deadline_seconds,
        ) is True
        return False

    monkeypatch.setattr(
        repository,
        "requeue_summary_job",
        simulate_competing_retry,
    )

    retried = service.begin_summary_generation(collection["id"])

    assert retried["summary_created"] is False
    assert retried["summary_job"]["status"] == "queued"
    assert retried["summary_job"]["job_id"] == first_job["job_id"]
    modules = repository.list_summary_modules(first_job["job_id"])
    assert [module["status"] for module in modules] == ["success"]
    assert modules[0]["markdown"] == "Checkpointed module"
