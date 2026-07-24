import sqlite3


def _create_pending(repo, **overrides):
    values = {
        "owner_type": "study",
        "owner_id": "view-1",
        "document_type": "overview",
        "request_key": "request-1",
        "source_hash": "source-hash-1",
        "style": "study-notes",
    }
    values.update(overrides)
    return repo.create_or_get_pending(**values)


def test_create_or_get_pending_is_idempotent(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    repo = VisualLearningRepository(str(tmp_path / "visual.db"))

    first = _create_pending(repo)
    second = _create_pending(repo)

    assert first["id"] == second["id"]
    assert second["status"] == "pending"
    assert repo.list_documents("study", "view-1") == [second]


def test_force_generation_creates_new_version(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    repo = VisualLearningRepository(str(tmp_path / "visual.db"))

    first = _create_pending(repo)
    second = _create_pending(repo, force=True)

    assert first["id"] != second["id"]
    assert first["request_key"] != second["request_key"]
    assert len(repo.list_documents("study", "view-1", "overview")) == 2


def test_successful_document_remains_visible_after_new_failure(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    repo = VisualLearningRepository(str(tmp_path / "visual.db"))
    successful = _create_pending(repo)
    success_token = repo.claim_generation(successful["id"])
    assert success_token
    assert repo.save_success(
        successful["id"],
        success_token,
        {"version": 1, "title": "上一版"},
        "test-model",
    )

    failed = _create_pending(repo, force=True)
    failure_token = repo.claim_generation(failed["id"])
    assert failure_token
    assert repo.save_failure(failed["id"], failure_token, "temporary failure")

    latest_attempt = repo.get_latest("study", "view-1", "overview")
    latest_success = repo.get_latest(
        "study", "view-1", "overview", successful_only=True
    )

    assert latest_attempt["id"] == failed["id"]
    assert latest_attempt["status"] == "failed"
    assert latest_success["id"] == successful["id"]
    assert latest_success["document_json"]["title"] == "上一版"


def test_generation_token_prevents_late_worker_overwrite(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    db_path = tmp_path / "visual.db"
    repo = VisualLearningRepository(str(db_path))
    document = _create_pending(repo)
    old_token = repo.claim_generation(document["id"])
    assert old_token

    repo.close()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE visual_documents SET updated_at = '2000-01-01 00:00:00' WHERE id = ?",
            (document["id"],),
        )

    repo = VisualLearningRepository(str(db_path))
    assert repo.recover_stale_generations(max_age_minutes=20) == 1
    new_token = repo.claim_generation(document["id"])
    assert new_token and new_token != old_token

    assert repo.save_success(
        document["id"], old_token, {"version": 1, "title": "过期结果"}, "old-model"
    ) is False
    assert repo.save_success(
        document["id"], new_token, {"version": 1, "title": "最新结果"}, "new-model"
    ) is True
    assert repo.get_document(document["id"])["document_json"]["title"] == "最新结果"


def test_stale_generation_can_be_reclaimed(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    db_path = tmp_path / "visual.db"
    repo = VisualLearningRepository(str(db_path))
    document = _create_pending(repo)
    assert repo.claim_generation(document["id"])
    repo.close()

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE visual_documents SET updated_at = '2000-01-01 00:00:00' WHERE id = ?",
            (document["id"],),
        )

    repo = VisualLearningRepository(str(db_path))
    assert repo.recover_stale_generations(max_age_minutes=20) == 1
    recovered = repo.get_document(document["id"])
    assert recovered["status"] == "failed"
    assert recovered["error_message"] == "generation timed out"
    assert repo.claim_generation(document["id"])


def test_list_recent_diagrams_orders_by_updated_at(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    repo = VisualLearningRepository(str(tmp_path / "visual.db"))
    first = _create_pending(
        repo,
        document_type="diagram",
        request_key="diagram-1",
    )
    first_token = repo.claim_generation(first["id"])
    repo.save_success(first["id"], first_token, {"title": "第一张"}, "test-model")

    second = _create_pending(
        repo,
        document_type="diagram",
        request_key="diagram-2",
    )
    second_token = repo.claim_generation(second["id"])
    repo.save_success(second["id"], second_token, {"title": "第二张"}, "test-model")

    recent = repo.list_recent(document_type="diagram", limit=1)

    assert [item["id"] for item in recent] == [second["id"]]


def test_repository_migrates_and_deserializes_progress_json(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    db_path = tmp_path / "visual.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE visual_documents (
                id TEXT PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
                document_type TEXT NOT NULL, status TEXT NOT NULL,
                request_key TEXT NOT NULL UNIQUE, source_hash TEXT NOT NULL,
                style TEXT NOT NULL, document_json TEXT, model TEXT,
                error_message TEXT, generation_token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )

    repo = VisualLearningRepository(str(db_path))
    columns = {
        row[1]
        for row in sqlite3.connect(db_path).execute("PRAGMA table_info(visual_documents)")
    }
    assert "progress_json" in columns

    record = _create_pending(repo)
    token = repo.claim_generation(record["id"])
    assert repo.update_progress(
        record["id"], token, {"stage": "analyzing_outline", "percent": 50}
    )
    assert repo.get_document(record["id"])["progress_json"]["stage"] == "analyzing_outline"


def test_success_and_failure_persist_terminal_progress_atomically(tmp_path):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository

    repo = VisualLearningRepository(str(tmp_path / "visual.db"))
    success = _create_pending(repo)
    success_token = repo.claim_generation(success["id"])
    repo.update_progress(success["id"], success_token, {"stage": "validating", "percent": 95})
    assert repo.save_success(success["id"], success_token, {"title": "完成"}, "model")
    completed = repo.get_document(success["id"])
    assert completed["status"] == "success"
    assert completed["progress_json"]["stage"] == "completed"
    assert completed["progress_json"]["percent"] == 100

    failed = _create_pending(repo, request_key="request-failed", force=True)
    failure_token = repo.claim_generation(failed["id"])
    repo.update_progress(failed["id"], failure_token, {"stage": "generating_visual", "percent": 75})
    assert repo.save_failure(failed["id"], failure_token, "provider failed")
    failure = repo.get_document(failed["id"])
    assert failure["status"] == "failed"
    assert failure["progress_json"]["stage"] == "failed"
    assert failure["progress_json"]["previous_stage"] == "generating_visual"
