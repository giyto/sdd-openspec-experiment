"""Командная строка: прогон сценария операций из JSON и вывод отчёта.

Пример сценария::

    [
      {"op": "register", "sku": "BOLT-M8", "name": "Болт М8"},
      {"op": "receive", "wh": "MAIN", "sku": "BOLT-M8", "qty": 100},
      {"op": "issue", "wh": "MAIN", "sku": "BOLT-M8", "qty": 5, "ref": "SO-1"}
    ]

Запуск: ``python -m warehouse.cli run scenario.json --show log``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import reports
from .errors import WarehouseError
from .inventory import Inventory

logger = logging.getLogger(__name__)


def apply_operation(inventory: Inventory, op: dict[str, Any]) -> None:
    kind = op.get("op")
    if kind == "register":
        inventory.register_sku(op["sku"], op.get("name", op["sku"]), op.get("unit", "pcs"))
    elif kind == "receive":
        inventory.receive(op["wh"], op["sku"], op["qty"], op.get("ref"))
    elif kind == "issue":
        inventory.issue(op["wh"], op["sku"], op["qty"], op.get("ref"))
    elif kind == "transfer":
        inventory.transfer(op["src"], op["dst"], op["sku"], op["qty"], op.get("ref"))
    elif kind == "adjust":
        inventory.adjust(op["wh"], op["sku"], op["counted"], op["reason"])
    else:
        raise WarehouseError(f"unknown operation {kind!r}")


def run_scenario(operations: list[dict[str, Any]], inventory: Inventory | None = None) -> Inventory:
    inventory = inventory if inventory is not None else Inventory()
    for index, op in enumerate(operations, start=1):
        try:
            apply_operation(inventory, op)
        except KeyError as exc:
            raise WarehouseError(f"operation #{index}: missing field {exc.args[0]!r}") from exc
        except WarehouseError as exc:
            raise WarehouseError(f"operation #{index}: {exc}") from exc
    return inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warehouse")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="apply a JSON scenario and print a report")
    run.add_argument("scenario", type=Path)
    run.add_argument("--show", choices=["stock", "csv", "log", "movement"], default="stock")
    run.add_argument("--warehouse", default=None)
    run.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    try:
        operations = json.loads(args.scenario.read_text(encoding="utf-8"))
        inventory = run_scenario(operations)
    except (OSError, ValueError, WarehouseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.show == "stock":
        print(reports.stock_report(inventory, args.warehouse), file=out)
    elif args.show == "csv":
        print(reports.stock_csv(inventory), end="", file=out)
    elif args.show == "log":
        for line in inventory.log.lines():
            print(line, file=out)
    else:
        for movement in reports.movement_summary(inventory.log).values():
            print(
                f"{movement.sku}: +{movement.received} -{movement.issued} "
                f"adj {movement.adjusted:+d} net {movement.net:+d}",
                file=out,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
