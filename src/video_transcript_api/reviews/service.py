"""Application service for review records, aggregation, AI, and sync."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from ..utils.timeutil.timezone_helper import get_configured_timezone
from .ai import ReviewAIAnalyzer
from .obsidian import ReviewObsidianSyncService
from .periods import month_period, parse_date, week_period, year_period
from .repository import ReviewDataError, ReviewRepository


class ReviewService:
    """Coordinate owner-scoped review flows without web framework dependencies."""

    def __init__(
        self,
        repository: ReviewRepository,
        config: Mapping[str, Any] | None = None,
        *,
        ai_analyzer: ReviewAIAnalyzer | None = None,
        sync_service: ReviewObsidianSyncService | None = None,
    ) -> None:
        self.repository = repository
        self.config = dict(config or {})
        self.ai = ai_analyzer or ReviewAIAnalyzer(repository, self.config)
        self.syncer = sync_service or ReviewObsidianSyncService(repository, self.config)

    def close(self) -> None:
        self.repository.close()

    @staticmethod
    def _sync_response(record: dict[str, Any], sync: dict[str, Any]) -> dict[str, Any]:
        return {"record": record, "sync": sync}

    @staticmethod
    def _typed_source(source_type: str, record: Mapping[str, Any]) -> dict[str, str]:
        return {
            "type": source_type,
            "id": str(record["id"]),
            "date": str(
                record.get("review_date")
                or record.get("week_start")
                or record.get("month_key")
                or record.get("year_key")
                or ""
            ),
            "label": str(
                record.get("title")
                or record.get("statement")
                or record.get("month_key")
                or record.get("week_start")
                or record.get("year_key")
                or record["id"]
            ),
        }

    def _sync_related_daily_sources(
        self, user_id: str, raw_sources: list[Any]
    ) -> None:
        if not self.syncer.configuration_status()["configured"]:
            return
        synced_dates: set[str] = set()
        for raw in raw_sources:
            reference = raw if isinstance(raw, Mapping) else {"type": "daily", "id": raw}
            if str(reference.get("type") or reference.get("source_type") or "daily") != "daily":
                continue
            source_id = str(reference.get("id") or reference.get("source_id") or "")
            source = self.repository.source(user_id, "daily", source_id) if source_id else None
            review_date = str((source or {}).get("review_date") or "")
            if source and review_date not in synced_dates:
                self.syncer.sync(user_id, "daily", source["id"])
                synced_dates.add(review_date)

    def create_insight(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = dict(payload)
        evidence = [dict(item) if isinstance(item, Mapping) else {"text": str(item)} for item in clean.get("evidence") or []]
        counter = [dict(item) if isinstance(item, Mapping) else {"text": str(item)} for item in clean.get("counter_evidence") or []]
        source_refs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in clean.get("source_ids") or []:
            ref = raw if isinstance(raw, Mapping) else {"type": "daily", "id": raw}
            source_type = str(ref.get("type") or ref.get("source_type") or "daily")
            source_id = str(ref.get("id") or ref.get("source_id") or "")
            if source_id and (source_type, source_id) not in seen:
                source = self.repository.source(user_id, source_type, source_id)
                if source is None:
                    raise ReviewDataError("insight source does not exist for this user")
                source_refs.append(self._typed_source(source_type, source))
                seen.add((source_type, source_id))
        for entry in evidence:
            source_id = str(entry.get("source_id") or "")
            source_type = str(entry.get("source_type") or "daily")
            if not source_id or (source_type, source_id) in seen:
                continue
            source = self.repository.source(user_id, source_type, source_id)
            if source is None:
                raise ReviewDataError("insight evidence source does not exist for this user")
            source_refs.append(self._typed_source(source_type, source))
            seen.add((source_type, source_id))
        dates = sorted(
            {
                str(entry.get("record_date") or entry.get("date") or ref.get("date") or "")
                for entry in evidence
                for ref in [next((item for item in source_refs if item["id"] == str(entry.get("source_id") or "")), {})]
                if str(entry.get("record_date") or entry.get("date") or ref.get("date") or "")
            }
        )
        span_days = 0
        if dates:
            try:
                span_days = (date.fromisoformat(dates[-1][:10]) - date.fromisoformat(dates[0][:10])).days + 1
            except ValueError:
                span_days = 0
        independent = len(source_refs)
        strength_label = "证据较少"
        if independent >= 2 and span_days >= 7:
            strength_label = "正在形成"
        if independent >= 4 and span_days >= 21:
            strength_label = "跨周期重复"
        clean.update(
            {
                "evidence": evidence,
                "counter_evidence": counter,
                "source_ids": source_refs,
                "evidence_span": clean.get("evidence_span") or {
                    "start": dates[0] if dates else None,
                    "end": dates[-1] if dates else None,
                    "days": span_days,
                },
                "evidence_strength": clean.get("evidence_strength") or {
                    "label": strength_label,
                    "independent_sources": independent,
                    "source_types": sorted({item["type"] for item in source_refs}),
                    "counter_evidence": len(counter),
                },
            }
        )
        return self.repository.create_insight(user_id, clean)

    def today(self) -> str:
        return datetime.now(get_configured_timezone()).date().isoformat()

    def daily(self, user_id: str, review_date: str | None = None) -> dict[str, Any]:
        target = parse_date(review_date, default=parse_date(self.today())).isoformat()
        items = self.repository.list_daily_events(user_id, review_date=target, limit=500)
        states = {
            item["record_id"]: item
            for item in self.repository.list_sync_states(user_id, limit=500)
            if item["record_type"] == "daily"
        }
        return {
            "date": target,
            "items": [{**item, "sync": states.get(item["id"])} for item in items],
            "total": len(items),
        }

    def create_daily(self, user_id: str, review_date: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean_date = parse_date(review_date).isoformat()
        record = self.repository.create_daily_event(user_id, clean_date, payload)
        return self._sync_response(record, self.syncer.sync(user_id, "daily", record["id"]))

    def update_daily(self, user_id: str, event_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if "review_date" in payload:
            payload = {**payload, "review_date": parse_date(str(payload["review_date"])).isoformat()}
        record = self.repository.update_daily_event(user_id, event_id, payload)
        if record is None:
            return None
        return self._sync_response(record, self.syncer.sync(user_id, "daily", event_id))

    def duplicate_daily(self, user_id: str, event_id: str) -> dict[str, Any] | None:
        record = self.repository.duplicate_daily_event(user_id, event_id)
        if record is None:
            return None
        return self._sync_response(record, self.syncer.sync(user_id, "daily", record["id"]))

    def weekly(self, user_id: str, anchor: str | None = None) -> dict[str, Any]:
        preferences = self.repository.get_preferences(user_id)
        target = parse_date(anchor, default=parse_date(self.today()))
        period = week_period(target, week_start_day=preferences["week_start_day"])
        start, end = period.start.isoformat(), period.end.isoformat()
        daily = self.repository.list_daily_events(user_id, start_date=start, end_date=end, limit=500)
        experiments = [
            item
            for item in self.repository.list_experiments(user_id)
            if item.get("period_key") == start
            or (
                str(item.get("period_key") or "") < start
                and item.get("status") not in {"completed", "stopped"}
            )
        ]
        return {
            "period": period.as_dict(),
            "record": self.repository.get_weekly(user_id, start),
            "daily_events": daily,
            "connections": self.repository.list_connections(user_id, period_type="weekly", period_key=start),
            "experiments": experiments,
        }

    def save_weekly(self, user_id: str, anchor: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        preferences = self.repository.get_preferences(user_id)
        period = week_period(parse_date(anchor), week_start_day=preferences["week_start_day"])
        start, end = period.start.isoformat(), period.end.isoformat()
        clean = dict(payload)
        if "source_ids" not in clean:
            clean["source_ids"] = [
                self._typed_source("daily", item)
                for item in self.repository.list_daily_events(
                    user_id, start_date=start, end_date=end, limit=500
                )
            ]
        record = self.repository.upsert_weekly(user_id, start, end, clean)
        sync = self.syncer.sync(user_id, "weekly", record["id"])
        self._sync_related_daily_sources(user_id, clean.get("source_ids") or [])
        return self._sync_response(record, sync)

    def monthly(self, user_id: str, month: str | None = None) -> dict[str, Any]:
        target = month or self.today()[:7]
        period = month_period(target)
        month_key = period.start.strftime("%Y-%m")
        return {
            "period": period.as_dict(),
            "record": self.repository.get_monthly(user_id, month_key),
            "daily_events": self.repository.list_daily_events(
                user_id, start_date=period.start.isoformat(), end_date=period.end.isoformat(), limit=500
            ),
            "weekly_reviews": self.repository.list_weekly(user_id, year=month_key[:4], limit=60),
            "monthly_reviews": self.repository.list_monthly(user_id, limit=24),
            "connections": self.repository.list_connections(
                user_id, period_type="monthly", period_key=month_key[:4]
            ),
        }

    def save_monthly(self, user_id: str, month: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        period = month_period(month)
        month_key = period.start.strftime("%Y-%m")
        clean = dict(payload)
        if "source_ids" not in clean:
            daily_sources = [
                self._typed_source("daily", item)
                for item in self.repository.list_daily_events(
                    user_id,
                    start_date=period.start.isoformat(),
                    end_date=period.end.isoformat(),
                    limit=500,
                )
            ]
            weekly_sources = [
                self._typed_source("weekly", item)
                for item in self.repository.list_weekly(user_id, year=month_key[:4], limit=60)
                if item["week_start"] <= period.end.isoformat()
                and item["week_end"] >= period.start.isoformat()
            ]
            clean["source_ids"] = daily_sources + weekly_sources
        record = self.repository.upsert_monthly(user_id, month_key, clean)
        sync = self.syncer.sync(user_id, "monthly", record["id"])
        self._sync_related_daily_sources(user_id, clean.get("source_ids") or [])
        return self._sync_response(record, sync)

    def create_experiment(
        self, user_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        record = self.repository.create_experiment(user_id, payload)
        sync = self.syncer.sync(user_id, "experiment", record["id"])
        self._sync_related_daily_sources(user_id, record.get("source_ids") or [])
        return self._sync_response(record, sync)

    def update_experiment(
        self, user_id: str, experiment_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        record = self.repository.update_experiment(user_id, experiment_id, payload)
        if record is None:
            return None
        sync = self.syncer.sync(user_id, "experiment", record["id"])
        self._sync_related_daily_sources(user_id, record.get("source_ids") or [])
        return self._sync_response(record, sync)

    def delete_experiment(self, user_id: str, experiment_id: str) -> bool:
        record = self.repository.get_experiment(user_id, experiment_id)
        if record is None or not self.repository.delete_experiment(user_id, experiment_id):
            return False
        self._sync_related_daily_sources(user_id, record.get("source_ids") or [])
        return True

    def annual(self, user_id: str, year: str | int | None = None) -> dict[str, Any]:
        year_key = str(year or self.today()[:4])
        period = year_period(year_key)
        months_by_key = {
            item["month_key"]: item for item in self.repository.list_monthly(user_id, year=year_key, limit=12)
        }
        months = []
        for month_number in range(1, 13):
            key = f"{int(year_key):04d}-{month_number:02d}"
            months.append(months_by_key.get(key) or {
                "month_key": key, "inner": [], "actions": [], "results": [], "notes": [],
                "cross_month": [], "affirmation": "", "source_ids": [], "status": "empty",
            })
        candidates = []
        for item in self.repository.list_ai_candidates(
            user_id, analysis_type="annual_summary", limit=100
        ):
            source_years = set()
            for reference in item.get("scope") or []:
                if reference.get("type") != "monthly":
                    continue
                source = self.repository.source(
                    user_id, "monthly", str(reference.get("id") or "")
                )
                if source:
                    source_years.add(str(source.get("month_key") or "")[:4])
            if year_key in source_years:
                candidates.append(item)
        return {
            "period": period.as_dict(),
            "record": self.repository.get_annual(user_id, year_key),
            "months": months,
            "connections": self.repository.list_connections(
                user_id, period_type="monthly", period_key=year_key
            ),
            "ai_candidates": candidates,
        }

    def save_annual(self, user_id: str, year: str | int, payload: Mapping[str, Any]) -> dict[str, Any]:
        year_key = str(year_period(year).start.year)
        clean = dict(payload)
        if "source_ids" not in clean:
            clean["source_ids"] = [
                self._typed_source("monthly", item)
                for item in self.repository.list_monthly(user_id, year=year_key, limit=12)
            ]
        record = self.repository.upsert_annual(user_id, year_key, clean)
        return self._sync_response(record, self.syncer.sync(user_id, "annual", record["id"]))

    def source_trace(self, user_id: str, source_type: str, source_id: str) -> dict[str, Any] | None:
        record = self.repository.source(user_id, source_type, source_id)
        if record is None:
            return None
        source_ids = record.get("source_ids") or []
        resolved = []
        for raw in source_ids[:50]:
            reference = raw if isinstance(raw, dict) else {"type": "daily", "id": raw}
            child_type = str(reference.get("type") or "daily")
            child_id = str(reference.get("id") or reference.get("source_id") or "")
            child = self.repository.source(user_id, child_type, child_id) if child_id else None
            resolved.append({"type": child_type, "id": child_id, "record": child})
        return {"type": source_type, "record": record, "sources": resolved}

    def confirm_ai(
        self,
        user_id: str,
        candidate_id: str,
        content: Mapping[str, Any] | None = None,
        *,
        create_insight: bool = False,
    ) -> dict[str, Any] | None:
        candidate = self.repository.get_ai_candidate(user_id, candidate_id)
        if candidate is None or candidate["status"] != "candidate":
            return None
        chosen = dict(content or candidate["candidate"])
        confirmed = self.repository.confirm_ai_candidate(user_id, candidate_id, chosen)
        if confirmed is None:
            return None
        insight = None
        applied_to = None
        if candidate.get("analysis_type") == "annual_summary":
            monthly_sources = []
            for reference in candidate.get("scope") or []:
                if reference.get("type") != "monthly":
                    continue
                source = self.repository.source(
                    user_id, "monthly", str(reference.get("id") or "")
                )
                if source:
                    monthly_sources.append(source)
            years = {str(item.get("month_key") or "")[:4] for item in monthly_sources}
            if len(years) == 1:
                year_key = years.pop()
                current = self.repository.get_annual(user_id, year_key) or {}
                statement = str(chosen.get("statement") or "").strip()
                existing_summary = str(current.get("summary") or "").strip()
                summary = existing_summary
                if statement and statement not in existing_summary:
                    summary = f"{existing_summary}\n- {statement}".strip()
                annual = self.repository.upsert_annual(
                    user_id,
                    year_key,
                    {
                        "keywords": current.get("keywords") or [],
                        "summary": summary,
                        "cross_month": current.get("cross_month") or [],
                        "source_ids": [
                            self._typed_source("monthly", source)
                            for source in monthly_sources
                        ],
                        "status": "active",
                    },
                )
                self.syncer.sync(user_id, "annual", annual["id"])
                applied_to = {"type": "annual", "id": annual["id"], "year": year_key}
        if create_insight:
            scope_types = {
                str(item.get("id")): str(item.get("type") or "daily")
                for item in candidate.get("scope") or []
            }
            source_ids = [
                {"type": item.get("source_type") or scope_types.get(str(item.get("source_id")), "daily"), "id": item.get("source_id")}
                for item in chosen.get("evidence") or []
                if item.get("source_id")
            ]
            insight = self.create_insight(
                user_id,
                {
                    "tier": chosen.get("tier") or "branch",
                    "level": chosen.get("level") or 1,
                    "statement": chosen.get("statement") or "",
                    "category": chosen.get("category") or "pattern",
                    "evidence": chosen.get("evidence") or [],
                    "counter_evidence": chosen.get("counter_evidence") or [],
                    "evidence_span": chosen.get("evidence_span") or {},
                    "evidence_strength": chosen.get("evidence_strength") or {},
                    "uncertainty": chosen.get("uncertainty", 0.5),
                    "uncertainty_note": chosen.get("uncertainty_note") or "",
                    "verification_experiment": chosen.get("verification_experiment") or "",
                    "source_ids": source_ids,
                    "ai_candidate_id": candidate_id,
                    "status": "pending",
                },
            )
            self.syncer.sync(user_id, "insight", insight["id"])
        return {"candidate": confirmed, "insight": insight, "applied_to": applied_to}
