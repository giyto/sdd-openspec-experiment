"""Доменные модели. Все модели — неизменяемые датаклассы."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Sku:
    """Позиция справочника номенклатуры."""

    code: str
    name: str
    unit: str = "pcs"


@dataclass(frozen=True)
class Availability:
    """Остаток позиции с учётом активных резервов."""

    warehouse: str
    sku: str
    on_hand: int
    reserved: int
    available: int


@dataclass(frozen=True)
class StockLevel:
    """Физический остаток SKU на конкретном складе."""

    warehouse: str
    sku: str
    on_hand: int


class ReservationStatus(str, Enum):
    """Статус резерва. ``CONFIRMED`` и ``CANCELLED`` — окончательные."""

    ACTIVE = "active"
    EXPIRED = "expired"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ReservationLine:
    """Строка резерва: сколько единиц SKU держим на складе под заказ."""

    warehouse: str
    sku: str
    qty: int


@dataclass(frozen=True)
class Reservation:
    """Снимок резерва под заказ на момент запроса."""

    order_id: str
    lines: tuple[ReservationLine, ...]
    created_at: datetime
    expires_at: datetime
    status: ReservationStatus
