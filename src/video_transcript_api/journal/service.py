import calendar
from datetime import date
from typing import Any, Callable

from ..llm import call_llm_api
from .repository import JournalRepository

ENTRY_TYPES = {
    "daily": "日记",
    "note": "随笔",
    "weekly_plan": "周计划",
    "weekly_review": "周复盘",
    "monthly_plan": "月计划",
    "monthly_review": "月复盘",
}

_DEFAULT_REVIEW_MODEL = "deepseek-v4-pro"
_DEFAULT_REVIEW_REASONING_EFFORT = "high"


class JournalService:
    """Coordinates journal persistence and AI review prompts."""

    def __init__(
        self,
        repository: JournalRepository,
        llm_config: dict | None = None,
        llm_answerer: Callable[..., str] | None = None,
    ):
        self.repository = repository
        self.llm_config = llm_config or {}
        self.llm_answerer = llm_answerer or call_llm_api

    def save_entry(
        self,
        user_id: str,
        entry_date: str,
        entry_type: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        clean_date = self._parse_date(entry_date).isoformat()
        clean_type = self._normalize_entry_type(entry_type)
        return self.repository.upsert_entry(
            user_id=user_id,
            entry_date=clean_date,
            entry_type=clean_type,
            title=title or self._default_title(clean_date, clean_type, body),
            body=body or "",
        )

    def get_entry(
        self,
        user_id: str,
        entry_date: str,
        entry_type: str,
    ) -> dict[str, Any] | None:
        clean_date = self._parse_date(entry_date).isoformat()
        clean_type = self._normalize_entry_type(entry_type)
        return self.repository.get_entry(user_id, clean_date, clean_type)

    def list_entries(
        self,
        user_id: str,
        month: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        entry_type: str | None = None,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        start = self._parse_date(start_date).isoformat() if start_date else None
        end = self._parse_date(end_date).isoformat() if end_date else None
        if month and not (start or end):
            start, end = self._month_bounds(month)
        clean_type = self._normalize_entry_type(entry_type) if entry_type else None
        return self.repository.list_entries(user_id, start, end, clean_type, limit)

    def list_reviews(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.list_reviews(user_id, limit=limit)

    def review(
        self,
        user_id: str,
        range_start: str,
        range_end: str,
        question: str,
    ) -> dict[str, Any]:
        start = self._parse_date(range_start).isoformat()
        end = self._parse_date(range_end).isoformat()
        if start > end:
            start, end = end, start

        entries = self.repository.list_entries(
            user_id=user_id,
            start_date=start,
            end_date=end,
            limit=120,
        )
        prompt = self._build_review_prompt(entries, start, end, question)
        if not prompt:
            raise ValueError("这段时间还没有可复盘的记录")

        model = self._review_model()
        reasoning_effort = self._review_reasoning_effort()
        answer = self.llm_answerer(
            model=model,
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            task_type="journal_review",
            system_prompt=(
                "你是克制、严谨的中文个人复盘助手。你只能基于用户记录和用户问题分析，"
                "不要编造没有记录支撑的事实。输出要具体、可执行，避免空泛鼓励。"
            ),
        )
        return self.repository.create_review(
            user_id=user_id,
            range_start=start,
            range_end=end,
            question=(question or "").strip(),
            answer=str(answer).strip(),
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def _build_review_prompt(
        self,
        entries: list[dict[str, Any]],
        range_start: str,
        range_end: str,
        question: str,
    ) -> str:
        clean_question = (question or "").strip()
        blocks = []
        for entry in sorted(entries, key=lambda item: item.get("entry_date") or ""):
            body = (entry.get("body") or "").strip()
            if not body:
                continue
            entry_type = ENTRY_TYPES.get(entry.get("entry_type"), entry.get("entry_type"))
            title = (entry.get("title") or "").strip()
            heading = f"{entry.get('entry_date')} · {entry_type}"
            if title:
                heading += f" · {title}"
            blocks.append(f"### {heading}\n{body}")

        if not blocks and not clean_question:
            return ""

        records = self._clip_text("\n\n".join(blocks), 60000) or "这段时间没有正文记录。"
        return f"""请基于下面的个人记录做复盘。

时间范围：{range_start} 至 {range_end}

用户这次想问：
{clean_question or "请帮我总结这段时间真正发生了什么、反复出现的问题，以及下一步最值得保留的动作。"}

记录：
{records}

回答要求：
1. 先给出 3-5 条最重要的观察，每条必须能回到记录中的事实。
2. 区分“推进顺利的事”“卡住的地方”“下阶段建议保留/砍掉的动作”。
3. 如果记录不足，直接指出缺口，并建议以后怎么记录更有利于复盘。
4. 不要做宏大规划，不要列太多项；保持安静、具体、可执行。
5. 使用中文。
"""

    def _review_model(self) -> str:
        return (
            self.llm_config.get("journal_review_model")
            or self.llm_config.get("study_chat_model")
            or self.llm_config.get("summary_model")
            or _DEFAULT_REVIEW_MODEL
        )

    def _review_reasoning_effort(self) -> str | None:
        value = self.llm_config.get("journal_review_reasoning_effort")
        if value is None:
            value = self.llm_config.get("study_chat_reasoning_effort")
        if value is None:
            value = _DEFAULT_REVIEW_REASONING_EFFORT
        return value

    def _normalize_entry_type(self, value: str | None) -> str:
        entry_type = (value or "daily").strip()
        if entry_type not in ENTRY_TYPES:
            raise ValueError("unsupported journal entry type")
        return entry_type

    def _parse_date(self, value: str | None) -> date:
        if not value:
            return date.today()
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD") from exc

    def _month_bounds(self, month: str) -> tuple[str, str]:
        try:
            year_text, month_text = month.split("-", 1)
            year = int(year_text)
            month_num = int(month_text)
            last_day = calendar.monthrange(year, month_num)[1]
        except Exception as exc:
            raise ValueError("month must use YYYY-MM") from exc
        return f"{year:04d}-{month_num:02d}-01", f"{year:04d}-{month_num:02d}-{last_day:02d}"

    def _default_title(self, entry_date: str, entry_type: str, body: str) -> str:
        first_line = next((line.strip() for line in (body or "").splitlines() if line.strip()), "")
        if first_line:
            return first_line[:80]
        return f"{entry_date} {ENTRY_TYPES.get(entry_type, entry_type)}"

    def _clip_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n\n[记录过长，已截断]"
