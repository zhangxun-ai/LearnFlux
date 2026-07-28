import pytest


def test_normalize_plain_transcript_returns_untimed_lines():
    from video_transcript_api.study.transcript import normalize_transcript

    lines = normalize_transcript("第一段内容。\n\n第二段内容。")

    assert [line["text"] for line in lines] == ["第一段内容。", "第二段内容。"]
    assert all(line["start_seconds"] is None for line in lines)
    assert all(line["seekable"] is False for line in lines)


def test_normalize_long_plain_transcript_splits_into_readable_sentences():
    from video_transcript_api.study.transcript import normalize_transcript

    transcript = (
        "第一句话介绍课程背景，帮助听众进入状态。"
        "第二句话继续解释核心概念，并给出具体例子。"
        "第三句话总结这一部分，提醒听众继续思考。"
    )

    lines = normalize_transcript(transcript)

    assert [line["text"] for line in lines] == [
        "第一句话介绍课程背景，帮助听众进入状态。",
        "第二句话继续解释核心概念，并给出具体例子。",
        "第三句话总结这一部分，提醒听众继续思考。",
    ]
    assert all(line["seekable"] is False for line in lines)


def test_normalize_short_plain_transcript_keeps_existing_line_boundaries():
    from video_transcript_api.study.transcript import normalize_transcript

    lines = normalize_transcript("短句一。\n短句二。")

    assert [line["text"] for line in lines] == ["短句一。", "短句二。"]


def test_normalize_funasr_segments_returns_seekable_lines():
    from video_transcript_api.study.transcript import normalize_transcript

    payload = [
        {"text": "第一句", "start": 1200, "end": 2400},
        {"sentence": "第二句", "start_time": 3.5, "end_time": 5.0},
    ]

    lines = normalize_transcript(payload)

    assert lines[0]["text"] == "第一句"
    assert lines[0]["start_seconds"] == 1.2
    assert lines[0]["end_seconds"] == 2.4
    assert lines[0]["seekable"] is True
    assert lines[1]["text"] == "第二句"
    assert lines[1]["start_seconds"] == 3.5
    assert lines[1]["seekable"] is True


def test_normalize_nested_funasr_payload():
    from video_transcript_api.study.transcript import normalize_transcript

    payload = {"segments": [{"text": "嵌套句子", "start": 0, "end": 1500}]}

    lines = normalize_transcript(payload)

    assert len(lines) == 1
    assert lines[0]["text"] == "嵌套句子"
    assert lines[0]["start_seconds"] == 0
    assert lines[0]["end_seconds"] == 1.5


def test_normalize_repairs_legacy_long_whisper_timestamp_reset():
    from video_transcript_api.study.transcript import normalize_transcript

    payload = {
        "segments": [
            {"text": "边界前", "start_time": 997.3, "end_time": 999.12},
            {"text": "跨越边界", "start_time": 999.36, "end_time": 1.001},
            {"text": "边界后", "start_time": 1.002, "end_time": 1.005},
        ]
    }

    lines = normalize_transcript(payload)

    assert [line["start_seconds"] for line in lines] == [997.3, 999.36, 1002.0]
    assert [line["end_seconds"] for line in lines] == [999.12, 1001.0, 1005.0]


def test_local_upload_preserves_structured_transcript_cache(monkeypatch, tmp_path):
    import queue
    from threading import Event

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager
    from video_transcript_api.study.transcript import normalize_transcript

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    media_id = "local_structured"
    display_url = f"local://study-source/{media_id}/lesson.mp4"
    task = cache_manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"fake video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *_args):
            return {
                "transcript": "第一句。第二句。",
                "funasr_json_data": {
                    "segments": [
                        {"text": "第一句。", "start_time": 0.0, "end_time": 1.5},
                        {"text": "第二句。", "start_time": 1.5, "end_time": 3.0},
                    ]
                },
            }

    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue.Queue())
    monkeypatch.setattr(transcription, "_extract_audio_to_file", lambda *_args: None)
    monkeypatch.setattr(transcription, "Transcriber", FakeTranscriber)

    result = transcription.process_local_upload(
        task["task_id"],
        str(source),
        "lesson.mp4",
        display_url,
        media_id,
        preserve_source_file=True,
        preserve_transcript_timestamps=True,
    )

    cached = None
    for _ in range(100):
        cached = cache_manager.get_cache(platform="generic", media_id=media_id)
        if cached:
            break
        Event().wait(0.01)
    cache_manager.close()

    assert result == {"status": "processing", "message": "local_asr_queued"}
    assert cached is not None
    assert cached["transcript_type"] == "funasr"
    lines = normalize_transcript(cached["transcript_data"])
    assert [line["start_seconds"] for line in lines] == [0.0, 1.5]


