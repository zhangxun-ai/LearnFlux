"""Unit tests for the export-file-path resolution helper in views.

All console output must be in English only (no emoji, no Chinese).
"""

from pathlib import Path

from video_transcript_api.api.routes.views import resolve_export_file_path


class TestResolveExportFilePath:
    def test_calibrated(self, tmp_path):
        p = resolve_export_file_path(str(tmp_path), "calibrated")
        assert p == tmp_path / "llm_calibrated.txt"

    def test_summary(self, tmp_path):
        p = resolve_export_file_path(str(tmp_path), "summary")
        assert p == tmp_path / "llm_summary.txt"

    def test_comment_insight(self, tmp_path):
        p = resolve_export_file_path(str(tmp_path), "comment_insight")
        assert p == tmp_path / "comment_insight.txt"

    def test_transcript_prefers_funasr_when_present(self, tmp_path):
        (tmp_path / "transcript_funasr.json").write_text("{}", encoding="utf-8")
        p = resolve_export_file_path(str(tmp_path), "transcript")
        assert p == tmp_path / "transcript_funasr.json"

    def test_transcript_falls_back_to_capswriter(self, tmp_path):
        # No funasr file present -> capswriter path (even if it doesn't exist yet).
        p = resolve_export_file_path(str(tmp_path), "transcript")
        assert p == tmp_path / "transcript_capswriter.txt"

    def test_unsupported_returns_none(self, tmp_path):
        assert resolve_export_file_path(str(tmp_path), "bogus") is None
