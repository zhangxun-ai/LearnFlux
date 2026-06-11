"""Unit tests for flywheel domain models (immutable, storage-agnostic)."""
import pytest

from src.video_transcript_api.flywheel.models import (
    MediaType, AnalysisStatus, ContentSource, Blogger, Content,
)


@pytest.mark.unit
def test_enums_have_expected_string_values():
    assert MediaType.VIDEO.value == "video"
    assert MediaType.ARTICLE.value == "article"
    assert AnalysisStatus.PENDING.value == "pending"
    assert AnalysisStatus.PROCESSING.value == "processing"
    assert AnalysisStatus.SUCCESS.value == "success"
    assert AnalysisStatus.FAILED.value == "failed"
    assert ContentSource.FEED.value == "feed"
    assert ContentSource.ADHOC.value == "adhoc"


@pytest.mark.unit
def test_blogger_is_immutable():
    b = Blogger(id=1, platform="xiaohongshu", platform_user_id="u1", handle="@k")
    with pytest.raises(Exception):
        b.handle = "changed"  # frozen dataclass


@pytest.mark.unit
def test_content_defaults_are_sane():
    c = Content(
        id=1, blogger_id=1, platform="xiaohongshu", platform_item_id="n1",
        media_type=MediaType.VIDEO, title="t", original_url="https://x/n1",
    )
    assert c.analysis_status is AnalysisStatus.PENDING
    assert c.source is ContentSource.FEED
    assert c.like_count == 0
