import time

import pytest


def test_media_grant_round_trips_without_serializing_api_key():
    from video_transcript_api.study.media_access import StudyMediaAccess

    access = StudyMediaAccess(secret="server-secret", clock=lambda: 1000)

    token = access.issue_single(user_id="user-a", view_token="view-1", ttl_seconds=60)
    payload = access.verify_single(token, view_token="view-1")

    assert payload["user_id"] == "user-a"
    assert payload["exp"] == 1060
    assert "sk-user-a" not in token


def test_media_grant_rejects_tampering_expiry_and_cross_content_use():
    from video_transcript_api.study.media_access import StudyMediaAccess

    now = [1000]
    access = StudyMediaAccess(secret="server-secret", clock=lambda: now[0])
    token = access.issue_single(user_id="user-a", view_token="view-1", ttl_seconds=10)

    with pytest.raises(ValueError):
        access.verify_single(token + "x", view_token="view-1")
    with pytest.raises(ValueError):
        access.verify_single(token, view_token="view-2")
    now[0] = 1011
    with pytest.raises(ValueError):
        access.verify_single(token, view_token="view-1")


def test_source_resolver_accepts_only_existing_files_under_allowed_roots(tmp_path):
    from video_transcript_api.study.source_files import find_study_source_file

    source_root = tmp_path / "sources"
    retained = source_root / "retained" / "lesson.mp4"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"video")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")

    assert find_study_source_file(
        source_root=source_root,
        media_id="missing",
        title="lesson.mp4",
        url="local://other/lesson.mp4",
        source_file_path=str(retained),
    ) == retained.resolve()
    assert find_study_source_file(
        source_root=source_root,
        media_id="missing",
        title="outside.mp4",
        url="local://other/outside.mp4",
        source_file_path=str(outside),
    ) is None
