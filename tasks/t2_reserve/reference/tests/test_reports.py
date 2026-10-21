from datetime import datetime, timedelta, timezone

from warehouse import reports

T0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_stock_report_table(inv):
    inv.receive("MAIN", "BOLT-M8", 120)
    inv.receive("MAIN", "OIL-5L", 4)
    assert reports.stock_report(inv).splitlines() == [
        "WAREHOUSE  SKU      NAME       ON HAND",
        "MAIN       BOLT-M8  Болт М8    120 pcs",
        "MAIN       OIL-5L   Масло 5 л    4 can",
    ]


def test_stock_report_empty(inv):
    assert reports.stock_report(inv) == "(no stock)"


def test_stock_csv(inv):
    inv.receive("MAIN", "NUT-M8", 3)
    assert reports.stock_csv(inv) == "warehouse,sku,on_hand\nMAIN,NUT-M8,3\n"


def test_low_stock(inv):
    inv.receive("MAIN", "NUT-M8", 3)
    inv.receive("MAIN", "BOLT-M8", 50)
    assert reports.low_stock(inv, 10) == [("MAIN", "NUT-M8", 3)]


def test_movement_summary_ignores_transfers_and_respects_period(inv, clock):
    inv.receive("MAIN", "BOLT-M8", 10)
    clock.advance(timedelta(hours=1))
    inv.issue("MAIN", "BOLT-M8", 4)
    inv.transfer("MAIN", "NORTH", "BOLT-M8", 2)
    inv.adjust("MAIN", "BOLT-M8", 3, "recount")
    summary = reports.movement_summary(inv.log)
    assert summary["BOLT-M8"].received == 10
    assert summary["BOLT-M8"].issued == 4
    assert summary["BOLT-M8"].adjusted == -1
    assert summary["BOLT-M8"].net == 5
    later = reports.movement_summary(inv.log, since=T0 + timedelta(minutes=30))
    assert later["BOLT-M8"].received == 0
