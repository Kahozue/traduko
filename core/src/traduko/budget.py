"""Budget meter: token and USD accounting for every LLM call.

Ledger is human-readable JSONL under <root>/budget/, one file per month.
Prices are USD per 1M tokens (input, output); users can override or extend
them in config/pricing.yaml.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import CoreConfig
from .events import Event, EventBus
from .llm import ChatRequest, ChatResponse, LLMProvider

BUILTIN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "deepseek-chat": (0.27, 1.1),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class BudgetExceededError(Exception):
    pass


def load_prices(root: Path) -> dict[str, tuple[float, float]]:
    prices = dict(BUILTIN_PRICES)
    path = root / "config" / "pricing.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for model, entry in data.items():
            prices[model] = (float(entry["input"]), float(entry["output"]))
    return prices


class BudgetMeter:
    def __init__(self, root: Path, bus: EventBus, config: CoreConfig) -> None:
        self.bus = bus
        self.config = config
        self._prices = load_prices(root)
        self._dir = root / "budget"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._month_usd = 0.0
        self._task_usd: dict[str, float] = {}
        self._warned: set[str] = set()
        self._load_ledgers()

    def _month_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _ledger_path(self) -> Path:
        return self._dir / f"ledger-{self._month_key()}.jsonl"

    def _load_ledgers(self) -> None:
        current = self._ledger_path().name
        for path in sorted(self._dir.glob("ledger-*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                cost = float(record.get("cost_usd", 0.0))
                task_id = record.get("task_id", "")
                self._task_usd[task_id] = self._task_usd.get(task_id, 0.0) + cost
                if path.name == current:
                    self._month_usd += cost

    def task_usage_usd(self, task_id: str) -> float:
        return self._task_usd.get(task_id, 0.0)

    def month_usage_usd(self) -> float:
        return self._month_usd

    def remaining_usd(self, task_id: str) -> float | None:
        """Smallest remaining headroom across task and month caps; None = uncapped."""
        remains = []
        task_limit = self.config.budget.task_usd_limit
        if task_limit is not None:
            remains.append(task_limit - self.task_usage_usd(task_id))
        month_limit = self.config.budget.monthly_usd_limit
        if month_limit is not None:
            remains.append(month_limit - self.month_usage_usd())
        if not remains:
            return None
        return max(0.0, min(remains))

    def _emit(self, event_type: str, project: str, task_id: str, data: dict) -> None:
        self.bus.publish(
            Event(type=event_type, task_id=task_id, project=project, data=data)
        )

    def _check_caps(self, project: str, task_id: str) -> None:
        task_limit = self.config.budget.task_usd_limit
        if task_limit is not None and self.task_usage_usd(task_id) >= task_limit:
            self._emit(
                "budget_exceeded", project, task_id,
                {"scope": "task", "used_usd": self.task_usage_usd(task_id), "limit_usd": task_limit},
            )
            raise BudgetExceededError(f"task budget exhausted: {task_id}")
        month_limit = self.config.budget.monthly_usd_limit
        if month_limit is not None and self.month_usage_usd() >= month_limit:
            self._emit(
                "budget_exceeded", project, task_id,
                {"scope": "month", "used_usd": self.month_usage_usd(), "limit_usd": month_limit},
            )
            raise BudgetExceededError("monthly budget exhausted")

    def _maybe_warn(self, project: str, task_id: str) -> None:
        checks = [
            ("task", f"task:{task_id}", self.task_usage_usd(task_id), self.config.budget.task_usd_limit),
            ("month", f"month:{self._month_key()}", self.month_usage_usd(), self.config.budget.monthly_usd_limit),
        ]
        for scope, key, used, limit in checks:
            if limit is not None and used >= 0.8 * limit and key not in self._warned:
                self._warned.add(key)
                self._emit(
                    "budget_warning", project, task_id,
                    {"scope": scope, "used_usd": used, "limit_usd": limit},
                )

    def chat(
        self, provider: LLMProvider, request: ChatRequest, *, project: str, task_id: str
    ) -> ChatResponse:
        self._check_caps(project, task_id)
        response = provider.chat(request)
        price = self._prices.get(request.model)
        usage = response.usage
        cost = 0.0
        if price is not None:
            cost = (
                usage.prompt_tokens / 1_000_000 * price[0]
                + usage.completion_tokens / 1_000_000 * price[1]
            )
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project": project,
            "task_id": task_id,
            "model": request.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": round(cost, 6),
            "price_known": price is not None,
        }
        with self._ledger_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._task_usd[task_id] = self._task_usd.get(task_id, 0.0) + cost
        self._month_usd += cost
        self._maybe_warn(project, task_id)
        return response
