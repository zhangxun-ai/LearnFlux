"""Portable date-period helpers for the review domain."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DatePeriod:
    """Inclusive business-date range used by one review."""

    start: date
    end: date

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def parse_date(value: str | date | None, *, default: date | None = None) -> date:
    """Parse an ISO business date without silently accepting timestamps."""

    if isinstance(value, date):
        return value
    if value is None or value == "":
        if default is not None:
            return default
        raise ValueError("date is required")
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def week_period(value: str | date, *, week_start_day: int = 0) -> DatePeriod:
    """Return the Monday-first (or configured) week containing ``value``.

    ``week_start_day`` follows ``date.weekday``: Monday is 0 and Sunday is 6.
    """

    if week_start_day not in range(7):
        raise ValueError("week_start_day must be between 0 and 6")
    target = parse_date(value)
    offset = (target.weekday() - week_start_day) % 7
    start = target - timedelta(days=offset)
    return DatePeriod(start=start, end=start + timedelta(days=6))


def month_period(value: str | date) -> DatePeriod:
    """Return the inclusive month containing ``value`` or identified by YYYY-MM."""

    if isinstance(value, str) and len(value) == 7:
        try:
            year, month = (int(part) for part in value.split("-", 1))
            start = date(year, month, 1)
        except (TypeError, ValueError) as exc:
            raise ValueError("month must use YYYY-MM") from exc
    else:
        target = parse_date(value)
        start = target.replace(day=1)
    last_day = calendar.monthrange(start.year, start.month)[1]
    return DatePeriod(start=start, end=start.replace(day=last_day))


def year_period(value: str | int | date) -> DatePeriod:
    """Return the inclusive calendar year identified by ``value``."""

    try:
        year = value.year if isinstance(value, date) else int(value)
        start = date(year, 1, 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("year must use YYYY") from exc
    return DatePeriod(start=start, end=date(start.year, 12, 31))


def iso_week_key(value: str | date) -> str:
    """Return the canonical YYYY-Www key for the week containing ``value``."""

    target = parse_date(value)
    iso_year, iso_week, _ = target.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"
