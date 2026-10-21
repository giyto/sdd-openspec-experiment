"""Модели предметной области и денежные суммы.

Все суммы в проекте — Decimal с двумя знаками после запятой.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ledger.errors import ValidationError

UNCATEGORIZED = "uncategorized"

CENT = Decimal("0.01")

_PLAIN_AMOUNT = re.compile(r"^[+-]?\d+(\.\d{1,2})?$")


def to_money(value: Decimal) -> Decimal:
    """Проверяет сумму и приводит её к двум знакам после запятой.

    Принимает только Decimal: float и int-строки сюда попадать не должны.
    Больше двух значащих знаков после запятой — ошибка, а не округление.
    """
    if not isinstance(value, Decimal):
        raise ValidationError(f"amount must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValidationError(f"amount must be finite, got {value}")
    quantized = value.quantize(CENT)
    if quantized != value:
        raise ValidationError(f"amount has more than 2 decimal places: {value}")
    return quantized


def parse_amount(text: str) -> Decimal:
    """Разбирает сумму вида '-1234.50' (точка, без разделителей тысяч)."""
    cleaned = text.strip()
    if not _PLAIN_AMOUNT.match(cleaned):
        raise ValidationError(f"invalid amount: {text!r}")
    try:
        return to_money(Decimal(cleaned))
    except InvalidOperation as exc:  # pragma: no cover - регулярка уже отсекла мусор
        raise ValidationError(f"invalid amount: {text!r}") from exc


def format_amount(amount: Decimal) -> str:
    """Форматирует сумму для людей: '-1 234.50'."""
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{' '.join(groups)}.{frac}"


@dataclass(frozen=True)
class Transaction:
    """Одна операция по счёту.

    amount < 0 — расход, amount > 0 — приход. Идентификатор назначает хранилище.
    """

    date: dt.date
    amount: Decimal
    description: str
    category: str | None = None
    imported_at: dt.datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.date, dt.date) or isinstance(self.date, dt.datetime):
            raise ValidationError(f"date must be datetime.date, got {self.date!r}")
        amount = to_money(self.amount)
        if amount == 0:
            raise ValidationError("amount must be non-zero")
        object.__setattr__(self, "amount", amount)
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValidationError("description must be a non-empty string")
        if self.category is not None and not self.category.strip():
            raise ValidationError("category must be None or a non-empty string")

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    @property
    def month(self) -> tuple[int, int]:
        return (self.date.year, self.date.month)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "amount": str(self.amount),
            "description": self.description,
            "category": self.category,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        imported_at = data.get("imported_at")
        return cls(
            id=data.get("id"),
            date=dt.date.fromisoformat(data["date"]),
            amount=Decimal(data["amount"]),
            description=data["description"],
            category=data.get("category"),
            imported_at=dt.datetime.fromisoformat(imported_at) if imported_at else None,
        )
