"""Командная строка: python -m ledger --store ledger.json <команда>."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, TextIO

from ledger.clock import Clock
from ledger.errors import LedgerError
from ledger.importer import import_csv
from ledger.models import format_amount
from ledger.reports import format_summary, monthly_summary
from ledger.rules import load_rules
from ledger.storage import JsonFileStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger")
    parser.add_argument("--store", required=True, help="путь к JSON-файлу хранилища")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="импортировать CSV-выписку")
    p_import.add_argument("path")
    p_import.add_argument("--rules", help="JSON-файл с правилами категоризации")

    p_list = sub.add_parser("list", help="показать транзакции")
    p_list.add_argument("--limit", type=int, default=20)

    p_report = sub.add_parser("report", help="сводка за месяц")
    p_report.add_argument("month", help="ГГГГ-ММ")
    return parser


def _parse_month(text: str) -> tuple[int, int]:
    try:
        year_s, month_s = text.split("-")
        year, month = int(year_s), int(month_s)
    except ValueError as exc:
        raise LedgerError(f"bad month {text!r}, expected YYYY-MM") from exc
    if not 1 <= month <= 12:
        raise LedgerError(f"bad month {text!r}, expected YYYY-MM")
    return year, month


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Clock | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = _build_parser().parse_args(argv)
    try:
        store = JsonFileStore(args.store)
        if args.command == "import":
            categorizer = load_rules(args.rules) if args.rules else None
            count = import_csv(args.path, store, categorizer=categorizer, clock=clock)
            print(f"Imported {count} transactions", file=out)
        elif args.command == "list":
            for tx in store.all()[-args.limit:]:
                category = tx.category or "-"
                print(
                    f"{tx.id:>5}  {tx.date.isoformat()}  {format_amount(tx.amount):>12}  "
                    f"{category:<14}  {tx.description}",
                    file=out,
                )
        elif args.command == "report":
            year, month = _parse_month(args.month)
            print(format_summary(monthly_summary(store.all(), year, month)), file=out)
    except LedgerError as exc:
        print(f"error: {exc}", file=err)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
