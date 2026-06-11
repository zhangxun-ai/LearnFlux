"""Unit tests for the ingest service: fetch -> persist (fake fetcher + real repos)."""
import pytest

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import (
    Blogger, MediaType, AnalysisStatus, ContentSource,
)
from src.video_transcript_api.flywheel.fetchers import FetchResult, FetchedItem
from src.video_transcript_api.flywheel.repositories import (
    SqliteBloggerRepository, SqliteContentRepository, ContentQuery,
)
from src.video_transcript_api.flywheel.ingest import ingest_blogger


@pytest.fixture
def env(tmp_path):
    db = FlywheelDB(db_path=str(tmp_path / "f.db"))
    yield SqliteBloggerRepository(db), SqliteContentRepository(db)
    db.close()


def _fake_result():
    blogger = Blogger(id=None, platform="xiaohongshu", platform_user_id="u1",
                      handle="@k", media_types=(MediaType.VIDEO,))
    items = (
        FetchedItem(platform_item_id="n1", media_type=MediaType.VIDEO, title="t1",
                    original_url="https://x/n1", cover_url=None, published_at=None, like_count=10),
        FetchedItem(platform_item_id="n2", media_type=MediaType.ARTICLE, title="t2",
                    original_url="https://x/n2", cover_url=None, published_at=None, like_count=20),
    )
    return FetchResult(blogger=blogger, items=items)


def _fake_fetch(url, *, max_items=20):
    return _fake_result()


@pytest.mark.unit
def test_ingest_subscribe_persists_blogger_and_content(env):
    brepo, crepo = env
    res = ingest_blogger("https://www.xiaohongshu.com/user/profile/u1", subscribe=True,
                         blogger_repo=brepo, content_repo=crepo, fetch=_fake_fetch)
    assert res.ingested == 2
    assert res.blogger.id is not None
    assert res.blogger.is_subscribed is True

    page = crepo.list(ContentQuery())
    assert page.total == 2
    c = page.items[0]
    assert c.blogger_id == res.blogger.id
    assert c.platform == "xiaohongshu"
    assert c.source is ContentSource.FEED
    assert c.analysis_status is AnalysisStatus.PENDING  # default: not auto-analyzed


@pytest.mark.unit
def test_ingest_adhoc_is_not_subscribed_and_source_adhoc(env):
    brepo, crepo = env
    res = ingest_blogger("https://www.xiaohongshu.com/user/profile/u1", subscribe=False,
                         blogger_repo=brepo, content_repo=crepo, fetch=_fake_fetch)
    assert res.blogger.is_subscribed is False
    assert crepo.list(ContentQuery()).items[0].source is ContentSource.ADHOC


@pytest.mark.unit
def test_ingest_is_idempotent_on_repeat(env):
    brepo, crepo = env
    ingest_blogger("https://www.xiaohongshu.com/user/profile/u1", subscribe=True,
                   blogger_repo=brepo, content_repo=crepo, fetch=_fake_fetch)
    ingest_blogger("https://www.xiaohongshu.com/user/profile/u1", subscribe=True,
                   blogger_repo=brepo, content_repo=crepo, fetch=_fake_fetch)
    assert crepo.list(ContentQuery()).total == 2          # not duplicated
    assert len(brepo.list_subscribed()) == 1
