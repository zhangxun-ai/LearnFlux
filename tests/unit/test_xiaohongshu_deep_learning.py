"""Deep-learning flow for Xiaohongshu notes."""
from src.video_transcript_api.api.services import transcription
from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.flywheel.models import MediaType
from src.video_transcript_api.flywheel.text_acquisition import NoteDetail
from src.video_transcript_api.utils.perf_tracker import PerfTracker
from src.video_transcript_api.utils.task_status import TaskStatus


SHARE_TEXT = (
    "57 【妈妈再也不用担心我会亏钱啦！ - 昊子商业观察 | 小红书】 "
    "https://www.xiaohongshu.com/discovery/item/69e754ba000000001b003e92"
    "?source=webshare&xhsshare=pc_web"
)
CANONICAL_URL = (
    "https://www.xiaohongshu.com/discovery/item/69e754ba000000001b003e92"
    "?source=webshare&xhsshare=pc_web"
)


class _FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _FakeNotifier:
    def __init__(self):
        self.statuses = []

    def notify_task_status(self, *args, **kwargs):
        self.statuses.append((args, kwargs))

    def send_text(self, *args, **kwargs):
        return None


def _install_cache_and_queue(monkeypatch, tmp_path):
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    queue = _FakeQueue()
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    return cache_manager, queue


def test_xhs_article_note_is_saved_as_deep_learning_text_and_queued(tmp_path, monkeypatch):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=CANONICAL_URL,
        use_speaker_recognition=False,
        platform="xiaohongshu",
        media_id="69e754ba000000001b003e92",
    )

    def fake_fetch(url):
        assert url == CANONICAL_URL
        return NoteDetail(
            note_id="69e754ba000000001b003e92",
            media_type=MediaType.ARTICLE,
            title="妈妈再也不用担心我会亏钱啦！",
            body_text="这是图文正文，应该作为深度学习原文进入结果页。",
            author="昊子商业观察",
        )

    result = transcription._queue_xiaohongshu_article_deep_learning(
        task_id=task["task_id"],
        url=SHARE_TEXT,
        display_url=SHARE_TEXT,
        use_speaker_recognition=False,
        wechat_webhook=None,
        notification_channel=None,
        notification_webhooks={},
        include_comments=False,
        comment_limit=100,
        tracker=PerfTracker(task_id=task["task_id"]),
        task_notifier=_FakeNotifier(),
        note_fetcher=fake_fetch,
    )

    assert result["status"] == "success"
    assert result["data"]["media_type"] == "article"
    assert result["data"]["video_title"] == "妈妈再也不用担心我会亏钱啦！"

    cache = cache_manager.get_cache(
        platform="xiaohongshu",
        media_id="69e754ba000000001b003e92",
        use_speaker_recognition=False,
    )
    assert cache["transcript_data"] == "这是图文正文，应该作为深度学习原文进入结果页。"

    queued = queue.items[0]
    assert queued["platform"] == "xiaohongshu"
    assert queued["media_id"] == "69e754ba000000001b003e92"
    assert queued["transcript"] == "这是图文正文，应该作为深度学习原文进入结果页。"
    assert queued["is_generic"] is False

    task_info = cache_manager.get_task_by_id(task["task_id"])
    assert task_info["status"] == TaskStatus.CALIBRATING
    assert task_info["title"] == "妈妈再也不用担心我会亏钱啦！"


def test_xhs_video_note_falls_through_to_existing_transcription(tmp_path, monkeypatch):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=CANONICAL_URL,
        use_speaker_recognition=False,
        platform="xiaohongshu",
        media_id="69e754ba000000001b003e92",
    )

    def fake_fetch(url):
        assert url == CANONICAL_URL
        return NoteDetail(
            note_id="69e754ba000000001b003e92",
            media_type=MediaType.VIDEO,
            title="妈妈再也不用担心我会亏钱啦！",
            body_text="视频简介不是最终转录文稿",
            author="昊子商业观察",
        )

    result = transcription._queue_xiaohongshu_article_deep_learning(
        task_id=task["task_id"],
        url=SHARE_TEXT,
        display_url=SHARE_TEXT,
        use_speaker_recognition=False,
        wechat_webhook=None,
        notification_channel=None,
        notification_webhooks={},
        include_comments=False,
        comment_limit=100,
        tracker=PerfTracker(task_id=task["task_id"]),
        task_notifier=_FakeNotifier(),
        note_fetcher=fake_fetch,
    )

    assert result is None
    assert queue.items == []
    assert cache_manager.get_cache(
        platform="xiaohongshu",
        media_id="69e754ba000000001b003e92",
        use_speaker_recognition=False,
    ) is None