def test_local_upload_retry_uses_task_scoped_audio_and_output_names(
    monkeypatch, tmp_path
):
    from video_transcript_api.api.services import transcription

    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"fake video")
    extraction_keys = []
    transcriptions = []

    class Cache:
        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def update_task_status(self, *args, **kwargs):
            return None

    def extract_audio(source_path, output_dir, artifact_key):
        extraction_keys.append(artifact_key)
        audio_path = tmp_path / f"{artifact_key}.m4a"
        audio_path.write_bytes(b"audio")
        return str(audio_path)

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            return None

        def transcribe(self, audio_path, output_base):
            transcriptions.append((audio_path, output_base))
            return {"transcript": "正文", "funasr_json_data": {}}

    def submit_immediately(**kwargs):
        kwargs["run_provider"]()

    monkeypatch.setattr(transcription, "cache_manager", Cache())
    monkeypatch.setattr(transcription, "_extract_audio_to_file", extract_audio)
    monkeypatch.setattr(transcription, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(
        transcription, "submit_local_asr_continuation", submit_immediately
    )

    for task_id in ("task-first", "task-retry"):
        result = transcription.process_local_upload(
            task_id,
            str(source),
            "lesson.mp4",
            "local://study-source/shared/lesson.mp4",
            "shared-media",
            preserve_source_file=True,
        )
        assert result == {"status": "processing", "message": "local_asr_queued"}

    assert extraction_keys == [
        "shared-media_task-first",
        "shared-media_task-retry",
    ]
    assert [output_base for _, output_base in transcriptions] == [
        "task-first",
        "task-retry",
    ]


@pytest.mark.parametrize("strategy", ["local", "cloud"])
def test_completed_video_upload_reuses_cache_before_asr_or_cloud_quote(
    monkeypatch, tmp_path, strategy
):
    import queue

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    media_id = "local_same_video"
    display_url = f"local://study-source/{media_id}/lesson.mp4"
    completed = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
    )
    manager.save_cache(
        platform="generic",
        url=display_url,
        media_id=media_id,
        use_speaker_recognition=False,
        transcript_data="cached transcript",
        transcript_type="capswriter",
        title="lesson.mp4",
        author="本地上传",
    )
    manager.save_llm_result(
        "generic", media_id, False, "calibrated", "cached calibrated"
    )
    manager.save_llm_result(
        "generic", media_id, False, "summary", "cached summary"
    )
    manager.update_task_status(
        completed["task_id"],
        "success",
        platform="generic",
        media_id=media_id,
        title="lesson.mp4",
    )
    canceled = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    manager.update_task_status(canceled["task_id"], "canceled")
    current = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"same video")

    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue.Queue())
    monkeypatch.setattr(
        transcription,
        "_extract_audio_to_file",
        lambda *_args: (_ for _ in ()).throw(AssertionError("local ASR started")),
    )
    monkeypatch.setattr(
        transcription,
        "_pause_for_cloud_confirmation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cloud quote started")),
    )

    try:
        result = transcription.process_local_upload(
            current["task_id"],
            str(source),
            "lesson.mp4",
            display_url,
            media_id,
            preserve_source_file=True,
            transcription_strategy=strategy,
            cloud_confirmation_required=True,
        )
        current_task = manager.get_task_by_id(current["task_id"])
    finally:
        manager.close()

    assert result == {"status": "success", "message": "cache_hit"}
    assert current_task["status"] == "success"
    assert current_task["progress"]["evidence"]["cache_hit"] is True
    assert (
        current_task["progress"]["evidence"]["source_task_id"]
        == completed["task_id"]
    )


def test_explicit_reparse_skips_completed_cache_and_prepares_fresh_cloud_quote(
    monkeypatch, tmp_path
):
    import queue

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    media_id = "local_reparse_video"
    display_url = f"local://study-source/{media_id}/lesson.mp4"
    completed = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
    )
    manager.save_cache(
        platform="generic",
        url=display_url,
        media_id=media_id,
        use_speaker_recognition=False,
        transcript_data="old transcript",
        transcript_type="capswriter",
        title="lesson.mp4",
        author="本地上传",
    )
    manager.save_llm_result(
        "generic", media_id, False, "summary", "old summary"
    )
    manager.update_task_status(
        completed["task_id"],
        "success",
        platform="generic",
        media_id=media_id,
    )
    current = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"same video")
    quote_calls = []

    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue.Queue())
    monkeypatch.setattr(
        transcription,
        "_pause_for_cloud_confirmation",
        lambda **kwargs: quote_calls.append(kwargs)
        or {"status": "awaiting_cloud_confirmation"},
    )

    try:
        result = transcription.process_local_upload(
            current["task_id"],
            str(source),
            "lesson.mp4",
            display_url,
            media_id,
            preserve_source_file=True,
            transcription_strategy="cloud",
            cloud_confirmation_required=True,
            skip_cache=True,
        )
        current_task = manager.get_task_by_id(current["task_id"])
    finally:
        manager.close()

    assert result == {"status": "awaiting_cloud_confirmation"}
    assert len(quote_calls) == 1
    assert current_task["status"] == "processing"


