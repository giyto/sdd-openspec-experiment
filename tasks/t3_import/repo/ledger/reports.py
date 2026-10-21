"""Отчёты по транзакциям."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from ledger.models import UNCATEGORIZED, Transaction, format_amount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonthlySummary:
    year: int
    month: int
    income: Decimal
    expense: Decimal
    by_category: dict[str, Decimal] = field(default_factory=dict)

    @property
    def balance(self) -> Decimal:
        return self.income + self.expense


def monthly_summary(transactions: Iterable[Transaction], year: int, month: int) -> MonthlySummary:
    """Сводка за месяц: приходы, расходы и сумма расходов по категориям."""
    income = Decimal("0.00")
    expense = Decimal("0.00")
    by_category: dict[str, Decimal] = {}
    for tx in transactions:
        if tx.month != (year, month):
            continue
        if tx.amount > 0:
            income += tx.amount
        else:
            expense += tx.amount
            key = tx.category or UNCATEGORIZED
            by_category[key] = by_category.get(key, Decimal("0.00")) + tx.amount
    logger.debug("summary %04d-%02d: income=%s expense=%s", year, month, income, expense)
    return MonthlySummary(year, month, income, expense, dict(sorted(by_category.items())))


def format_summary(summary: MonthlySummary) -> str:
    lines = [
        f"{summary.year:04d}-{summary.month:02d}",
        f"  income:  {format_amount(summary.income)}",
        f"  expense: {format_amount(summary.expense)}",
        f"  balance: {format_amount(summary.balance)}",
    ]
    if summary.by_category:
        lines.append("  by category:")
        width = max(len(name) for name in summary.by_category)
        for name, total in summary.by_category.items():
            lines.append(f"    {name:<{width}}  {format_amount(total)}")
    return "\n".join(lines)
