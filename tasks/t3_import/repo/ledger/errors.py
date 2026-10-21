"""Иерархия исключений проекта.

Весь код ledger бросает только наследников LedgerError, чтобы CLI и
вызывающий код могли перехватывать ошибки предметной области одним except.
"""

from __future__ import annotations


class LedgerError(Exception):
    """Базовое исключение ledger."""


class ValidationError(LedgerError):
    """Некорректные данные модели (сумма, дата, описание и т.п.)."""


class StorageError(LedgerError):
    """Ошибка чтения или записи хранилища."""


class StatementError(LedgerError):
    """Ошибка разбора банковской выписки.

    line_no — номер строки файла, если ошибка относится к конкретной строке;
    иначе None. Нумерация по физическим строкам файла: заголовок — строка 1,
    пустые строки тоже считаются; если запись в кавычках занимает несколько
    строк, её номер — строка, где она начинается.
    """

    def __init__(self, message: str, *, line_no: int | None = None) -> None:
        text = message if line_no is None else f"line {line_no}: {message}"
        super().__init__(text)
        self.message = message
        self.line_no = line_no