def test_canceled_upload_does_not_block_a_fresh_parse(monkeypatch, tmp_path):
    import queue

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    media_id = "local_canceled_video"
    display_url = f"local://study-source/{media_id}/lesson.mp4"
    canceled = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
    )
    manager.save_cache(
        platform="generic",
        url=display_url,
        media_id=media_id,
        use_speaker_recognition=False,
        transcript_data="partial transcript from canceled attempt",
        transcript_type="capswriter",
    )
    manager.update_task_status(canceled["task_id"], "canceled")
    current = manager.create_task(
        url=display_url,
        platform="generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"video")
    provider_calls = []

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *_args):
            provider_calls.append(True)
            return {"transcript": "fresh transcript", "funasr_json_data": {}}

    def submit_immediately(**kwargs):
        result = kwargs["run_provider"]()
        kwargs["after_provider"](result)

    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue.Queue())
    monkeypatch.setattr(transcription, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(transcription, "_extract_audio_to_file", lambda *_: None)
    monkeypatch.setattr(
        transcription, "submit_local_asr_continuation", submit_immediately
    )

    try:
        result = transcription.process_local_upload(
            current["task_id"],
            str(source),
            "lesson.mp4",
            display_url,
            media_id,
            preserve_source_file=True,
            transcription_strategy="local",
        )
        current_task = manager.get_task_by_id(current["task_id"])
    finally:
        manager.close()

    assert result == {"status": "processing", "message": "local_asr_queued"}
    assert provider_calls == [True]
    assert current_task["status"] == "calibrating"


def test_clean_visual_document_skips_llm_and_preserves_extracted_text(monkeypatch, tmp_path):
    import queue
    from pathlib import Path

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = manager.create_task(
        url="local://study-source/clean/guide.pdf",
        platform="generic",
        media_id="clean",
    )
    source = tmp_path / "guide.pdf"
    source.write_bytes(b"pdf")
    extracted = "\ufeff" + "".join(
        f"第 {index} 节：干净的正文内容。" + ("\r\n" if index % 2 else "\r")
        for index in range(80)
    )
    llm_queue = queue.Queue()
    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "llm_task_queue", llm_queue)
    monkeypatch.setattr(transcription, "_extract_document_text", lambda *_: extracted)

    result = transcription.process_local_upload(
        task["task_id"],
        str(source),
        "guide.pdf",
        "local://study-source/clean/guide.pdf",
        "clean",
        preserve_source_file=True,
        document_fast_path=True,
    )

    cached = manager.get_cache("generic", "clean")
    progress = manager.get_task_by_id(task["task_id"])["progress"]
    assert result["status"] == "success"
    assert llm_queue.empty()
    cached_file = Path(cached["file_path"]) / "transcript_capswriter.txt"
    with cached_file.open("r", encoding="utf-8", newline="") as saved:
        assert saved.read() == extracted
    assert progress["evidence"]["analysis_mode"] == "document_fast"
    assert progress["evidence"]["visual_ready"] is True
    assert "canonical_text" not in repr(progress["evidence"])


def test_low_quality_visual_document_falls_back_with_bounded_evidence(monkeypatch, tmp_path):
    import queue

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = manager.create_task(
        url="local://study-source/bad/bad.pdf",
        platform="generic",
        media_id="bad",
    )
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"pdf")
    extracted = ("有效正文" * 80) + ("\x00" * 40)
    llm_queue = queue.Queue()
    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "llm_task_queue", llm_queue)
    monkeypatch.setattr(transcription, "_extract_document_text", lambda *_: extracted)

    result = transcription.process_local_upload(
        task["task_id"],
        str(source),
        "bad.pdf",
        "local://study-source/bad/bad.pdf",
        "bad",
        preserve_source_file=True,
        document_fast_path=True,
    )

    queued = llm_queue.get_nowait()
    progress = manager.get_task_by_id(task["task_id"])["progress"]
    assert result["status"] == "success"
    assert manager.get_task_by_id(task["task_id"])["status"] == "calibrating"
    assert queued["document_quality"]["mode"] == "fallback"
    assert "low_printable_ratio" in queued["document_quality"]["reasons"]
    assert "canonical_text" not in queued["document_quality"]
    assert "document_quality" in progress["evidence"]
    assert len(repr(progress["evidence"])) < 2000


def test_visual_fast_path_excludes_non_visual_and_non_whitelisted_documents(monkeypatch, tmp_path):
    import queue

    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr(transcription, "cache_manager", manager)
    monkeypatch.setattr(transcription, "_extract_document_text", lambda *_: "正文" * 200)

    for index, (filename, fast_flag) in enumerate(
        [("guide.pdf", False), ("data.csv", True), ("events.log", True)]
    ):
        media_id = f"legacy-{index}"
        task = manager.create_task(
            url=f"local://study-source/{media_id}/{filename}",
            platform="generic",
            media_id=media_id,
        )
        source = tmp_path / filename
        source.write_text("source", encoding="utf-8")
        llm_queue = queue.Queue()
        monkeypatch.setattr(transcription, "llm_task_queue", llm_queue)
        transcription.process_local_upload(
            task["task_id"],
            str(source),
            filename,
            f"local://study-source/{media_id}/{filename}",
            media_id,
            preserve_source_file=True,
            document_fast_path=fast_flag,
        )
        assert not llm_queue.empty()
