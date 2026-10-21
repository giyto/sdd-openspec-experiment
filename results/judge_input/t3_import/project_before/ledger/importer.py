"""Импорт банковских выписок.

Сейчас поддерживается CSV-выписка банка «Нова»:

    date,amount,description
    2026-03-01,-350.00,Кофейня Зерно
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import os

from ledger.clock import Clock, SystemClock
from ledger.errors import StatementError, ValidationError
from ledger.models import Transaction, parse_amount
from ledger.rules import Categorizer
from ledger.storage import MemoryStore

logger = logging.getLogger(__name__)

NOVA_COLUMNS = ("date", "amount", "description")


def _parse_row(row: dict[str, str], line_no: int, imported_at: dt.datetime) -> Transaction:
    try:
        date = dt.date.fromisoformat(row["date"].strip())
    except ValueError as exc:
        raise StatementError(f"invalid date {row['date']!r}", line_no=line_no) from exc
    try:
        amount = parse_amount(row["amount"])
        return Transaction(
            date=date,
            amount=amount,
            description=row["description"].strip(),
            imported_at=imported_at,
        )
    except ValidationError as exc:
        raise StatementError(str(exc), line_no=line_no) from exc


def import_csv(
    path: str | os.PathLike[str],
    store: MemoryStore,
    categorizer: Categorizer | None = None,
    clock: Clock | None = None,
) -> int:
    """Импортирует выписку «Новы» в store и возвращает число добавленных транзакций."""
    clock = clock or SystemClock()
    imported_at = clock.now()
    count = 0
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = [c for c in NOVA_COLUMNS if c not in fieldnames]
        if missing:
            raise StatementError(f"missing columns: {', '.join(missing)}", line_no=1)
        for line_no, row in enumerate(reader, start=2):
            if any(row.get(c) is None for c in NOVA_COLUMNS):
                raise StatementError("not enough fields", line_no=line_no)
            tx = _parse_row(row, line_no, imported_at)
            if categorizer is not None:
                category = categorizer.categorize(tx)
                if category is not None:
                    tx = Transaction(
                        date=tx.date,
                        amount=tx.amount,
                        description=tx.description,
                        category=category,
                        imported_at=tx.imported_at,
                    )
            store.add(tx)
            count += 1
    logger.info("imported %d transactions from %s", count, path)
    return count
