"""Сводка по всем оценённым прогонам: таблицы по задачам и условиям + статистика.

Тест значимости: перестановочный тест разности средних с перестановками внутри задачи
(стратифицированный), 20000 перестановок. Размер эффекта: Cliff's delta.
Запуск: python -I aggregate.py [--model sonnet]
"""
import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP_ROOTS = {"1": HERE.parent / "runs", "2": HERE.parent / "runs_cr", "3": HERE.parent / "runs_po"}
JUDGE = HERE.parent / "results" / "judge_scores.json"

METRICS_2 = [
    ("cr_pass_rate", "Доля тестов запроса на изменение", True),
    ("cr_req_rate", "Доля выполненных требований CR", True),
    ("preserved_rate", "Сохранность требований этапа 1", True),
    ("stage1_valid_pass_rate", "Доля неотменённых тестов этапа 1", True),
    ("regress_rate", "Доля исходных тестов", True),
    ("protected_n", "Затронуто защищённых файлов", False),
    ("prod_loc_cr", "Строк кода в пакете (+/-)", None),
    ("cost_usd", "Стоимость, $", False),
    ("wall_min", "Время, мин", False),
    ("output_tokens", "Выходные токены", False),
]
METRICS_3 = [
    ("hidden_pass_rate", "Доля скрытых тестов", True),
    ("decision_rate", "Доля выполненных решений PO", True),
    ("non_decision_pass_rate", "Доля прочих тестов", True),
    ("req_rate", "Доля выполненных требований", True),
    ("po_comments_n", "Замечаний PO", None),
    ("regress_rate", "Доля исходных тестов", True),
    ("cost_usd", "Стоимость, $", False),
    ("wall_min", "Время, мин", False),
]
METRICS = [
    ("hidden_pass_rate", "Доля скрытых тестов", True),
    ("req_rate", "Доля выполненных требований", True),
    ("regress_rate", "Доля исходных тестов", True),
    ("protected_n", "Затронуто защищённых файлов", False),
    ("prod_loc", "Строк кода в пакете (+/-)", None),
    ("new_test_funcs", "Новых тестов агента", None),
    ("cc_mean", "Средняя цикломатическая сложность", False),
    ("cost_usd", "Стоимость, $", False),
    ("wall_min", "Время, мин", False),
    ("output_tokens", "Выходные токены", False),
    ("judge", "Экспертная оценка (1–5)", True),
]


def load(model, exp="1", tag="v2", treat=None):
    rows = []
    judge = json.loads(JUDGE.read_text(encoding="utf-8")) if JUDGE.exists() else {}
    for p in sorted(EXP_ROOTS[exp].iterdir()):
        f = p / "eval.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["model"] != model or (exp != "3" and r.get("tag", "v1") != tag):
            continue
        treat_name = treat or {"1": "sdd", "2": "sdd", "3": "sdd_po"}[exp]
        base_name = "base_po" if exp == "3" else "baseline"
        if r["condition"] not in (base_name, treat_name):
            continue
        r["condition"] = "baseline" if r["condition"] == base_name else "sdd"
        if exp == "3":
            r["decision_rate"] = r["decisions_ok"] / r["decisions_total"] if r["decisions_total"] else None
        if exp == "2":
            r["cr_req_rate"] = r["cr_req_satisfied"] / r["cr_req_total"]
            r["prod_loc_cr"] = r["prod_loc"]
        else:
            r["req_rate"] = r["req_satisfied"] / r["req_total"]
            r["prod_loc"] = r["loc"]["prod_added"] + r["loc"]["prod_removed"]
        r["regress_rate"] = r["regress_passed"] / r["regress_total"] if r["regress_total"] else None
        r["protected_n"] = len(r["protected_touched"])
        r["wall_min"] = r["wall_s"] / 60 if r["wall_s"] else None
        r["judge"] = judge.get(r["trial_id"], {}).get("overall") if exp == "1" else None
        rows.append(r)
    return rows


