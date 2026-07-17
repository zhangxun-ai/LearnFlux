from pathlib import Path
from typing import Any, Callable, Optional

from ..cache.cache_manager import CacheManager
from ..llm import call_llm_api
from .repository import StudyRepository
from .source_files import describe_study_source, find_study_source_file
from .transcript import normalize_transcript

_DEFAULT_STUDY_CHAT_MODEL = "deepseek-v4-pro"
_DEFAULT_STUDY_CHAT_REASONING_EFFORT = "high"


class StudyService:
    """Builds local study-mode read models from existing task/cache data."""

    def __init__(
        self,
        cache_manager: CacheManager,
        repository: StudyRepository,
        source_root: str | Path,
        llm_config: Optional[dict] = None,
        llm_answerer: Optional[Callable[..., str]] = None,
    ):
        self.cache_manager = cache_manager
        self.repository = repository
        self.source_root = Path(source_root)
        self.llm_config = llm_config or {}
        self.llm_answerer = llm_answerer or call_llm_api

    def get_session(self, view_token: str) -> Optional[dict]:
        view_data = self.cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            return None

        task_info = self.cache_manager.get_task_by_view_token(view_token) or {}
        status = task_info.get("status") or view_data.get("status")
        source_file = self.get_source_file(view_token)
        source_available = source_file is not None
        progress = task_info.get("progress") or view_data.get("progress") or {}
        progress_evidence = progress.get("evidence") or {}
        state = self._state_for(status, source_available, progress)
        transcript_source = self._transcript_source(view_token, view_data)
        source_url = f"/api/study/{view_token}/source-file" if source_available else ""
        source = describe_study_source(
            url=view_data.get("url") or "",
            title=view_data.get("title") or "",
            source_file=source_file,
            media_type=view_data.get("source_media_type") or "",
            media_kind=view_data.get("media_type") or "",
        )
        source["original_url"] = source_url

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
                "source_url": source_url,
                "unavailable_reason": "" if source_available else "源视频未保存或已清理",
            },
            "source": source,
            "transcript": {
                "lines": normalize_transcript(transcript_source),
            },
            "ai": {
                "overview": view_data.get("summary") or "",
                "summary_missing": bool(view_data.get("summary_missing")),
                "chat_model": self._study_chat_model(),
            },
            "analysis": {
                "mode": progress_evidence.get("analysis_mode") or "legacy",
                "visual_ready": bool(progress_evidence.get("visual_ready")),
                "quality": progress_evidence.get("quality") or {},
            },
            "notes": self.repository.list_notes(view_token),
            "progress": progress,
        }

    def get_source_file(self, view_token: str) -> Optional[Path]:
        view_data = self.cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            return None
        task_info = self.cache_manager.get_task_by_view_token(view_token) or {}
        return find_study_source_file(
            source_root=self.source_root,
            media_id=view_data.get("media_id") or "",
            title=view_data.get("title") or "",
            url=view_data.get("url") or "",
            source_file_path=task_info.get("source_file_path") or "",
        )

    def get_collection_session(
        self,
        view_token: str,
        *,
        owner_user_id: str,
        collection_id: str,
        source_id: str,
    ) -> Optional[dict]:
        session = self.get_session(view_token)
        if not session:
            return None
        session["notes"] = self.repository.list_notes(
            view_token,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )
        return session

    def create_note(self, view_token: str, time_seconds, body: str) -> dict:
        return self.repository.create_note(view_token, time_seconds, body)

    def update_note(self, view_token: str, note_id: str, time_seconds, body: str):
        return self.repository.update_note(note_id, view_token, body, time_seconds)

    def delete_note(self, view_token: str, note_id: str) -> bool:
        return self.repository.delete_note(note_id, view_token)

    def create_collection_note(
        self,
        view_token: str,
        time_seconds,
        body: str,
        *,
        owner_user_id: str,
        collection_id: str,
        source_id: str,
    ) -> dict:
        return self.repository.create_note(
            view_token,
            time_seconds,
            body,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )

    def update_collection_note(
        self,
        view_token: str,
        note_id: str,
        time_seconds,
        body: str,
        *,
        owner_user_id: str,
        collection_id: str,
        source_id: str,
    ):
        return self.repository.update_note(
            note_id,
            view_token,
            body,
            time_seconds,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )

    def delete_collection_note(
        self,
        view_token: str,
        note_id: str,
        *,
        owner_user_id: str,
        collection_id: str,
        source_id: str,
    ) -> bool:
        return self.repository.delete_note(
            note_id,
            view_token,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )

    def ask_ai(
        self,
        view_token: str,
        question: str,
        time_seconds=None,
        history: Optional[list[dict[str, str]]] = None,
    ) -> Optional[dict[str, Any]]:
        session = self.get_session(view_token)
        if not session:
            return None

        clean_question = (question or "").strip()
        if not clean_question:
            raise ValueError("question is required")

        prompt = self._build_chat_prompt(session, clean_question, time_seconds, history or [])
        if not prompt:
            raise ValueError("当前学习内容还没有可供 AI 参考的文稿")

        model = self._study_chat_model()
        reasoning_effort = self.llm_config.get("study_chat_reasoning_effort")
        if reasoning_effort is None:
            reasoning_effort = _DEFAULT_STUDY_CHAT_REASONING_EFFORT

        answer = self.llm_answerer(
            model=model,
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            task_type="study_chat",
            system_prompt=(
                "你是专业、严谨的中文视频学习助教。回答必须优先基于给定视频上下文；"
                "可以补充相关领域的专业知识，但要明确区分“视频中提到”和“背景补充”。"
                "如果上下文不足以支持结论，直接说明不足，不要编造。"
            ),
        )
        return {
            "answer": str(answer).strip(),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "time_seconds": time_seconds,
        }

    def export_markdown(self, view_token: str) -> Optional[str]:
        session = self.get_session(view_token)
        if not session:
            return None

        return self._export_session_markdown(session)

    def export_collection_markdown(
        self,
        view_token: str,
        *,
        owner_user_id: str,
        collection_id: str,
        source_id: str,
    ) -> Optional[str]:
        session = self.get_collection_session(
            view_token,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )
        if not session:
            return None
        return self._export_session_markdown(session)

    def _export_session_markdown(self, session: dict) -> str:

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

    def _build_chat_prompt(
        self,
        session: dict,
        question: str,
        time_seconds,
        history: list[dict[str, str]],
    ) -> str:
        metadata = session.get("metadata") or {}
        ai = session.get("ai") or {}
        lines = ((session.get("transcript") or {}).get("lines")) or []
        summary = (ai.get("overview") or "").strip()
        transcript = self._format_transcript_for_prompt(lines)
        if not summary and not transcript:
            return ""

        nearby = self._nearby_transcript(lines, time_seconds)
        history_block = self._format_chat_history(history)
        time_block = ""
        if time_seconds is not None:
            time_block = (
                f"\n用户选择参考的播放位置：{self._format_timestamp(time_seconds)}\n"
                f"该位置附近文稿：\n{nearby or '未找到可定位文稿'}\n"
            )

        return f"""请回答用户关于这个视频的问题。

视频标题：{metadata.get("title") or "未命名视频"}

用户问题：
{question}
{time_block}
最近对话：
{history_block or "无"}

视频 AI 总结：
{self._clip_text(summary, 12000) or "无"}

视频全文文稿：
{transcript}

回答要求：
1. 先直接回答问题。
2. 引用视频上下文中的关键依据，不要只泛泛解释。
3. 需要专业背景时可以补充，但要标明这是背景补充。
4. 如果用户的问题和视频内容关系不明确，先说明你基于哪个理解来回答。
5. 使用中文，结构清晰，避免空泛套话。
6. 不要输出 Markdown 分隔线、引用前缀符号、代码块或表格；可以使用简短小标题和短段落。
"""

    def _format_transcript_for_prompt(self, lines: list[dict]) -> str:
        entries = []
        for line in lines:
            text = (line.get("text") or "").strip()
            if not text:
                continue
            if line.get("seekable"):
                entries.append(f"[{self._format_timestamp(line.get('start_seconds'))}] {text}")
            else:
                entries.append(text)
        return self._clip_text("\n".join(entries), 60000)

    def _nearby_transcript(self, lines: list[dict], time_seconds) -> str:
        if time_seconds is None:
            return ""
        try:
            target = float(time_seconds)
        except (TypeError, ValueError):
            return ""

        seekable = [
            (index, line)
            for index, line in enumerate(lines)
            if line.get("seekable") and line.get("start_seconds") is not None
        ]
        if not seekable:
            return ""

        active_index = seekable[0][0]
        for index, line in seekable:
            if float(line.get("start_seconds") or 0) <= target:
                active_index = index
            else:
                break

        start = max(0, active_index - 5)
        end = min(len(lines), active_index + 8)
        return "\n".join(
            f"[{self._format_timestamp(line.get('start_seconds'))}] {line.get('text') or ''}"
            if line.get("seekable")
            else (line.get("text") or "")
            for line in lines[start:end]
            if (line.get("text") or "").strip()
        )

    def _format_chat_history(self, history: list[dict[str, str]]) -> str:
        rows = []
        for item in history[-8:]:
            role = "用户" if item.get("role") == "user" else "AI"
            content = self._clip_text((item.get("content") or "").strip(), 1000)
            if content:
                rows.append(f"{role}: {content}")
        return "\n".join(rows)

    def _study_chat_model(self) -> str:
        return self.llm_config.get("study_chat_model") or _DEFAULT_STUDY_CHAT_MODEL

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[已截断]"

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
