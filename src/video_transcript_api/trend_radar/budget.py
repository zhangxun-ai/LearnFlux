"""Budget accounting for paid trend radar collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class BudgetExceeded(ValueError):
    """Raised before a paid request would exceed the run budget."""


@dataclass
class BudgetLedger:
    """Conservative per-run budget ledger.

    TikHub may charge different endpoints differently, so the ledger uses a
    configurable estimated request cost and blocks before the projected API
    spend exceeds the budget left after reserving LLM spend.
    """

    limit_usd: float
    request_cost_usd: float = 0.01
    llm_reserved_usd: float = 0.2
    api_requests: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.limit_usd <= 0:
            raise ValueError("budget must be positive")
        if self.request_cost_usd <= 0:
            raise ValueError("request_cost_usd must be positive")
        if self.llm_reserved_usd < 0:
            raise ValueError("llm_reserved_usd cannot be negative")

    @property
    def api_budget_usd(self) -> float:
        return max(float(self.limit_usd) - float(self.llm_reserved_usd), 0.0)

    @property
    def api_requests_used(self) -> int:
        return len(self.api_requests)

    @property
    def estimated_api_usd(self) -> float:
        return round(self.api_requests_used * self.request_cost_usd, 4)

    @property
    def estimated_total_usd(self) -> float:
        return round(self.estimated_api_usd + self.llm_reserved_usd, 4)

    def record_api_request(self, source: str, endpoint: str) -> None:
        projected = self.estimated_api_usd + self.request_cost_usd
        if projected > self.api_budget_usd + 1e-9:
            raise BudgetExceeded(
                "Trend radar API budget exhausted before "
                f"{source} {endpoint}: projected ${projected:.2f}, "
                f"API budget ${self.api_budget_usd:.2f}"
            )
        self.api_requests.append(
            {
                "source": source,
                "endpoint": endpoint,
                "estimated_cost_usd": self.request_cost_usd,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        for item in self.api_requests:
            source = str(item["source"])
            by_source[source] = by_source.get(source, 0) + 1
        return {
            "limit_usd": round(self.limit_usd, 4),
            "api_budget_usd": round(self.api_budget_usd, 4),
            "llm_reserved_usd": round(self.llm_reserved_usd, 4),
            "request_cost_usd": round(self.request_cost_usd, 4),
            "api_requests_used": self.api_requests_used,
            "estimated_api_usd": self.estimated_api_usd,
            "estimated_total_usd": self.estimated_total_usd,
            "requests_by_source": by_source,
        }