def mean_sd(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "—"
    m = st.mean(xs)
    sd = st.stdev(xs) if len(xs) > 1 else 0.0
    return f"{m:.3g} ± {sd:.2g}" if abs(m) < 1000 else f"{m:,.0f} ± {sd:,.0f}"


def cliffs_delta(a, b):
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b)) if a and b else None


def strat_perm_test(rows, key, n=20000, seed=7):
    """H0: условие не влияет. Перемешиваем метки условий внутри каждой задачи."""
    by_task = {}
    for r in rows:
        if r.get(key) is None:
            continue
        by_task.setdefault(r["task"], []).append((r["condition"], r[key]))
    def stat(groups):
        s = [v for g in groups.values() for c, v in g if c == "sdd"]
        b = [v for g in groups.values() for c, v in g if c == "baseline"]
        return (st.mean(s) - st.mean(b)) if s and b else 0.0
    obs = stat(by_task)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n):
        perm = {}
        for t, g in by_task.items():
            labels = [c for c, _ in g]
            rng.shuffle(labels)
            perm[t] = [(labels[i], g[i][1]) for i in range(len(g))]
        if abs(stat(perm)) >= abs(obs) - 1e-12:
            hits += 1
    return obs, (hits + 1) / (n + 1)


def main():
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    model, exp, tag, treat = arg("--model", "sonnet"), arg("--exp", "1"), arg("--tag", "v2"), arg("--treat", None)
    rows = load(model, exp, tag, treat)
    metrics = {"1": METRICS, "2": METRICS_2, "3": METRICS_3}[exp]
    tasks = sorted({r["task"] for r in rows})
    out = {"model": model, "n_runs": len(rows), "per_task": {}, "overall": {}, "requirements": {}}
    print(f"Модель: {model}, прогонов: {len(rows)}\n")
    for key, title, _ in metrics:
        print(f"## {title}")
        for t in tasks + ["ВСЕ"]:
            sel = [r for r in rows if t == "ВСЕ" or r["task"] == t]
            b = [r[key] for r in sel if r["condition"] == "baseline"]
            s = [r[key] for r in sel if r["condition"] == "sdd"]
            print(f"  {t:12s} baseline {mean_sd(b):>18s} (n={len(b)})   sdd {mean_sd(s):>18s} (n={len(s)})")
            out["per_task"].setdefault(t, {})[key] = {"baseline": [x for x in b], "sdd": [x for x in s]}
        b_all = [r[key] for r in rows if r["condition"] == "baseline" and r.get(key) is not None]
        s_all = [r[key] for r in rows if r["condition"] == "sdd" and r.get(key) is not None]
        if b_all and s_all:
            diff, p = strat_perm_test(rows, key)
            d = cliffs_delta(s_all, b_all)
            print(f"  Δ(sdd−baseline) = {diff:.4g}; p(перест.) = {p:.4f}; Cliff's δ = {d:.2f}")
            out["overall"][key] = {"diff": diff, "p": p, "cliffs_delta": d,
                                   "baseline_mean": st.mean(b_all), "sdd_mean": st.mean(s_all),
                                   "baseline_sd": st.stdev(b_all) if len(b_all) > 1 else 0,
                                   "sdd_sd": st.stdev(s_all) if len(s_all) > 1 else 0}
        print()
    # Какие требования чаще проваливаются в каждом условии.
    for t in tasks:
        req = {}
        for r in rows:
            if r["task"] != t:
                continue
            for rid, ok in r.get("req_status", r.get("cr_req_status", r.get("decision_status", {}))).items():
                req.setdefault(rid, {"baseline": [0, 0], "sdd": [0, 0]})
                req[rid][r["condition"]][0] += bool(ok)
                req[rid][r["condition"]][1] += 1
        out["requirements"][t] = req
        print(f"## Требования {t}: выполнено baseline / sdd")
        print("  " + "  ".join(f"{rid}:{v['baseline'][0]}/{v['baseline'][1]}|{v['sdd'][0]}/{v['sdd'][1]}" for rid, v in req.items()))
    res_dir = HERE.parent / "results"
    res_dir.mkdir(exist_ok=True)
    (res_dir / f"summary_exp{exp}_{model}{'_' + treat if treat else ''}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
