from pathlib import Path
from typing import Optional

from ..cache.cache_manager import CacheManager
from .repository import StudyRepository
from .source_files import find_study_source_file
from .transcript import normalize_transcript


class StudyService:
    """Builds local study-mode read models from existing task/cache data."""

    def __init__(
        self,
        cache_manager: CacheManager,
        repository: StudyRepository,
        source_root: str | Path,
    ):
        self.cache_manager = cache_manager
        self.repository = repository
        self.source_root = Path(source_root)

    def get_session(self, view_token: str) -> Optional[dict]:
        view_data = self.cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            return None

        task_info = self.cache_manager.get_task_by_view_token(view_token) or {}
        status = task_info.get("status") or view_data.get("status")
        source_file = self.get_source_file(view_token)
        source_available = source_file is not None
        progress = task_info.get("progress") or view_data.get("progress") or {}
        state = self._state_for(status, source_available, progress)
        transcript_source = self._transcript_source(view_token, view_data)

        return {
            "state": state,
            "metadata": {
                "task_id": view_data.get("task_id"),
                "view_token": view_token,
                "title": view_data.get("title") or "",
                "author": view_data.get("author") or "",
                "platform": view_data.get("platform") or "",
                "media_id": view_data.get("media_id") or "",
                "created_at": view_data.get("created_at"),
                "completed_at": view_data.get("completed_at"),
                "message": view_data.get("message") or "",
            },
            "playback": {
                "source_available": source_available,
                "source_url": f"/api/study/{view_token}/source-file" if source_available else "",
                "unavailable_reason": "" if source_available else "源视频未保存或已清理",
            },
            "transcript": {
                "lines": normalize_transcript(transcript_source),
            },
            "ai": {
                "overview": view_data.get("summary") or "",
                "summary_missing": bool(view_data.get("summary_missing")),
            },
            "notes": self.repository.list_notes(view_token),
            "progress": progress,
        }

    def get_source_file(self, view_token: str) -> Optional[Path]:
        view_data = self.cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            return None
        return find_study_source_file(
            source_root=self.source_root,
            media_id=view_data.get("media_id") or "",
            title=view_data.get("title") or "",
            url=view_data.get("url") or "",
        )

    def create_note(self, view_token: str, time_seconds, body: str) -> dict:
        return self.repository.create_note(view_token, time_seconds, body)

    def update_note(self, view_token: str, note_id: str, time_seconds, body: str):
        return self.repository.update_note(note_id, view_token, body, time_seconds)

    def delete_note(self, view_token: str, note_id: str) -> bool:
        return self.repository.delete_note(note_id, view_token)

    def export_markdown(self, view_token: str) -> Optional[str]:
        session = self.get_session(view_token)
        if not session:
            return None

        metadata = session.get("metadata") or {}
        ai = session.get("ai") or {}
        transcript = session.get("transcript") or {}
        notes = session.get("notes") or []

        title = metadata.get("title") or "本地视频学习笔记"
        lines = [
            f"# {title}",
            "",
            "## AI 看",
            ai.get("overview") or "暂无 AI 总结。",
            "",
            "## 文稿",
        ]

        transcript_lines = transcript.get("lines") or []
        if transcript_lines:
            for line in transcript_lines:
                text = line.get("text") or ""
                if line.get("seekable"):
                    lines.append(f"- [{self._format_timestamp(line.get('start_seconds'))}] {text}")
                else:
                    lines.append(f"- {text}")
        else:
            lines.append("暂无文稿。")

        lines.extend(["", "## 我的笔记"])
        if notes:
            for note in notes:
                body = note.get("body") or ""
                time_seconds = note.get("time_seconds")
                if time_seconds is None:
                    lines.append(f"- {body}")
                else:
                    lines.append(f"- [{self._format_timestamp(time_seconds)}] {body}")
        else:
            lines.append("暂无笔记。")

        return "\n".join(lines).strip() + "\n"

    def _transcript_source(self, view_token: str, view_data: dict):
        cache_data = self.cache_manager.get_cache_by_view_token(view_token)
        if cache_data and cache_data.get("transcript_data") is not None:
            return cache_data.get("transcript_data")
        return view_data.get("transcript") or ""

    @staticmethod
    def _state_for(status: str, source_available: bool, progress: Optional[dict] = None) -> str:
        if status == "success":
            return "ready" if source_available else "source_missing"
        if status == "failed":
            return "failed"
        if status == "canceled":
            return "canceled"
        if status == "calibrating":
            return "generating_ai"
        stage = (progress or {}).get("stage")
        if stage in {"downloading", "transcribing"}:
            return stage
        if status == "queued":
            return "queued"
        if status == "processing":
            return "processing"
        return status or "unknown"

    @staticmethod
    def _format_timestamp(seconds) -> str:
        if seconds is None:
            return "--:--"
        total = max(0, int(float(seconds)))
        hours = total // 3600
        minutes = (total % 3600) // 60
        remaining = total % 60
        if hours:
            return f"{hours}:{minutes:02d}:{remaining:02d}"
        return f"{minutes:02d}:{remaining:02d}"
