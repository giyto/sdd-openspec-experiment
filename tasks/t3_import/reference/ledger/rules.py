"""Правила автоматической категоризации."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ledger.errors import ValidationError
from ledger.models import Transaction

logger = logging.getLogger(__name__)

_KINDS = ("any", "income", "expense")


def normalize_text(text: str) -> str:
    """Приводит текст к виду для сравнения.

    Обрезает пробелы по краям, любые последовательности пробельных символов
    заменяет одним пробелом, приводит к нижнему регистру через casefold()
    и заменяет "ё" на "е". Так сравниваются описания операций везде в проекте;
    сами описания при этом хранятся как есть.
    """
    return " ".join(text.split()).casefold().replace("ё", "е")


@dataclass(frozen=True)
class Rule:
    """Если description содержит pattern (после normalize_text) — категория category.

    kind ограничивает правило приходами ("income") или расходами ("expense").
    """

    pattern: str
    category: str
    kind: str = "any"

    def __post_init__(self) -> None:
        if not self.pattern.strip():
            raise ValidationError("rule pattern must be non-empty")
        if not self.category.strip():
            raise ValidationError("rule category must be non-empty")
        if self.kind not in _KINDS:
            raise ValidationError(f"rule kind must be one of {_KINDS}, got {self.kind!r}")

    def matches(self, tx: Transaction) -> bool:
        if self.kind == "income" and tx.amount < 0:
            return False
        if self.kind == "expense" and tx.amount > 0:
            return False
        return normalize_text(self.pattern) in normalize_text(tx.description)


class Categorizer:
    """Применяет правила по порядку; побеждает первое подходящее."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def categorize(self, tx: Transaction) -> str | None:
        for rule in self._rules:
            if rule.matches(tx):
                logger.debug("rule %r matched %r", rule.pattern, tx.description)
                return rule.category
        return None


def load_rules(path: str | os.PathLike[str]) -> Categorizer:
    """Загружает правила из JSON: [{"pattern": ..., "category": ..., "kind": ...}]."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot read rules from {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ValidationError("rules file must contain a list")
    rules = []
    for item in raw:
        try:
            rules.append(Rule(item["pattern"], item["category"], item.get("kind", "any")))
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValidationError(f"bad rule {item!r}") from exc
    return Categorizer(rules)
