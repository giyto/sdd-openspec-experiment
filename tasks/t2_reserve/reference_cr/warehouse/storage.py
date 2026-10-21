"""Хранилище в памяти: справочник SKU и физические остатки по складам."""

from __future__ import annotations

from typing import Iterator

from .models import Sku


class InMemoryStore:
    """Простое хранилище. Ничего не проверяет — проверки живут в сервисе."""

    def __init__(self) -> None:
        self._skus: dict[str, Sku] = {}
        self._quantities: dict[tuple[str, str], int] = {}

    # --- справочник ---------------------------------------------------------

    def add_sku(self, sku: Sku) -> None:
        self._skus[sku.code] = sku

    def get_sku(self, code: str) -> Sku | None:
        return self._skus.get(code)

    def has_sku(self, code: str) -> bool:
        return code in self._skus

    def list_skus(self) -> list[Sku]:
        return sorted(self._skus.values(), key=lambda sku: sku.code)

    # --- остатки ------------------------------------------------------------

    def get_qty(self, warehouse: str, sku: str) -> int:
        return self._quantities.get((warehouse, sku), 0)

    def set_qty(self, warehouse: str, sku: str, qty: int) -> None:
        if qty == 0:
            self._quantities.pop((warehouse, sku), None)
        else:
            self._quantities[(warehouse, sku)] = qty

    def positions(self) -> Iterator[tuple[str, str, int]]:
        """Все ненулевые позиции ``(warehouse, sku, qty)`` в стабильном порядке."""
        for (warehouse, sku), qty in sorted(self._quantities.items()):
            yield warehouse, sku, qty

    def warehouses(self) -> list[str]:
        return sorted({warehouse for warehouse, _ in self._quantities})
