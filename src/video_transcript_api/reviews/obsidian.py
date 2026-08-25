"""Idempotent review exports into the configured local Obsidian Vault."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..obsidian.paths import (
    VaultPathError,
    atomic_write_text,
    ensure_vault_directory_tree,
    resolve_vault_path,
    sanitize_markdown_filename,
)
from .markdown import ReviewMarkdownConflict, merge_review_markdown, synced_timestamp
from .repository import ReviewRepository


class ReviewSyncError(RuntimeError):
    """A database-backed review could not be safely exported."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReviewObsidianSyncService:
    """Write deterministic managed files without risking database records."""

    def __init__(
        self,
        repository: ReviewRepository,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.repository = repository
        self.config = dict(config or {})

    def configuration_status(self) -> dict[str, Any]:
        obsidian = self.config.get("obsidian") or {}
        vault_path = str(obsidian.get("vault_path") or "").strip()
        enabled = obsidian.get("enabled") is True
        return {
            "enabled": enabled,
            "configured": enabled and bool(vault_path),
            "vault_path": vault_path,
            "review_root": str(obsidian.get("review_root") or "复盘"),
        }

    def sync(self, user_id: str, record_type: str, record_id: str) -> dict[str, Any]:
        status = self.configuration_status()
        if not status["configured"]:
            return self.repository.save_sync_state(
                user_id, record_type, record_id, status="not_configured",
                error_message=None,
            )
        try:
            root = self.repository.get_preferences(user_id).get("obsidian_root") or status["review_root"]
            record = self._build_record(user_id, record_type, record_id, str(root))
            relative_path = self._relative_path(str(root), record_type, record)
            vault = Path(status["vault_path"]).expanduser()
            if not vault.is_dir():
                raise ReviewSyncError("vault_not_found", "configured Obsidian Vault does not exist")
            directory = PurePosixPath(relative_path).parent.as_posix()
            ensure_vault_directory_tree(vault, directory)
            target = resolve_vault_path(vault, relative_path)
            existing = target.read_text(encoding="utf-8") if target.exists() else None
            content = merge_review_markdown(existing, record_type, record)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            previous = self.repository.get_sync_state(user_id, record_type, record_id)
            if existing != content:
                atomic_write_text(vault, relative_path, content)
            return self.repository.save_sync_state(
                user_id,
                record_type,
                record_id,
                status="synced" if existing != content else "unchanged",
                relative_path=relative_path,
                content_hash=digest,
                error_message=None,
                synced_at=(previous or {}).get("synced_at") if existing == content else synced_timestamp(),
            )
        except ReviewSyncError as exc:
            return self.repository.save_sync_state(
                user_id, record_type, record_id, status="failed", error_message=f"{exc.code}:{exc}",
            )
        except (OSError, UnicodeError, VaultPathError, ReviewMarkdownConflict, ValueError) as exc:
            return self.repository.save_sync_state(
                user_id, record_type, record_id, status="failed", error_message=str(exc),
            )

    def _build_record(
        self, user_id: str, record_type: str, record_id: str, root: str
    ) -> dict[str, Any]:
        source = self.repository.source(user_id, record_type, record_id)
        if source is None:
            raise ReviewSyncError("record_not_found", "review record does not exist")
        if record_type == "daily":
            review_date = source["review_date"]
            events = self.repository.list_daily_events(user_id, review_date=review_date, limit=500)
            event_ids = {item["id"] for item in events}
            created_at = min((item["created_at"] for item in events), default=source["created_at"])
            updated_at = max((item["updated_at"] for item in events), default=source["updated_at"])
            return {
                "id": f"daily:{review_date}",
                "period": review_date,
                "events": events,
                "source_ids": [item["id"] for item in events],
                "related_ids": self._decorate_sources(
                    user_id,
                    self._daily_related_sources(user_id, review_date, event_ids),
                    root,
                ),
                "status": "active",
                "created_at": created_at,
                "updated_at": updated_at,
            }
        if record_type == "weekly":
            source["period"] = source["week_start"]
            source["focus_sources"] = self._decorate_sources(
                user_id, [{"type": "daily", "id": value} for value in source.get("focus_ids") or []], root
            )
            source["connections"] = self.repository.list_connections(
                user_id, period_type="weekly", period_key=source["week_start"]
            )
            source["experiments"] = self.repository.list_experiments(
                user_id, period_key=source["week_start"]
            )
        elif record_type == "monthly":
            source["period"] = source["month_key"]
        elif record_type == "annual":
            source["period"] = source["year_key"]
            source["months"] = list(
                reversed(
                    self.repository.list_monthly(
                        user_id, year=source["year_key"], limit=12
                    )
                )
            )
        elif record_type in {"insight", "experiment"}:
            source["period"] = source.get("review_date") or source.get("updated_at", "")[:10]
        else:
            raise ReviewSyncError("unsupported_record_type", "record type cannot be synchronized")
        source["source_ids"] = self._decorate_sources(
            user_id, source.get("source_ids") or [], root
        )
        if record_type == "annual":
            month_links = {
                item["id"]: item
                for item in self._decorate_sources(
                    user_id,
                    [{"type": "monthly", "id": month["id"]} for month in source["months"]],
                    root,
                )
            }
            for month in source["months"]:
                month["source_ref"] = month_links.get(month["id"])
        return source

    def _daily_related_sources(
        self, user_id: str, review_date: str, event_ids: set[str]
    ) -> list[dict[str, str]]:
        references: list[dict[str, str]] = []
        for weekly in self.repository.list_weekly(user_id, limit=120):
            if weekly["week_start"] <= review_date <= weekly["week_end"]:
                references.append({"type": "weekly", "id": weekly["id"]})
        monthly = self.repository.get_monthly(user_id, review_date[:7])
        if monthly:
            references.append({"type": "monthly", "id": monthly["id"]})
        for experiment in self.repository.list_experiments(user_id):
            source_ids = {
                str(item.get("id") or item.get("source_id") or "")
                if isinstance(item, Mapping)
                else str(item)
                for item in experiment.get("source_ids") or []
            }
            if event_ids.intersection(source_ids):
                references.append({"type": "experiment", "id": experiment["id"]})
        return references

    def _decorate_sources(
        self,
        user_id: str,
        raw_sources: list[Any],
        root: str,
    ) -> list[dict[str, Any]]:
        decorated: list[dict[str, Any]] = []
        for raw in raw_sources:
            reference = raw if isinstance(raw, Mapping) else {"type": "daily", "id": raw}
            source_type = str(reference.get("type") or reference.get("source_type") or "daily")
            source_id = str(reference.get("id") or reference.get("source_id") or "")
            if not source_id:
                continue
            record = self.repository.source(user_id, source_type, source_id)
            if record is None:
                continue
            period = str(
                record.get("review_date")
                or record.get("week_start")
                or record.get("month_key")
                or record.get("year_key")
                or record.get("updated_at", "")[:10]
            )
            path_record = {**record, "period": period}
            relative = self._relative_path(root, source_type, path_record)
            link = relative[:-3] if relative.endswith(".md") else relative
            if source_type == "daily":
                link = f"{link}#^{source_id}"
            decorated.append(
                {
                    "type": source_type,
                    "id": source_id,
                    "date": period,
                    "label": str(
                        reference.get("label")
                        or record.get("title")
                        or record.get("statement")
                        or period
                        or source_id
                    ),
                    "obsidian_link": link,
                }
            )
        return decorated

    @staticmethod
    def _relative_path(root: str, record_type: str, record: Mapping[str, Any]) -> str:
        period = str(record.get("period") or "")
        if record_type == "daily":
            directory = PurePosixPath(root, "每日", period[:4])
            filename = f"{period}-每日复盘.md"
        elif record_type == "weekly":
            year, week, _ = date.fromisoformat(period).isocalendar()
            directory = PurePosixPath(root, "周度", f"{year:04d}")
            filename = f"{year:04d}-W{week:02d}-周度复盘.md"
        elif record_type == "monthly":
            directory = PurePosixPath(root, "月度", period[:4])
            filename = f"{period}-月度复盘.md"
        elif record_type == "annual":
            directory = PurePosixPath(root, "年度")
            filename = f"{period}-年度复盘.md"
        elif record_type == "insight":
            directory = PurePosixPath(root, "内在洞察")
            filename = sanitize_markdown_filename(
                f"{record.get('tier')}-L{record.get('level')}-{record.get('statement')}",
                fallback=str(record.get("id")),
            )
        elif record_type == "experiment":
            directory = PurePosixPath(root, "行动实验")
            filename = sanitize_markdown_filename(
                str(record.get("title") or record.get("id")), fallback=str(record.get("id"))
            )
        else:
            raise ReviewSyncError("unsupported_record_type", "record type cannot be synchronized")
        return PurePosixPath(directory, filename).as_posix()
