"""Отчёты по остаткам и движению. Только чтение, ничего не меняют."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime

from .events import EventLog
from .inventory import Inventory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Movement:
    """Сводка движения по SKU за период."""

    sku: str
    received: int = 0
    issued: int = 0
    adjusted: int = 0

    @property
    def net(self) -> int:
        return self.received - self.issued + self.adjusted


def stock_report(inventory: Inventory, warehouse: str | None = None) -> str:
    """Текстовая таблица физических остатков."""
    levels = inventory.stock_levels(warehouse)
    if not levels:
        return "(no stock)"
    rows = [("WAREHOUSE", "SKU", "NAME", "ON HAND")]
    for level in levels:
        sku = inventory.get_sku(level.sku)
        rows.append((level.warehouse, level.sku, sku.name, f"{level.on_hand} {sku.unit}"))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = []
    for row in rows:
        cells = [row[i].ljust(widths[i]) for i in range(3)] + [row[3].rjust(widths[3])]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def stock_csv(inventory: Inventory) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["warehouse", "sku", "on_hand"])
    for level in inventory.stock_levels():
        writer.writerow([level.warehouse, level.sku, level.on_hand])
    return buffer.getvalue()


def low_stock(inventory: Inventory, threshold: int) -> list[tuple[str, str, int]]:
    """Позиции, физический остаток которых ниже порога (нулевые не попадают)."""
    return [
        (level.warehouse, level.sku, level.on_hand)
        for level in inventory.stock_levels()
        if level.on_hand < threshold
    ]


def movement_summary(
    log: EventLog, since: datetime | None = None, until: datetime | None = None
) -> dict[str, Movement]:
    """Приход/расход/корректировки по SKU за полуинтервал ``[since, until)``.

    Перемещения между складами в сводку не входят: для компании в целом
    это не движение товара.
    """
    totals: dict[str, dict[str, int]] = {}
    for event in log:
        if since is not None and event.ts < since:
            continue
        if until is not None and event.ts >= until:
            continue
        sku = event.get("sku")
        if sku is None:
            continue
        bucket = totals.setdefault(sku, {"received": 0, "issued": 0, "adjusted": 0})
        if event.kind == "RECEIVE":
            bucket["received"] += int(event.fields["qty"])
        elif event.kind == "ISSUE":
            bucket["issued"] += int(event.fields["qty"])
        elif event.kind == "ADJUST":
            bucket["adjusted"] += int(event.fields["delta"])
    logger.debug("movement summary for %d SKUs", len(totals))
    return {sku: Movement(sku=sku, **values) for sku, values in sorted(totals.items())}
