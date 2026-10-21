"""Согласованность двух независимых слепых экспертов и итоговые оценки по условиям.

Читает results/judge_output/*.json (эксперт 1) и results/judge_output_2/*.json (эксперт 2),
сопоставляет решения через _private/judge_map.json. Для каждого критерия считает долю точных
совпадений, совпадений в пределах ±1 балла, ρ Спирмена и квадратично взвешенную каппу Коэна.
Итоговая оценка решения – среднее двух экспертов; пишет results/judge_scores.json.
Запуск: python -I judge_agreement.py
"""
import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
CRIT = ("conventions", "readability", "focus", "tests", "overall")


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else float("nan")


def qwk(a, b, lo=1, hi=5):
    n = hi - lo + 1
    obs = [[0] * n for _ in range(n)]
    for x, y in zip(a, b):
        obs[x - lo][y - lo] += 1
    total = len(a)
    ha = [sum(obs[i]) for i in range(n)]
    hb = [sum(obs[i][j] for i in range(n)) for j in range(n)]
    num = den = 0.0
    for i in range(n):
        for j in range(n):
            w = (i - j) ** 2 / (n - 1) ** 2
            num += w * obs[i][j]
            den += w * ha[i] * hb[j] / total
    return 1 - num / den if den else float("nan")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mapping = json.loads((HERE / "_private" / "judge_map.json").read_text(encoding="utf-8"))
    pairs = []
    for f1 in sorted((RES / "judge_output").glob("*.json")):
        f2 = RES / "judge_output_2" / f1.name
        if not f2.exists():
            continue
        d1, d2 = (json.loads(p.read_text(encoding="utf-8")) for p in (f1, f2))
        for letter in d1:
            if letter in d2:
                pairs.append((mapping[f"{f1.stem}/{letter}"], d1[letter], d2[letter]))
    out = {"n_solutions": len(pairs), "agreement": {}}
    print(f"Решений, оценённых обоими экспертами: {len(pairs)}")
    for c in CRIT:
        a = [int(p[1][c]) for p in pairs]
        b = [int(p[2][c]) for p in pairs]
        exact = sum(x == y for x, y in zip(a, b)) / len(a)
        within1 = sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a)
        res = {"exact": exact, "within1": within1, "spearman": spearman(a, b), "qwk": qwk(a, b)}
        out["agreement"][c] = res
        print(f"  {c:12s} точно {exact:.0%}, ±1 {within1:.0%}, ρ = {res['spearman']:.2f}, κw = {res['qwk']:.2f}")
    scores = {tid: {c: (float(s1[c]) + float(s2[c])) / 2 for c in CRIT} for tid, s1, s2 in pairs}
    (RES / "judge_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    # Средние по условиям и перестановочный тест внутри задач для общей оценки.
    by = {}
    for tid, sc in scores.items():
        task, cond = tid.split("__")[0], tid.split("__")[1]
        by.setdefault(cond, []).append((task, sc))
    for cond, items in sorted(by.items()):
        print(f"  {cond}: " + ", ".join(f"{c} {st.mean(s[c] for _, s in items):.2f}" for c in CRIT))
    rng = random.Random(7)
    def diff(lab):
        s = [v for (t, c), v in lab if c == "sdd"]
        b = [v for (t, c), v in lab if c == "baseline"]
        return st.mean(s) - st.mean(b)
    lab = [((tid.split("__")[0], tid.split("__")[1]), sc["overall"]) for tid, sc in scores.items()]
    obs = diff(lab)
    hits = 0
    tasks = sorted({t for (t, _), _ in lab})
    for _ in range(20000):
        perm = []
        for t in tasks:
            g = [x for x in lab if x[0][0] == t]
            conds = [x[0][1] for x in g]
            rng.shuffle(conds)
            perm += [((t, conds[i]), g[i][1]) for i in range(len(g))]
        hits += abs(diff(perm)) >= abs(obs) - 1e-12
    p = (hits + 1) / 20001
    out["overall_diff"], out["overall_p"] = obs, p
    print(f"  overall: Δ(sdd−baseline) = {obs:.2f}, p = {p:.3f}")
    (RES / "judge_agreement.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
