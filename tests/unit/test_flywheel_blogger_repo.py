"""Unit tests for FlywheelDB schema + BloggerRepository (sqlite)."""
import pytest

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import Blogger, MediaType
from src.video_transcript_api.flywheel.repositories import SqliteBloggerRepository


@pytest.fixture
def db(tmp_path):
    d = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    yield d
    d.close()


@pytest.fixture
def repo(db):
    return SqliteBloggerRepository(db)


def _sample(uid="u1", subscribed=False):
    return Blogger(id=None, platform="xiaohongshu", platform_user_id=uid,
                   handle="@阿K", media_types=(MediaType.VIDEO,), is_subscribed=subscribed)


# --- schema ---

@pytest.mark.unit
def test_schema_creates_blogger_and_content_tables(db):
    with db.cursor() as cur:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
    assert {"blogger", "content"}.issubset(tables)


@pytest.mark.unit
def test_init_is_idempotent(tmp_path):
    path = str(tmp_path / "flywheel.db")
    FlywheelDB(db_path=path).close()
    FlywheelDB(db_path=path).close()  # second init must not raise


# --- blogger repo ---

@pytest.mark.unit
def test_upsert_inserts_then_returns_id(repo):
    saved = repo.upsert(_sample())
    assert saved.id is not None
    assert saved.handle == "@阿K"
    assert saved.media_types == (MediaType.VIDEO,)


@pytest.mark.unit
def test_upsert_is_idempotent_by_platform_user(repo):
    a = repo.upsert(_sample(uid="u1"))
    b = repo.upsert(_sample(uid="u1"))
    assert a.id == b.id  # same (platform, platform_user_id) -> update, not duplicate


@pytest.mark.unit
def test_list_subscribed_only_returns_subscribed(repo):
    repo.upsert(_sample(uid="u1", subscribed=True))
    repo.upsert(_sample(uid="u2", subscribed=False))
    subs = repo.list_subscribed()
    assert [b.platform_user_id for b in subs] == ["u1"]


@pytest.mark.unit
def test_set_subscribed_toggles_flag(repo):
    b = repo.upsert(_sample(uid="u1", subscribed=False))
    repo.set_subscribed(b.id, True)
    assert repo.get(b.id).is_subscribed is True
