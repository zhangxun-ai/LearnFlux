# 创作飞轮 Phase 1 — 数据基座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为创作飞轮建立持久化基座 —— `blogger` 与 `content` 的领域模型 + SQLite 仓储层（含筛选/排序/分页查询），纯逻辑、零网络、完全可测。

**Architecture:** 沿用项目现有 `cache_manager` 的裸 `sqlite3` 模式（线程本地连接 + `_get_cursor` 上下文管理器 + `CREATE TABLE IF NOT EXISTS`）。领域模型用 frozen dataclass。仓储以 Protocol 定义接口、SQLite 实现，业务逻辑只依赖接口（为日后换 Supabase 留出口）。新库文件独立于缓存库：`data/flywheel/flywheel.db`。

**Tech Stack:** Python 3.11+ · 标准库 `sqlite3` · `dataclasses` / `enum` · pytest（`tmp_path` fixture，`unit` 标记）。

---

## 阶段路线图（每阶段单独成计划、单独可测）

1. **Phase 1（本计划）数据基座**：`blogger` / `content` 模型 + 仓储（筛选/排序/分页）。
2. Phase 2 抓取：`xiaohongshu_user` —— 主页链接 → user_id/xsec_token → 作品列表 → `Content` 入库（mock TikHub 测）。
3. Phase 3 解析引擎：`analysis` / `analysis_cost` / `prompt_template` 表 + 视频/图文双提示词 + 异步状态机 + 成本记账。
4. Phase 4 API + 内容列表：`GET /api/bloggers`、`GET /api/contents`（5 筛选 + 排序 + 分页 + 分组）、解析/批量解析路由。
5. Phase 5 整体套路（多样本 map-reduce）+ 提示词编辑 + 我的诊断。
6. Phase 6 UI：把 mockup 落成 Jinja 模板（三 Tab + 详情 + 解析结果 + 用量）。

---

## Phase 1 文件结构

- Create: `src/video_transcript_api/flywheel/__init__.py` — 包入口（空）。
- Create: `src/video_transcript_api/flywheel/models.py` — 枚举 + `Blogger` / `Content` frozen dataclass。
- Create: `src/video_transcript_api/flywheel/db.py` — `FlywheelDB`：连接 + 建表。
- Create: `src/video_transcript_api/flywheel/repositories.py` — `BloggerRepository` / `ContentRepository`（Protocol + SQLite 实现）+ `ContentQuery` 过滤器。
- Test: `tests/unit/test_flywheel_models.py` · `tests/unit/test_flywheel_blogger_repo.py` · `tests/unit/test_flywheel_content_repo.py`

---

## Task 1: 领域模型

**Files:**
- Create: `src/video_transcript_api/flywheel/__init__.py`
- Create: `src/video_transcript_api/flywheel/models.py`
- Test: `tests/unit/test_flywheel_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_flywheel_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flywheel_models.py -v`
Expected: FAIL — `ModuleNotFoundError: ... flywheel.models`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_transcript_api/flywheel/__init__.py
"""Creation-flywheel feature package (benchmark analysis + my-content diagnosis)."""
```

```python
# src/video_transcript_api/flywheel/models.py
"""Domain models for the creation flywheel. Immutable, storage-agnostic."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MediaType(str, Enum):
    VIDEO = "video"
    ARTICLE = "article"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class ContentSource(str, Enum):
    FEED = "feed"      # 来自订阅博主的内容流
    ADHOC = "adhoc"    # 临时解析的单条


@dataclass(frozen=True)
class Blogger:
    id: Optional[int]
    platform: str
    platform_user_id: str
    handle: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    follower_count: int = 0
    media_types: tuple[MediaType, ...] = ()
    is_subscribed: bool = False
    pinned: bool = False
    last_post_at: Optional[datetime] = None
    subscribed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class Content:
    id: Optional[int]
    blogger_id: int
    platform: str
    platform_item_id: str
    media_type: MediaType
    title: str
    original_url: str
    cover_url: Optional[str] = None
    published_at: Optional[datetime] = None
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    stats_synced_at: Optional[datetime] = None
    source: ContentSource = ContentSource.FEED
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING
    latest_analysis_id: Optional[int] = None
    created_at: Optional[datetime] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flywheel_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/video_transcript_api/flywheel/__init__.py src/video_transcript_api/flywheel/models.py tests/unit/test_flywheel_models.py
git commit -m "feat(flywheel): add blogger/content domain models"
```

---

## Task 2: 数据库连接与建表

**Files:**
- Create: `src/video_transcript_api/flywheel/db.py`
- Test: `tests/unit/test_flywheel_blogger_repo.py`（本任务先放建表测试，下一任务复用同文件）

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_flywheel_blogger_repo.py
import pytest
from src.video_transcript_api.flywheel.db import FlywheelDB


@pytest.fixture
def db(tmp_path):
    d = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    yield d
    d.close()


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flywheel_blogger_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: ... flywheel.db`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_transcript_api/flywheel/db.py
"""SQLite connection + schema for the flywheel feature.

