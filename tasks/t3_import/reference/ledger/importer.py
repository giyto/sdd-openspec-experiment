"""Импорт банковских выписок.

Поддерживаемые форматы:

    nova         date,amount,description           (ISO-дата, точка, UTF-8)
    sfera        Дата;Сумма;Описание               (ДД.ММ.ГГГГ, запятая, знак)
    sfera_split  Дата;Описание;Приход;Расход       (суммы без знака, одна из двух колонок)

Файл читается как UTF-8 (BOM допускается), а если не получилось — как cp1251.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Callable, Sequence

from ledger.clock import Clock, SystemClock
from ledger.errors import StatementError, StatementRowError, UnknownFormatError, ValidationError
from ledger.models import Transaction, parse_amount, to_money
from ledger.rules import Categorizer, normalize_text
from ledger.storage import MemoryStore

logger = logging.getLogger(__name__)

NOVA_COLUMNS = ("date", "amount", "description")

_SFERA_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_SFERA_AMOUNT = re.compile(r"^([+-]?)(\d+)(?:,(\d{1,2}))?$")
_THOUSANDS_SEPARATORS = (" ", " ")

# Разобранная строка выписки: дата, сумма, описание.
_Parsed = tuple[dt.date, Decimal, str]


@dataclass(frozen=True)
class RowError:
    """Строка выписки, которую не удалось импортировать."""

    line_no: int
    message: str


@dataclass(frozen=True)
class ImportResult:
    """Итог импорта одного файла."""

    format: str
    encoding: str
    added: int = 0
    duplicates: int = 0
    errors: list[RowError] = field(default_factory=list)


@dataclass(frozen=True)
class _Format:
    name: str
    delimiter: str
    columns: tuple[str, ...]
    parse: Callable[[dict[str, str]], _Parsed]


def normalize_description(text: str) -> str:
    """Описание для сравнения при дедупликации — по правилам проекта (normalize_text)."""
    return normalize_text(text)


# --- разбор значений -------------------------------------------------------


def _parse_iso_date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValidationError(f"invalid date {text!r}") from exc


def _parse_ru_date(text: str) -> dt.date:
    cleaned = text.strip()
    if not _SFERA_DATE.match(cleaned):
        raise ValidationError(f"invalid date {text!r}, expected DD.MM.YYYY")
    try:
        return dt.datetime.strptime(cleaned, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValidationError(f"invalid date {text!r}") from exc


def _parse_ru_amount(text: str, *, signed: bool) -> Decimal:
    """'-1 234,56' -> Decimal('-1234.56'). Точка и >2 знаков после запятой — ошибка."""
    cleaned = text.strip()
    for sep in _THOUSANDS_SEPARATORS:
        cleaned = cleaned.replace(sep, "")
    match = _SFERA_AMOUNT.match(cleaned)
    if not match:
        raise ValidationError(f"invalid amount {text!r}")
    sign, whole, frac = match.groups()
    if sign and not signed:
        raise ValidationError(f"amount {text!r} must not have a sign")
    return to_money(Decimal(f"{sign}{whole}.{frac or '0'}"))


def _parse_nova(row: dict[str, str]) -> _Parsed:
    return _parse_iso_date(row["date"]), parse_amount(row["amount"]), row["description"]


def _parse_sfera(row: dict[str, str]) -> _Parsed:
    return _parse_ru_date(row["дата"]), _parse_ru_amount(row["сумма"], signed=True), row["описание"]


def _parse_sfera_split(row: dict[str, str]) -> _Parsed:
    def side(text: str) -> Decimal | None:
        if not text.strip():
            return None
        value = _parse_ru_amount(text, signed=False)
        return value if value != 0 else None

    income, expense = side(row["приход"]), side(row["расход"])
    if (income is None) == (expense is None):
        raise ValidationError("exactly one of 'Приход' and 'Расход' must be filled")
    amount = income if income is not None else -expense
    return _parse_ru_date(row["дата"]), amount, row["описание"]


# Порядок важен при автоопределении: более специфичные форматы раньше.
FORMATS: dict[str, _Format] = {
    f.name: f
    for f in (
        _Format("sfera_split", ";", ("дата", "описание", "приход", "расход"), _parse_sfera_split),
        _Format("sfera", ";", ("дата", "сумма", "описание"), _parse_sfera),
        _Format("nova", ",", NOVA_COLUMNS, _parse_nova),
    )
}


# --- чтение файла ----------------------------------------------------------


def _read_text(path: str | os.PathLike[str]) -> tuple[str, str]:
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1251"), "cp1251"
    except UnicodeDecodeError as exc:
        raise StatementError(f"cannot decode {path}: neither UTF-8 nor cp1251") from exc


def _reader(text: str, fmt: _Format):
    return csv.reader(io.StringIO(text, newline=""), delimiter=fmt.delimiter)


def _column_index(header: Sequence[str], fmt: _Format) -> dict[str, int] | None:
    names = [name.strip().casefold() for name in header]
    index: dict[str, int] = {}
    for column in fmt.columns:
        if column not in names:
            return None
        index[column] = names.index(column)
    return index


def _header(text: str, fmt: _Format) -> list[str]:
    return next(_reader(text, fmt), [])


def _detect(text: str, fmt_name: str | None) -> _Format:
    if not text.strip():
        raise UnknownFormatError("empty statement file")
    if fmt_name is not None:
        fmt = FORMATS.get(fmt_name)
        if fmt is None:
            raise UnknownFormatError(f"unknown format {fmt_name!r}")
        if _column_index(_header(text, fmt), fmt) is None:
            raise UnknownFormatError(f"header does not match format {fmt_name!r}", line_no=1)
        return fmt
    for fmt in FORMATS.values():
        if _column_index(_header(text, fmt), fmt) is not None:
            return fmt
    raise UnknownFormatError("unrecognized statement header", line_no=1)


def detect_format(path: str | os.PathLike[str]) -> str:
    """Возвращает имя формата выписки по её заголовку."""
    text, _ = _read_text(path)
    return _detect(text, None).name


def _parse_rows(text: str, fmt: _Format, imported_at: dt.datetime, strict: bool):
    """Разбирает строки данных. Возвращает (транзакции, ошибки)."""
    reader = _reader(text, fmt)
    index = _column_index(next(reader), fmt)
    assert index is not None
    width = max(index.values()) + 1
    parsed: list[Transaction] = []
    errors: list[RowError] = []

    def fail(line_no: int, message: str) -> None:
        if strict:
            raise StatementRowError(message, line_no=line_no)
        logger.warning("line %d: %s", line_no, message)
        errors.append(RowError(line_no, message))

    while True:
        line_no = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            fail(line_no, f"malformed CSV: {exc}")
            break
        if all(not cell.strip() for cell in row):
            continue
        if len(row) < width:
            fail(line_no, f"expected at least {width} fields, got {len(row)}")
            continue
        values = {column: row[i] for column, i in index.items()}
        try:
            date, amount, description = fmt.parse(values)
            parsed.append(
                Transaction(
                    date=date,
                    amount=amount,
                    description=description.strip(),
                    imported_at=imported_at,
                )
            )
        except ValidationError as exc:
            fail(line_no, str(exc))
    return parsed, errors


def _dedup_key(tx: Transaction) -> tuple[dt.date, Decimal, str]:
    return (tx.date, tx.amount, normalize_description(tx.description))


def import_statement(
    path: str | os.PathLike[str],
    store: MemoryStore,
    *,
    fmt: str | None = None,
    strict: bool = False,
    categorizer: Categorizer | None = None,
    clock: Clock | None = None,
) -> ImportResult:
    """Импортирует выписку в store.

    Ничего не пишет в store, пока весь файл не разобран; в строгом режиме первая
    ошибочная строка бросает StatementRowError и хранилище остаётся нетронутым.
    """
    clock = clock or SystemClock()
    text, encoding = _read_text(path)
    statement_format = _detect(text, fmt)
    parsed, errors = _parse_rows(text, statement_format, clock.now(), strict)

    remaining = Counter(_dedup_key(tx) for tx in store.all())
    new: list[Transaction] = []
    duplicates = 0
    for tx in parsed:
        key = _dedup_key(tx)
        if remaining[key] > 0:
            remaining[key] -= 1
            duplicates += 1
            continue
        if categorizer is not None:
            category = categorizer.categorize(tx)
            if category is not None:
                tx = replace(tx, category=category)
        new.append(tx)

    store.add_many(new)
    logger.info(
        "imported %s (%s, %s): added=%d duplicates=%d errors=%d",
        path, statement_format.name, encoding, len(new), duplicates, len(errors),
    )
    return ImportResult(
        format=statement_format.name,
        encoding=encoding,
        added=len(new),
        duplicates=duplicates,
        errors=errors,
    )


def import_csv(
    path: str | os.PathLike[str],
    store: MemoryStore,
    categorizer: Categorizer | None = None,
    clock: Clock | None = None,
) -> int:
    """Импортирует выписку «Новы» в store и возвращает число добавленных транзакций.

    Строгий импорт: при ошибке в любой строке бросается StatementError, store не меняется.
    """
    result = import_statement(path, store, fmt="nova", strict=True, categorizer=categorizer, clock=clock)
    return result.added
