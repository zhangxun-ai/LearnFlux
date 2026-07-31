import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from video_transcript_api.api.routes.tasks import _require_task_owner
from video_transcript_api.api.services.transcription import TranscribeRequest


@pytest.mark.parametrize("strategy", ["local", "cloud"])
def test_public_transcribe_request_accepts_explicit_strategy(strategy):
    request = TranscribeRequest(url="https://example.com/video", transcription_strategy=strategy)

    assert request.transcription_strategy == strategy


@pytest.mark.parametrize("strategy", ["auto", "unknown", ""])
def test_public_transcribe_request_rejects_unsupported_strategy(strategy):
    with pytest.raises(ValidationError):
        TranscribeRequest(url="https://example.com/video", transcription_strategy=strategy)


def test_legacy_public_request_defaults_to_local_free():
    request = TranscribeRequest(url="https://example.com/video")

    assert request.transcription_strategy == "local"
    assert request.analysis_intent == "deep_learning"
    assert request.source_type is None


@pytest.mark.parametrize(
    "source_type",
    [
        "wechat_mp_article",
        "wechat_channels_video",
        "video",
        "social_post",
        "mixed_media",
        "unknown",
    ],
)
def test_every_public_source_keeps_deep_learning_intent(source_type):
    request = TranscribeRequest(
        url="https://example.com/content",
        source_type=source_type,
        include_comments=True,
    )

    assert request.analysis_intent == "deep_learning"


def test_public_transcribe_request_rejects_post_insight_intent():
    with pytest.raises(ValidationError):
        TranscribeRequest(
            url="https://mp.weixin.qq.com/s/example",
            analysis_intent="post_insight",
        )


def test_paid_quote_action_is_limited_to_task_owner():
    task = {"owner_user_id": "user-a"}

    _require_task_owner(task, {"user_id": "user-a"}, paid_action=True)
    with pytest.raises(HTTPException) as denied:
        _require_task_owner(task, {"user_id": "user-b"}, paid_action=True)

    assert denied.value.status_code == 403


def test_legacy_unowned_task_cannot_start_paid_action():
    with pytest.raises(HTTPException) as denied:
        _require_task_owner({}, {"user_id": "legacy_user"}, paid_action=True)

    assert denied.value.status_code == 403
