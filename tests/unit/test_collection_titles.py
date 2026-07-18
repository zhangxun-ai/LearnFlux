from video_transcript_api.collections.titles import (
    source_basename,
    source_display_title,
)


def test_source_basename_removes_browser_folder_paths():
    assert source_basename("课程目录/第01课.mp3") == "第01课.mp3"
    assert source_basename(r"课程目录\第02课.mp4") == "第02课.mp4"


def test_source_display_title_hides_supported_file_extensions_only():
    assert source_display_title("课程目录/第01课.MP3") == "第01课"
    assert source_display_title("资料目录/学习指南.pdf") == "学习指南"
    assert source_display_title("课程版本.v2") == "课程版本.v2"