Mirrors cache_manager's pattern: thread-local connections, WAL mode,
a `cursor()` context manager that commits/rolls back. New tables only;
does not touch the transcription cache DB.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from ..utils.logging import setup_logger

logger = setup_logger("flywheel_db")


class FlywheelDB:
    def __init__(self, db_path: str = "./data/flywheel/flywheel.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.OperationalError:
                logger.warning("WAL/foreign_keys not supported")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def cursor(self):
        conn = self._connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"flywheel db error: {e}")
            raise
        finally:
            cur.close()

    def _init_schema(self):
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS blogger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    avatar_url TEXT,
                    bio TEXT,
                    follower_count INTEGER NOT NULL DEFAULT 0,
                    media_types TEXT NOT NULL DEFAULT '[]',
                    is_subscribed INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    last_post_at TIMESTAMP,
                    subscribed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, platform_user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blogger_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    cover_url TEXT,
                    published_at TIMESTAMP,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    collect_count INTEGER NOT NULL DEFAULT 0,
                    comment_count INTEGER NOT NULL DEFAULT 0,
                    share_count INTEGER NOT NULL DEFAULT 0,
                    stats_synced_at TIMESTAMP,
                    source TEXT NOT NULL DEFAULT 'feed',
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    latest_analysis_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, platform_item_id),
                    FOREIGN KEY (blogger_id) REFERENCES blogger(id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_blogger_pub ON content(blogger_id, published_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_status ON content(analysis_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_pub ON content(published_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_media ON content(media_type)")

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flywheel_blogger_repo.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/video_transcript_api/flywheel/db.py tests/unit/test_flywheel_blogger_repo.py
git commit -m "feat(flywheel): add sqlite schema for blogger/content"
```

---

## Task 3: BloggerRepository

**Files:**
- Create: `src/video_transcript_api/flywheel/repositories.py`
- Test: `tests/unit/test_flywheel_blogger_repo.py`（追加）

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/unit/test_flywheel_blogger_repo.py
from src.video_transcript_api.flywheel.models import Blogger, MediaType
from src.video_transcript_api.flywheel.repositories import SqliteBloggerRepository


@pytest.fixture
def repo(db):
    return SqliteBloggerRepository(db)


def _sample(uid="u1", subscribed=False):
    return Blogger(id=None, platform="xiaohongshu", platform_user_id=uid,
                   handle="@阿K", media_types=(MediaType.VIDEO,), is_subscribed=subscribed)


@pytest.mark.unit
def test_upsert_inserts_then_returns_id(repo):
    saved = repo.upsert(_sample())
    assert saved.id is not None
    assert saved.handle == "@阿K"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flywheel_blogger_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: ... flywheel.repositories`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_transcript_api/flywheel/repositories.py
"""Storage-agnostic repository interfaces + SQLite implementations."""
from __future__ import annotations

import json
from typing import Optional, Protocol

from .db import FlywheelDB
from .models import Blogger, MediaType


def _blogger_from_row(row) -> Blogger:
    return Blogger(
        id=row["id"],
        platform=row["platform"],
        platform_user_id=row["platform_user_id"],
        handle=row["handle"],
        avatar_url=row["avatar_url"],
        bio=row["bio"],
        follower_count=row["follower_count"],
        media_types=tuple(MediaType(m) for m in json.loads(row["media_types"])),
        is_subscribed=bool(row["is_subscribed"]),
        pinned=bool(row["pinned"]),
    )


class BloggerRepository(Protocol):
    def upsert(self, blogger: Blogger) -> Blogger: ...
    def get(self, blogger_id: int) -> Optional[Blogger]: ...
    def list_subscribed(self) -> list[Blogger]: ...
    def set_subscribed(self, blogger_id: int, value: bool) -> None: ...


class SqliteBloggerRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def upsert(self, blogger: Blogger) -> Blogger:
        media = json.dumps([m.value for m in blogger.media_types])
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO blogger (platform, platform_user_id, handle, avatar_url,
                    bio, follower_count, media_types, is_subscribed, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_user_id) DO UPDATE SET
                    handle=excluded.handle, avatar_url=excluded.avatar_url, bio=excluded.bio,
                    follower_count=excluded.follower_count, media_types=excluded.media_types
                """,
                (blogger.platform, blogger.platform_user_id, blogger.handle, blogger.avatar_url,
                 blogger.bio, blogger.follower_count, media, int(blogger.is_subscribed), int(blogger.pinned)),
            )
            cur.execute("SELECT * FROM blogger WHERE platform=? AND platform_user_id=?",
                        (blogger.platform, blogger.platform_user_id))
            return _blogger_from_row(cur.fetchone())

    def get(self, blogger_id: int) -> Optional[Blogger]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM blogger WHERE id=?", (blogger_id,))
            row = cur.fetchone()
            return _blogger_from_row(row) if row else None

    def list_subscribed(self) -> list[Blogger]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM blogger WHERE is_subscribed=1 "
                "ORDER BY pinned DESC, last_post_at DESC, id DESC"
            )
            return [_blogger_from_row(r) for r in cur.fetchall()]

    def set_subscribed(self, blogger_id: int, value: bool) -> None:
        with self._db.cursor() as cur:
            cur.execute("UPDATE blogger SET is_subscribed=? WHERE id=?", (int(value), blogger_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flywheel_blogger_repo.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/video_transcript_api/flywheel/repositories.py tests/unit/test_flywheel_blogger_repo.py
git commit -m "feat(flywheel): add BloggerRepository (sqlite)"
```

---

## Task 4: ContentRepository（筛选 + 排序 + 分页）

**Files:**
- Modify: `src/video_transcript_api/flywheel/repositories.py`（追加 `ContentQuery` + `SqliteContentRepository`）
- Test: `tests/unit/test_flywheel_content_repo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_flywheel_content_repo.py
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
    page = crepo.list(ContentQuery(statuses=[AnalysisStatus.SUCCESS, AnalysisStatus.FAILED]))
    assert {c.platform_item_id for c in page.items} == {"n2", "n3"}


@pytest.mark.unit
def test_filter_by_date_range(env):
    _, crepo, b = env
    crepo.upsert(_c(b, "old", days_ago=40))
    crepo.upsert(_c(b, "new", days_ago=1))
    page = crepo.list(ContentQuery(date_from=datetime(2026, 6, 1)))
    assert [c.platform_item_id for c in page.items] == ["new"]


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flywheel_content_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'SqliteContentRepository'`.

- [ ] **Step 3: Write minimal implementation (append to repositories.py)**

```python
# append to src/video_transcript_api/flywheel/repositories.py
from dataclasses import dataclass, field
from datetime import datetime
from .models import Content, AnalysisStatus, ContentSource


def _content_from_row(row) -> Content:
    def _dt(v):
        return datetime.fromisoformat(v) if v else None
    return Content(
        id=row["id"], blogger_id=row["blogger_id"], platform=row["platform"],
        platform_item_id=row["platform_item_id"], media_type=MediaType(row["media_type"]),
        title=row["title"], original_url=row["original_url"], cover_url=row["cover_url"],
        published_at=_dt(row["published_at"]),
        like_count=row["like_count"], collect_count=row["collect_count"],
        comment_count=row["comment_count"], share_count=row["share_count"],
        source=ContentSource(row["source"]), analysis_status=AnalysisStatus(row["analysis_status"]),
        latest_analysis_id=row["latest_analysis_id"],
    )


@dataclass(frozen=True)
class ContentQuery:
    """Filter/sort/paginate spec for content listing (maps 1:1 to UI filters)."""
    subscribed: Optional[bool] = None            # None=全部
    blogger_ids: tuple[int, ...] = ()            # () = 全部
    statuses: tuple = ()                         # () = 全部; else list[AnalysisStatus]
    media_type: Optional[MediaType] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sort: str = "published_at"                   # or "like_count"
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))  # ceil div


class ContentRepository(Protocol):
    def upsert(self, content: Content) -> Content: ...
    def get(self, content_id: int) -> Optional[Content]: ...
    def list(self, query: "ContentQuery") -> "Page": ...
    def set_analysis_status(self, content_id: int, status: AnalysisStatus,
                            analysis_id: Optional[int] = None) -> None: ...


class SqliteContentRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def upsert(self, content: Content) -> Content:
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO content (blogger_id, platform, platform_item_id, media_type,
                    title, original_url, cover_url, published_at, like_count, collect_count,
                    comment_count, share_count, source, analysis_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_item_id) DO UPDATE SET
                    title=excluded.title, cover_url=excluded.cover_url,
                    like_count=excluded.like_count, collect_count=excluded.collect_count,
                    comment_count=excluded.comment_count, share_count=excluded.share_count
                """,
                (content.blogger_id, content.platform, content.platform_item_id,
                 content.media_type.value, content.title, content.original_url, content.cover_url,
                 content.published_at.isoformat() if content.published_at else None,
                 content.like_count, content.collect_count, content.comment_count,
                 content.share_count, content.source.value, content.analysis_status.value),
            )
            cur.execute("SELECT * FROM content WHERE platform=? AND platform_item_id=?",
                        (content.platform, content.platform_item_id))
            return _content_from_row(cur.fetchone())

    def get(self, content_id: int) -> Optional[Content]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM content WHERE id=?", (content_id,))
            row = cur.fetchone()
            return _content_from_row(row) if row else None

    def list(self, query: "ContentQuery") -> "Page":
        where, params = [], []
        if query.blogger_ids:
            where.append(f"c.blogger_id IN ({','.join('?' * len(query.blogger_ids))})")
            params += list(query.blogger_ids)
        if query.statuses:
            where.append(f"c.analysis_status IN ({','.join('?' * len(query.statuses))})")
            params += [s.value for s in query.statuses]
        if query.media_type:
            where.append("c.media_type=?"); params.append(query.media_type.value)
        if query.date_from:
            where.append("c.published_at>=?"); params.append(query.date_from.isoformat())
        if query.date_to:
            where.append("c.published_at<=?"); params.append(query.date_to.isoformat())
        if query.subscribed is not None:
            where.append("b.is_subscribed=?"); params.append(int(query.subscribed))
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = "c.like_count DESC" if query.sort == "like_count" else "c.published_at DESC"
        base = f"FROM content c JOIN blogger b ON c.blogger_id=b.id{clause}"
        with self._db.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) {base}", params)
            total = cur.fetchone()[0]
            offset = (query.page - 1) * query.page_size
            cur.execute(f"SELECT c.* {base} ORDER BY {order}, c.id DESC LIMIT ? OFFSET ?",
                        params + [query.page_size, offset])
            items = [_content_from_row(r) for r in cur.fetchall()]
        return Page(items=items, total=total, page=query.page, page_size=query.page_size)

    def set_analysis_status(self, content_id: int, status: AnalysisStatus,
                            analysis_id: Optional[int] = None) -> None:
        with self._db.cursor() as cur:
            cur.execute("UPDATE content SET analysis_status=?, latest_analysis_id=? WHERE id=?",
                        (status.value, analysis_id, content_id))
```

> Note: `ContentQuery.statuses` is typed loosely as `tuple` to avoid a forward-ref to `AnalysisStatus` in the dataclass; tests pass `list[AnalysisStatus]` and the `.value` access in `list()` handles it. Accept either list or tuple.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flywheel_content_repo.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Run the full flywheel unit suite + commit**

Run: `pytest tests/unit/test_flywheel_*.py -q`
Expected: PASS (all flywheel tests green).

```bash
git add src/video_transcript_api/flywheel/repositories.py tests/unit/test_flywheel_content_repo.py
git commit -m "feat(flywheel): add ContentRepository with filter/sort/pagination"
```

---

## Self-Review

- **Spec coverage (Phase 1 scope):** models（§6 blogger/content）✓；筛选口径（§5：订阅状态/博主/状态多选/类型/日期/排序）→ `ContentQuery` 字段一一对应 ✓；分页分组的"分页"由 `Page` 提供，"按日期↓+博主分组"是展示层职责（Phase 6），数据层已按 `published_at DESC` 排序 ✓；`is_subscribed`/`source(feed/adhoc)` 支撑"订阅状态"筛选 ✓。
- **超出 Phase 1（留给后续计划，非缺口）：** `analysis` / `analysis_cost` / `prompt_template` 表（Phase 3）、抓取（Phase 2）、API（Phase 4）。
- **Placeholder scan:** 无 TODO/TBD；每步含完整代码与命令。
- **Type consistency:** `MediaType/AnalysisStatus/ContentSource` 在 models 定义，repo 与测试一致引用；`ContentQuery` 字段名与 `list()` 内使用一致（`blogger_ids/statuses/media_type/date_from/date_to/sort/page/page_size`）。
