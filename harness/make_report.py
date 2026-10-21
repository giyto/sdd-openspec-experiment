"""Собирает таблицы отчёта по эксперименту из eval.json всех прогонов (разметка build_docx.py).

Запуск: python -I make_report.py > ../results/report_tables.txt
"""
import glob
import json
import statistics as st
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
TASK_NAMES = {"t1_promo": "Промокоды", "t2_reserve": "Склад", "t3_import": "Импорт выписок", "t4_retry": "Повторы"}
COND_NAMES = {"baseline": "тикет", "sdd": "SDD", "sdd_rules": "SDD + правило",
              "base_po": "тикет + отчёт", "plan_po": "план до кода", "sdd_po": "SDD", "sdd_po_rules": "SDD + правило"}


def pct(xs):
    xs = [x for x in xs if x is not None]
    return f"{100 * st.mean(xs):.1f}".replace(".", ",") if xs else "—"


def num(xs, d=1):
    xs = [x for x in xs if x is not None]
    return f"{st.mean(xs):.{d}f}".replace(".", ",") if xs else "—"


def load(root, tag=None):
    out = []
    for f in glob.glob(str(EXP / root / "*" / "eval.json")):
        e = json.loads(Path(f).read_text(encoding="utf-8"))
        if tag and e.get("tag") != tag:
            continue
        out.append(e)
    return out


def table(caption, header, rows):
    print(f"@caption: {caption}")
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    e1 = load("runs", "v2")
    n = 1
    for model in ("sonnet", "haiku"):
        conds = ["baseline", "sdd"] + (["sdd_rules"] if model == "sonnet" else [])
        rows = []
        for t in TASK_NAMES:
            for c in conds:
                es = [e for e in e1 if e["model"] == model and e["task"] == t and e["condition"] == c]
                if not es:
                    continue
                rows.append([TASK_NAMES[t], COND_NAMES[c], str(len(es)),
                             pct([e["hidden_pass_rate"] for e in es]), pct([e["req_satisfied"] / e["req_total"] for e in es]),
                             num([e["new_test_funcs"] for e in es], 0), num([e["wall_s"] / 60 for e in es]),
                             num([e["cost_usd"] for e in es], 2)])
        table(f"Таблица {n} – Эксперимент 1, модель {model.capitalize()}: результаты по задачам",
              ["Задача", "Условие", "n", "Скрытые тесты, %", "Требования, %", "Тестов агента", "Время, мин", "Стоимость, $"], rows)
        n += 1
    e2 = load("runs_cr", "v2")
    for model in ("sonnet", "haiku"):
        rows = []
        for t in TASK_NAMES:
            for c in ("baseline", "sdd", "sdd_rules"):
                es = [e for e in e2 if e["model"] == model and e["task"] == t and e["condition"] == c]
                if not es:
                    continue
                rows.append([TASK_NAMES[t], COND_NAMES[c], str(len(es)), pct([e["cr_pass_rate"] for e in es]),
                             pct([e["cr_req_satisfied"] / e["cr_req_total"] for e in es]), pct([e["preserved_rate"] for e in es]),
                             num([e["wall_s"] / 60 for e in es]), num([e["cost_usd"] for e in es], 2)])
        if rows:
            table(f"Таблица {n} – Эксперимент 2, модель {model.capitalize()}: запрос на изменение в новой сессии",
                  ["Задача", "Условие", "n", "Тесты CR, %", "Требования CR, %", "Сохранность этапа 1, %", "Время, мин", "Стоимость, $"], rows)
            n += 1
    e3 = load("runs_po")
    rows = []
    for t in TASK_NAMES:
        for c in ("base_po", "plan_po", "sdd_po", "sdd_po_rules"):
            es = [e for e in e3 if e["task"] == t and e["condition"] == c]
            if not es:
                continue
            rows.append([TASK_NAMES[t], COND_NAMES[c], str(len(es)), pct([e["decisions_ok"] / e["decisions_total"] for e in es]),
                         pct([e["non_decision_pass_rate"] for e in es]), pct([e["hidden_pass_rate"] for e in es]),
                         num([e["po_comments_n"] for e in es]), num([e["cost_usd"] for e in es], 2)])
    table(f"Таблица {n} – Эксперимент 3 (Sonnet): неполная постановка и владелец продукта",
          ["Задача", "Условие", "n", "Решения PO, %", "Прочие тесты, %", "Все тесты, %", "Замечаний PO", "Стоимость, $"], rows)
    n += 1
    fc = json.loads((EXP / "results" / "failure_classes.json").read_text(encoding="utf-8"))
    agg = {}
    for k, v in fc.items():
        key = (k.split("/")[0], v["model"], v["condition"])
        a = agg.setdefault(key, [0, 0, 0, 0])
        a[0] += 1
        a[1] += bool(v["interface"])
        a[2] += len(v["interface"])
        a[3] += len(v["behavior"])
    rows = [[{"exp1": "1", "exp3": "3"}[k[0]], k[1].capitalize(), COND_NAMES[k[2]], str(a[0]), str(a[1]), str(a[2]), str(a[3])]
            for k, a in sorted(agg.items())]
    table(f"Таблица {n} – Классификация упавших скрытых тестов",
          ["Эксп.", "Модель", "Условие", "Прогонов", "Прогонов с ошибкой интерфейса", "Тестов: интерфейс", "Тестов: поведение"], rows)
    n += 1
    judge = json.loads((EXP / "results" / "judge_scores.json").read_text(encoding="utf-8"))
    rows = []
    for c in ("baseline", "sdd"):
        es = [judge[e["trial_id"]] for e in e1 if e["model"] == "sonnet" and e["condition"] == c and e["trial_id"] in judge]
        rows.append([COND_NAMES[c], str(len(es))] + [num([s[k] for s in es], 2) for k in ("conventions", "readability", "focus", "tests", "overall")])
    table(f"Таблица {n} – Слепая экспертная оценка кода (эксперимент 1, Sonnet), баллы 1–5",
          ["Условие", "n", "Соглашения", "Читаемость", "Сфокусированность", "Тесты", "Общая"], rows)
    total = len(e1) + len(e2) + len(e3)
    print(f"@@total_runs {total} (эксп.1: {len(e1)}, эксп.2: {len(e2)}, эксп.3: {len(e3)})")


if __name__ == "__main__":
    main()
