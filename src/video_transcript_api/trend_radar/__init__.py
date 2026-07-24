"""Trend opportunity radar backend."""

from .models import RawSignal
from .service import latest_report, run_report

__all__ = ["RawSignal", "latest_report", "run_report"]
