"""Sales reports for the back office.

Reports only read orders; they never change them. Cancelled orders are ignored.
A report can be limited to a period ``[since, until)`` of order creation time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .catalog import Category
from .errors import ValidationError
from .money import ZERO, format_money, quantize_money
from .orders import Order, OrderStatus


@dataclass(frozen=True)
class SalesReport:
    orders_count: int
    revenue: Decimal
    tax: Decimal
    shipping: Decimal
    by_category: dict[Category, Decimal]
    by_day: dict[date, Decimal]
    top_skus: list[tuple[str, int]]

    @property
    def average_order(self) -> Decimal:
        if self.orders_count == 0:
            return ZERO
        return quantize_money(self.revenue / self.orders_count)


def build_sales_report(
    orders: Iterable[Order],
    *,
    top: int = 5,
    since: datetime | None = None,
    until: datetime | None = None,
) -> SalesReport:
    """Aggregate placed orders created in ``[since, until)`` (both bounds optional)."""
    if since is not None and until is not None and since >= until:
        raise ValidationError("report period is empty: since must be earlier than until")
    count = 0
    revenue = tax = shipping = ZERO
    by_category: dict[Category, Decimal] = defaultdict(lambda: ZERO)
    by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    units: dict[str, int] = defaultdict(int)

    for order in orders:
        if order.status is not OrderStatus.PLACED:
            continue
        if since is not None and order.created_at < since:
            continue
        if until is not None and order.created_at >= until:
            continue
        count += 1
        revenue += order.total.total
        tax += order.total.tax
        shipping += order.total.shipping
        by_day[order.created_at.date()] += order.total.total
        for line in order.total.lines:
            by_category[line.category] += line.amount
            units[line.sku] += line.quantity

    top_skus = sorted(units.items(), key=lambda item: (-item[1], item[0]))[:top]
    return SalesReport(
        orders_count=count,
        revenue=revenue,
        tax=tax,
        shipping=shipping,
        by_category=dict(sorted(by_category.items(), key=lambda item: item[0].value)),
        by_day=dict(sorted(by_day.items())),
        top_skus=top_skus,
    )


def format_sales_report(report: SalesReport) -> str:
    rows = [
        f"Orders:        {report.orders_count}",
        f"Revenue:       {format_money(report.revenue)}",
        f"  incl. tax:   {format_money(report.tax)}",
        f"  shipping:    {format_money(report.shipping)}",
        f"Average order: {format_money(report.average_order)}",
        "",
        "By category:",
    ]
    rows += [f"  {cat.value:<12} {format_money(amount)}" for cat, amount in report.by_category.items()]
    rows += ["", "By day:"]
    rows += [f"  {day.isoformat()}   {format_money(amount)}" for day, amount in report.by_day.items()]
    rows += ["", "Top products:"]
    rows += [f"  {sku:<16} {qty} pcs" for sku, qty in report.top_skus]
    return "\n".join(rows)
