import types
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import video_transcript_api.api.services.transcription as transcription
from video_transcript_api.downloaders.models import VideoMetadata, DownloadInfo
from video_transcript_api.transcriber.contracts import TranscriptionResult
from video_transcript_api.transcriber.cloud_config import NewCloudSubmissionSettings
from video_transcript_api.transcriber.media_preparer import PreparedASRMedia
from video_transcript_api.transcriber.providers.aliyun_funasr import AliyunFunASRProvider
from video_transcript_api.transcriber.usage_repository import NewASRAttempt
from video_transcript_api.api.services.post_asr import build_cloud_continuation


class DummyQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class DummyNotifier:
    def __init__(self, webhook=None):
        self.webhook = webhook
        self.messages = []

    def notify_task_status(self, *args, **kwargs):
        self.messages.append(("notify", args, kwargs))

    def send_text(self, text, **kwargs):
        self.messages.append(("send_text", text, kwargs))

    def _clean_url(self, url):
        return url


class DummyCacheManager:
    def __init__(self, cache_data=None):
        self.cache_data = cache_data
        self.saved = []
        self.status_updates = []
        self.tasks = {}

    def get_cache(self, platform, media_id, use_speaker_recognition):
        return self.cache_data

    def save_cache(self, **kwargs):
        self.saved.append(kwargs)
        return True

    def update_task_status(self, task_id, status, **kwargs):
        self.status_updates.append((task_id, status, kwargs))

    def get_task_by_id(self, task_id):
        return self.tasks.get(task_id)


class DummyTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, local_file, output_base):
        return {"transcript": "transcribed text"}


class DummyFunASR:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe_sync(self, local_file):
        return {
            "formatted_text": "funasr text",
            "transcription_result": [{"speaker": "spk_0", "text": "hello"}],
        }

    def format_transcript_with_speakers(self, data):
        return "funasr formatted"


class YoutubeDownloader:
    def __init__(self, subtitle=None, download_url="http://example.com/audio.mp3", filename="test.mp3"):
        self._subtitle = subtitle
        self._download_url = download_url
        self._filename = filename
        self.use_api_server = False

    def get_metadata(self, url):
        return VideoMetadata(
            video_id="abc123",
            platform="youtube",
            title="test title",
            author="test author",
            description="test desc",
        )

    def get_download_info(self, url):
        return DownloadInfo(
            download_url=self._download_url,
            file_ext="mp3",
            filename=self._filename,
        )

    def get_subtitle(self, url):
        return self._subtitle

    def download_file(self, url, filename):
        return "C:/tmp/test.mp3"

    def fetch_for_transcription(self, *args, **kwargs):
        raise AssertionError("fetch_for_transcription should not be called in this test")


class GenericDownloader:
    def __init__(self):
        self.calls = []

    def download_file(self, url, filename):
        self.calls.append((url, filename))
        return "C:/tmp/direct.mp3"


@pytest.fixture
def patch_runtime(monkeypatch):
    queue = DummyQueue()
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "WechatNotifier", DummyNotifier)
    monkeypatch.setattr(transcription, "send_long_text_wechat", lambda *args, **kwargs: None)
    monkeypatch.setattr(transcription, "Transcriber", DummyTranscriber)
    monkeypatch.setattr(transcription, "FunASRSpeakerClient", DummyFunASR)
    monkeypatch.setattr(transcription, "get_base_url", lambda: "http://test")
    return queue


