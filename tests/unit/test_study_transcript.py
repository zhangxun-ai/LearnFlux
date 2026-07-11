def test_normalize_plain_transcript_returns_untimed_lines():
    from video_transcript_api.study.transcript import normalize_transcript

    lines = normalize_transcript("第一段内容。\n\n第二段内容。")

    assert [line["text"] for line in lines] == ["第一段内容。", "第二段内容。"]
    assert all(line["start_seconds"] is None for line in lines)
    assert all(line["seekable"] is False for line in lines)


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


def test_local_upload_preserves_structured_transcript_cache(monkeypatch, tmp_path):
    import queue

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

    cached = cache_manager.get_cache(platform="generic", media_id=media_id)
    cache_manager.close()

    assert result["status"] == "success"
    assert cached is not None
    assert cached["transcript_type"] == "funasr"
    lines = normalize_transcript(cached["transcript_data"])
    assert [line["start_seconds"] for line in lines] == [0.0, 1.5]


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
