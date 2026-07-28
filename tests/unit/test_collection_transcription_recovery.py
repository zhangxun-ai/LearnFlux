from decimal import Decimal

from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.collections.repository import LearningCollectionRepository
from video_transcript_api.collections.service import LearningCollectionService
from video_transcript_api.collections.transcription import (
    CollectionTranscriptionService,
)
from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteConfirmation,
    CloudQuoteRepository,
    NewCloudQuote,
)


def test_continue_recreates_legacy_budget_exceeded_cloud_quote_failure(tmp_path):
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    collection = repository.create_collection(
        "Series",
        "Teacher",
        "video_course",
        owner_user_id="owner",
        transcription_strategy="cloud",
        transcription_concurrency=5,
    )
    failed = cache.create_task(
        url="local://collection-source/media-long/lesson.mp4",
        platform="generic",
        media_id="media-long",
        owner_user_id="owner",
        source_file_path="/stable/lesson.mp4",
    )
    cache.update_task_status(
        failed["task_id"],
        "failed",
        error_message="本地转录失败: budget_exceeded",
    )
    source = repository.add_source(
        collection["id"],
        failed["task_id"],
        failed["view_token"],
        "lesson.mp4",
        "video",
        content_sha256="sha-lesson",
    )

    result = CollectionTranscriptionService(
        repository, cache
    ).continue_collection(
        collection["id"],
        owner_user_id="owner",
        strategy="cloud",
        requested_concurrency=5,
    )

    assert len(result.launches) == 1
    assert result.launches[0].source_id == source["id"]
    assert result.launches[0].strategy == "cloud"


def test_batch_confirmation_atomically_moves_tasks_out_of_awaiting_state(tmp_path):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(cache.db_path)
    quote_repository = CloudQuoteRepository(cache.db_path)
    collection = repository.create_collection(
        "Series",
        "Teacher",
        "video_course",
        owner_user_id="owner",
        transcription_strategy="cloud",
        transcription_concurrency=5,
    )
    task = cache.create_task(
        url="local://collection-source/media-1/lesson.mp4",
        platform="generic",
        media_id="media-1",
        owner_user_id="owner",
        source_file_path="/stable/lesson.mp4",
    )
    cache.update_task_status(task["task_id"], "awaiting_cloud_confirmation")
    repository.add_source(
        collection["id"],
        task["task_id"],
        task["view_token"],
        "lesson.mp4",
        "video",
        content_sha256="sha-lesson",
    )
    collection = repository.get_collection(collection["id"])
    quote_repository.create(
        NewCloudQuote(
            task_id=task["task_id"],
            media_ref="/stable/input.m4a",
            media_sha256="a" * 64,
            duration_seconds=Decimal("60"),
            billable_seconds=60,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.0132"),
        ),
        token="quote-token",
    )
    service = CollectionTranscriptionService(
        repository,
        cache,
        quote_repository=quote_repository,
    )

    service.confirm_collection_cloud_quotes(
        collection["id"],
        owner_user_id="owner",
        transcription_revision=collection["transcription_revision"],
        confirmations=(
            CloudQuoteConfirmation(
                task_id=task["task_id"],
                token="quote-token",
                accepted_max_cost=Decimal("0.0132"),
            ),
        ),
        accepted_total=Decimal("0.0132"),
    )

    assert cache.get_task_by_id(task["task_id"])["status"] == "queued"
    assert quote_repository.get(task["task_id"]).status == "confirmed_queued"


def test_stop_collection_cancels_an_unconfirmed_cloud_quote(tmp_path):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(cache.db_path)
    quote_repository = CloudQuoteRepository(cache.db_path)
    collection = repository.create_collection(
        "Series",
        "Teacher",
        "video_course",
        owner_user_id="owner",
        transcription_strategy="cloud",
        transcription_concurrency=5,
    )
    task = cache.create_task(
        url="local://collection-source/media-1/lesson.mp4",
        platform="generic",
        media_id="media-1",
        owner_user_id="owner",
        source_file_path="/stable/lesson.mp4",
    )
    cache.update_task_status(task["task_id"], "awaiting_cloud_confirmation")
    repository.add_source(
        collection["id"],
        task["task_id"],
        task["view_token"],
        "lesson.mp4",
        "video",
        content_sha256="sha-lesson",
    )
    quote_repository.create(
        NewCloudQuote(
            task_id=task["task_id"],
            media_ref="/stable/input.m4a",
            media_sha256="a" * 64,
            duration_seconds=Decimal("60"),
            billable_seconds=60,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.0132"),
        ),
        token="quote-token",
    )
    service = CollectionTranscriptionService(
        repository,
        cache,
        quote_repository=quote_repository,
    )

    result = service.stop_collection(collection["id"], owner_user_id="owner")

    assert result.stopped_count == 1
    assert cache.get_task_by_id(task["task_id"])["status"] == "canceled"
    assert quote_repository.get(task["task_id"]).status == "canceled"


def test_no_transcript_finishes_a_collection_without_marking_it_failed(tmp_path):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(cache.db_path)
    collection = repository.create_collection(
        "Silent clips",
        "Teacher",
        "video_course",
        owner_user_id="owner",
    )
    task = cache.create_task(
        url="local://collection-source/media-silent/silent.mp4",
        platform="generic",
        media_id="media-silent",
        owner_user_id="owner",
    )
    cache.update_task_status(
        task["task_id"], "no_transcript", error_message="未检测到可转录语音"
    )
    repository.add_source(
        collection["id"],
        task["task_id"],
        task["view_token"],
        "silent.mp4",
        "video",
        content_sha256="sha-silent",
    )

    detail = LearningCollectionService(repository, cache).get_collection_detail(
        collection["id"]
    )

    assert detail["workflow_status"] == "completed_without_transcript"
    assert detail["metrics"]["completed_count"] == 1