def test_flow_cache_hit(monkeypatch, patch_runtime):
    cache_data = {
        "platform": "youtube",
        "media_id": "abc123",
        "title": "cached title",
        "author": "cached author",
        "description": "cached desc",
        "transcript_type": "capswriter",
        "transcript_data": "cached transcript",
        "use_speaker_recognition": False,
        "llm_calibrated": "calibrated",
        "llm_summary": "summary",
    }
    cache_manager = DummyCacheManager(cache_data=cache_data)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    def fail_create_downloader(url):
        raise AssertionError("create_downloader should not be called on cache hit")

    monkeypatch.setattr(transcription, "create_downloader", fail_create_downloader)

    result = transcription.process_transcription(
        task_id="task_cache_hit",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "success"
    assert result["data"]["cached"] is True
    assert len(patch_runtime.items) == 0


def test_flow_subtitle_preferred(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle="subtitle text")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_subtitle",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "success"
    assert result["data"]["transcript"] == "subtitle text"
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "capswriter"
    assert saved["transcript_data"] == "subtitle text"


def test_flow_download_capswriter(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None, download_url="http://example.com/audio.mp3", filename="audio.mp3")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_download_caps",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result == {"status": "processing", "message": "local_asr_queued"}
    for _ in range(100):
        if cache_manager.saved:
            break
        Event().wait(0.01)
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "capswriter"
    assert saved["use_speaker_recognition"] is False


def test_flow_download_funasr(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None, download_url="http://example.com/audio.mp3", filename="audio.mp3")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_download_funasr",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=True,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "success"
    assert result["data"]["speaker_recognition"] is True
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "funasr"
    assert saved["use_speaker_recognition"] is True


def test_flow_separate_download_url(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    metadata_downloader = YoutubeDownloader(subtitle=None)
    monkeypatch.setattr(transcription, "create_downloader", lambda url: metadata_downloader)

    generic_downloader = GenericDownloader()
    import video_transcript_api.downloaders.generic as generic_module
    monkeypatch.setattr(generic_module, "GenericDownloader", lambda: generic_downloader)

    result = transcription.process_transcription(
        task_id="task_separate_url",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url="http://example.com/file.mp3",
        metadata_override=None,
    )

    assert result == {"status": "processing", "message": "local_asr_queued"}
    assert generic_downloader.calls
    assert generic_downloader.calls[0][0] == "http://example.com/file.mp3"
    assert generic_downloader.calls[0][1] == "file.mp3"


def test_flow_download_url_skips_youtube_api(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None)
    downloader.use_api_server = True
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    generic_downloader = GenericDownloader()
    import video_transcript_api.downloaders.generic as generic_module
    monkeypatch.setattr(generic_module, "GenericDownloader", lambda: generic_downloader)

    result = transcription.process_transcription(
        task_id="task_download_url_skip_api",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url="http://example.com/file.mp3",
        metadata_override=None,
    )

    assert result == {"status": "processing", "message": "local_asr_queued"}
    assert generic_downloader.calls


def test_internal_cloud_url_flow_uses_context_and_single_post_asr_seam(
    monkeypatch, patch_runtime, tmp_path
):
    cache_manager = DummyCacheManager(cache_data=None)
    cache_manager.db_path = tmp_path / "cache.db"
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    downloader = YoutubeDownloader(
        subtitle=None,
        download_url="http://example.com/audio.mp3",
        filename="audio.mp3",
    )
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)
    seen = {}
    prepared_path = tmp_path / "prepared" / "input.m4a"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"prepared-audio")
    prepared = PreparedASRMedia(
        path=prepared_path,
        media_format="m4a",
        duration_seconds=Decimal("2"),
        size_bytes=prepared_path.stat().st_size,
        sha256=hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
        preparation="reused",
    )

    class Preparer:
        def prepare(self, source_path, task_id):
            return prepared

        def cleanup(self, media):
            return None

    monkeypatch.setattr(transcription, "_new_media_preparer", lambda: Preparer())
    continuation_json = build_cloud_continuation(
        task_id="task_cloud_url",
        url="https://www.youtube.com/watch?v=abc123",
        display_url="https://www.youtube.com/watch?v=abc123",
        platform="youtube",
        media_id="abc123",
        video_title="test title",
        author="test author",
        description="test desc",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = transcription.UsageEventRepository(cache_manager.db_path)
    event = repository.reserve_attempt(
        NewASRAttempt(
            task_id="task_cloud_url",
            model="fun-asr-2025-11-07",
            estimated_quantity=Decimal("2"),
            unit_price=Decimal("0.00022"),
            estimated_cost=Decimal("0.00044"),
            owner_key="",
            sample_sha256=prepared.sha256,
            platform="youtube",
            media_id="abc123",
            output_name="lesson",
            continuation_json=continuation_json,
        )
    )
    now = datetime.now(UTC)
    assert repository.claim_submission(event.id, "crashed", now=now)
    assert repository.record_submitted(
        event.id,
        "crashed",
        now=now,
        provider_task_id="private-task",
    )
    assert repository.mark_polling_unknown(
        event.id,
        "crashed",
        now=now,
        error_code="polling_timeout",
    )

    class Snapshotter:
        temp_root = tmp_path / "snapshots"

        def promote(
            self,
            prepared,
            *,
            task_id,
            attempt_no,
            expected_sha256,
            create,
        ):
            assert create is False
            return SimpleNamespace(
                path=self.temp_root / str(attempt_no) / "input.m4a",
                task_hash="b" * 64,
                attempt_no=attempt_no,
                media_format="m4a",
                sha256=expected_sha256,
                size_bytes=prepared.size_bytes,
                duration_seconds=Decimal("2"),
            )

        def find_attempt(
            self,
            *,
            task_id,
            attempt_no,
            expected_sha256,
            duration_seconds,
        ):
            return SimpleNamespace(
                path=self.temp_root / str(attempt_no) / "input.m4a",
                task_hash="b" * 64,
                attempt_no=attempt_no,
                media_format="m4a",
                sha256=expected_sha256,
                size_bytes=4,
                duration_seconds=Decimal(duration_seconds),
            )

        def cleanup_attempt(self, snapshot):
            return None

    class PollOnlyClient:
        submits = 0

        def upload_audio(self, *args, **kwargs):
            raise AssertionError("re-entry must not upload")

        def submit(self, *args, **kwargs):
            self.submits += 1
            raise AssertionError("re-entry must not submit")

        def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
            assert task_id == "private-task"
            return {
                "task_id": task_id,
                "status": "SUCCEEDED",
                "usage_seconds": 2,
                "results": [
                    {
                        "status": "SUCCEEDED",
                        "transcript": {
                            "text": "cloud text",
                            "sentences": [
                                {
                                    "text": "cloud text",
                                    "start_time": 0.0,
                                    "end_time": 2.0,
                                }
                            ],
                        },
                    }
                ],
            }

    client = PollOnlyClient()
    settings = NewCloudSubmissionSettings(
        provider="aliyun",
        model="fun-asr-2025-11-07",
        region="cn-beijing",
        max_cny_per_task=Decimal("1"),
        price_cny_per_second=Decimal("0.00022"),
        price_verified_at=date(2026, 7, 21),
        poll_interval_seconds=1,
        poll_timeout_seconds=300,
    )

    class CloudTranscriber:
        def __init__(self, *args, **kwargs):
            seen["strategy"] = kwargs.get("strategy")

        def transcribe(self, local_file, output_base, *, context):
            seen["context"] = context
            provider = AliyunFunASRProvider(
                settings=settings,
                repository=repository,
                snapshotter=Snapshotter(),
                output_dir=tmp_path / "outputs",
                credential_loader=lambda: object(),
                client_factory=lambda credentials: client,
                attempt_reserver=repository.reserve_attempt,
                prepared_media_cleanup=lambda prepared: None,
            )
            self.last_result = provider.transcribe(
                local_file, output_base, context=context
            )
            return self.last_result.to_legacy_dict()

    monkeypatch.setattr(transcription, "Transcriber", CloudTranscriber)

    result = transcription.process_transcription(
        task_id="task_cloud_url",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        transcription_strategy="cloud",
    )

    assert result["status"] == "success"
    assert seen["strategy"] == "cloud"
    assert seen["context"].task_id == "task_cloud_url"
    assert len(patch_runtime.items) == 1
    assert patch_runtime.items[0]["usage_event_id"]
    assert client.submits == 0
