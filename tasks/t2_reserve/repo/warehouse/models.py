"""Доменные модели. Все модели — неизменяемые датаклассы."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sku:
    """Позиция справочника номенклатуры."""

    code: str
    name: str
    unit: str = "pcs"


@dataclass(frozen=True)
class StockLevel:
    """Физический остаток SKU на конкретном складе."""

    warehouse: str
    sku: str
    on_hand: int
