import datetime as dt
import json
from decimal import Decimal

import pytest

from ledger.errors import ValidationError
from ledger.models import Transaction
from ledger.rules import Categorizer, Rule, load_rules, normalize_text


def _tx(desc, amount="-100.00"):
    return Transaction(dt.date(2026, 3, 1), Decimal(amount), desc)


def test_first_matching_rule_wins_case_insensitive():
    cat = Categorizer([Rule("кофе", "cafe"), Rule("КОФЕЙНЯ", "other")])
    assert cat.categorize(_tx("Кофейня Зерно")) == "cafe"
    assert cat.categorize(_tx("Такси")) is None


def test_rule_kind_limits_direction():
    cat = Categorizer([Rule("перевод", "income-transfer", kind="income"), Rule("перевод", "out")])
    assert cat.categorize(_tx("Перевод от Ивана", "500.00")) == "income-transfer"
    assert cat.categorize(_tx("Перевод Ивану", "-500.00")) == "out"


def test_rule_validation():
    with pytest.raises(ValidationError):
        Rule("", "x")
    with pytest.raises(ValidationError):
        Rule("x", "y", kind="both")


def test_load_rules(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps([{"pattern": "такси", "category": "transport", "kind": "expense"}], ensure_ascii=False),
        encoding="utf-8",
    )
    cat = load_rules(path)
    assert cat.categorize(_tx("Яндекс Такси")) == "transport"
    path.write_text('[{"category": "x"}]', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_rules(path)


def test_normalize_text():
    assert normalize_text("  Ёлки 	  Палки ") == "елки палки"
    cat = Categorizer([Rule("пятёрочка", "food")])
    assert cat.categorize(_tx("ПЯТЕРОЧКА  №12")) == "food"
