"""Иерархия исключений складского учёта.

Все ошибки пакета наследуются от :class:`WarehouseError`, чтобы вызывающий
код (CLI, интеграции) мог ловить их одним ``except``.
"""

from __future__ import annotations


class WarehouseError(Exception):
    """Базовое исключение пакета ``warehouse``."""


class ValidationError(WarehouseError):
    """Некорректные входные данные (пустой код, пробелы в идентификаторе и т.п.)."""


class InvalidQuantityError(ValidationError):
    """Количество должно быть целым положительным числом."""

    def __init__(self, qty: object) -> None:
        super().__init__(f"quantity must be a positive integer, got {qty!r}")
        self.qty = qty


class UnknownSkuError(WarehouseError):
    """SKU не зарегистрирован в справочнике."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown SKU {sku!r}")
        self.sku = sku


class DuplicateSkuError(WarehouseError):
    """SKU с таким кодом уже зарегистрирован."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"SKU {sku!r} is already registered")
        self.sku = sku


class InsufficientStockError(WarehouseError):
    """Недостаточно товара для операции.

    ``requested`` — сколько всего единиц позиции требует операция,
    ``available`` — сколько из них сервис мог бы отдать в этот момент.
    """

    def __init__(self, warehouse: str, sku: str, requested: int, available: int) -> None:
        super().__init__(
            f"not enough {sku!r} at {warehouse!r}: requested {requested}, available {available}"
        )
        self.warehouse = warehouse
        self.sku = sku
        self.requested = requested
        self.available = available


class EventFormatError(WarehouseError):
    """Строку журнала невозможно записать или разобрать."""
