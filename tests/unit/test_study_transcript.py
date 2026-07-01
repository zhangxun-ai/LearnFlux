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
