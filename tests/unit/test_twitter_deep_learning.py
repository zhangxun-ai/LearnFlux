"""Deep-learning flow for X / Twitter posts."""
from src.video_transcript_api.api.services import transcription
from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.comments.twitter_post import TwitterPost
from src.video_transcript_api.utils.perf_tracker import PerfTracker
from src.video_transcript_api.utils.task_status import TaskStatus


TWEET_URL = "https://x.com/knowledgefxg/status/2080262589804839241?s=46"
CANONICAL_URL = "https://x.com/knowledgefxg/status/2080262589804839241"
TWEET_ID = "2080262589804839241"
THREAD_TEXT = (
    "这是一条 X 帖子正文。\n\n"
    "应该作为单篇深度学习原文进入结果页，而不是走通用媒体下载。"
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


class _FakeFetcher:
    def __init__(self, post: TwitterPost):
        self.post = post
        self.calls = []

    def fetch(self, url, tweet_id, max_comments=80):
        self.calls.append((url, tweet_id, max_comments))
        return self.post


def _install_cache_and_queue(monkeypatch, tmp_path):
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    queue = _FakeQueue()
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    return cache_manager, queue


def test_twitter_post_is_saved_as_deep_learning_text_and_queued(tmp_path, monkeypatch):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=TWEET_URL,
        use_speaker_recognition=False,
        platform="twitter",
        media_id=TWEET_ID,
    )

    fetcher = _FakeFetcher(
        TwitterPost(
            title="这是一条 X 帖子正文。",
            author="knowledgefxg",
            thread_text=THREAD_TEXT,
            comments=[],
            main_tweet_id=TWEET_ID,
        )
    )

    result = transcription._queue_twitter_post_deep_learning(
        task_id=task["task_id"],
        url=TWEET_URL,
        display_url=TWEET_URL,
        tweet_id=TWEET_ID,
        use_speaker_recognition=False,
        wechat_webhook=None,
        notification_channel=None,
        notification_webhooks={},
        include_comments=False,
        comment_limit=100,
        tracker=PerfTracker(task_id=task["task_id"]),
        task_notifier=_FakeNotifier(),
        post_fetcher=fetcher,
    )

    assert result["status"] == "success"
    assert result["data"]["media_type"] == "article"
    assert result["data"]["video_title"] == "这是一条 X 帖子正文。"
    assert result["data"]["author"] == "knowledgefxg"
    assert result["data"]["transcript"] == THREAD_TEXT

    assert len(fetcher.calls) == 1
    called_url, called_id, called_max = fetcher.calls[0]
    assert called_id == TWEET_ID
    assert called_max == 0
    assert "2080262589804839241" in called_url

    cache = cache_manager.get_cache(
        platform="twitter",
        media_id=TWEET_ID,
        use_speaker_recognition=False,
    )
    assert cache["transcript_data"] == THREAD_TEXT

    queued = queue.items[0]
    assert queued["platform"] == "twitter"
    assert queued["media_id"] == TWEET_ID
    assert queued["transcript"] == THREAD_TEXT
    assert queued["is_generic"] is False

    task_info = cache_manager.get_task_by_id(task["task_id"])
    assert task_info["status"] == TaskStatus.CALIBRATING
    assert task_info["title"] == "这是一条 X 帖子正文。"


def test_twitter_empty_thread_raises(tmp_path, monkeypatch):
    cache_manager, _queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=TWEET_URL,
        use_speaker_recognition=False,
        platform="twitter",
        media_id=TWEET_ID,
    )
    fetcher = _FakeFetcher(
        TwitterPost(
            title="X 帖子",
            author="knowledgefxg",
            thread_text="   ",
            comments=[],
            main_tweet_id=TWEET_ID,
        )
    )

    try:
        transcription._queue_twitter_post_deep_learning(
            task_id=task["task_id"],
            url=TWEET_URL,
            display_url=TWEET_URL,
            tweet_id=TWEET_ID,
            use_speaker_recognition=False,
            wechat_webhook=None,
            notification_channel=None,
            notification_webhooks={},
            include_comments=False,
            comment_limit=100,
            tracker=PerfTracker(task_id=task["task_id"]),
            task_notifier=_FakeNotifier(),
            post_fetcher=fetcher,
        )
        assert False, "expected ValueError for empty thread"
    except ValueError as exc:
        assert "正文为空" in str(exc)
