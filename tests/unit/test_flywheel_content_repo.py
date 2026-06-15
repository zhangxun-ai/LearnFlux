"""Unit tests for ContentRepository: filter / sort / paginate (sqlite)."""
from datetime import datetime, timedelta

import pytest

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import (
    Blogger, Content, MediaType, AnalysisStatus, ContentSource,
)
from src.video_transcript_api.flywheel.repositories import (
    SqliteBloggerRepository, SqliteContentRepository, ContentQuery,
)


@pytest.fixture
def env(tmp_path):
    db = FlywheelDB(db_path=str(tmp_path / "f.db"))
    brepo = SqliteBloggerRepository(db)
    crepo = SqliteContentRepository(db)
    b = brepo.upsert(Blogger(id=None, platform="xiaohongshu", platform_user_id="u1",
                             handle="@k", is_subscribed=True))
    yield brepo, crepo, b
    db.close()


def _c(b, item, mt=MediaType.VIDEO, likes=100, days_ago=0,
       status=AnalysisStatus.PENDING, source=ContentSource.FEED):
    return Content(
        id=None, blogger_id=b.id, platform="xiaohongshu", platform_item_id=item,
        media_type=mt, title=item, original_url=f"https://x/{item}",
        published_at=datetime(2026, 6, 10) - timedelta(days=days_ago),
        like_count=likes, source=source, analysis_status=status,
    )


@pytest.mark.unit
def test_upsert_dedups_by_platform_item(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "n1"))
    crepo.upsert(_c(b, "n1", likes=999))
    page = crepo.list(ContentQuery())
    assert page.total == 1
    assert page.items[0].like_count == 999


@pytest.mark.unit
def test_upsert_refreshes_original_url_for_retry(env):
    _, crepo, b = env
    existing = crepo.upsert(_c(b, "n1"))
    refreshed = crepo.upsert(Content(
        id=None,
        blogger_id=b.id,
        platform="xiaohongshu",
        platform_item_id="n1",
        media_type=MediaType.VIDEO,
        title="n1",
        original_url="https://www.xiaohongshu.com/discovery/item/n1",
    ))

    assert refreshed.id == existing.id
    assert crepo.get(existing.id).original_url == "https://www.xiaohongshu.com/discovery/item/n1"


@pytest.mark.unit
def test_filter_by_media_type(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "v1", mt=MediaType.VIDEO))
    crepo.upsert(_c(b, "a1", mt=MediaType.ARTICLE))
    page = crepo.list(ContentQuery(media_type=MediaType.ARTICLE))
    assert [c.platform_item_id for c in page.items] == ["a1"]


@pytest.mark.unit
def test_filter_by_status_multi(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "n1", status=AnalysisStatus.PENDING))
    crepo.upsert(_c(b, "n2", status=AnalysisStatus.SUCCESS))
    crepo.upsert(_c(b, "n3", status=AnalysisStatus.FAILED))
    page = crepo.list(ContentQuery(statuses=(AnalysisStatus.SUCCESS, AnalysisStatus.FAILED)))
    assert {c.platform_item_id for c in page.items} == {"n2", "n3"}


@pytest.mark.unit
def test_filter_by_date_range(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "old", days_ago=40))
    crepo.upsert(_c(b, "new", days_ago=1))
    page = crepo.list(ContentQuery(date_from=datetime(2026, 6, 1)))
    assert [c.platform_item_id for c in page.items] == ["new"]


@pytest.mark.unit
def test_filter_by_subscribed(env):
    brepo, crepo, b = env
    other = brepo.upsert(Blogger(id=None, platform="xiaohongshu", platform_user_id="u2",
                                 handle="@adhoc", is_subscribed=False))
    crepo.upsert(_c(b, "sub1"))
    crepo.upsert(Content(id=None, blogger_id=other.id, platform="xiaohongshu",
                         platform_item_id="ad1", media_type=MediaType.VIDEO, title="ad1",
                         original_url="https://x/ad1", source=ContentSource.ADHOC))
    page = crepo.list(ContentQuery(subscribed=True))
    assert [c.platform_item_id for c in page.items] == ["sub1"]


@pytest.mark.unit
def test_sort_by_likes_desc(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "low", likes=10))
    crepo.upsert(_c(b, "high", likes=9000))
    page = crepo.list(ContentQuery(sort="like_count"))
    assert [c.platform_item_id for c in page.items] == ["high", "low"]


@pytest.mark.unit
def test_pagination(env):
    _, crepo, b = env
    for i in range(5):
        crepo.upsert(_c(b, f"n{i}", days_ago=i))
    page = crepo.list(ContentQuery(page=1, page_size=2))
    assert len(page.items) == 2 and page.total == 5 and page.pages == 3


@pytest.mark.unit
def test_set_analysis_status(env):
    _, crepo, b = env
    c = crepo.upsert(_c(b, "n1"))
    crepo.set_analysis_status(c.id, AnalysisStatus.SUCCESS, analysis_id=7)
    got = crepo.get(c.id)
    assert got.analysis_status is AnalysisStatus.SUCCESS and got.latest_analysis_id == 7
