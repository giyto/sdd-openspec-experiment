"""Оценка прогона эксперимента 3: метрики эксперимента 1 + выполнение решений PO (D1..Dn).
Запуск: python -I evaluate_po.py <trial_id> | --all
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["SDD_META_ROOT"] = str(HERE.parent / "runs_po")
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402


def evaluate(tid):
    res = ev.evaluate(tid)
    task_dir = ev.TASKS / res["task"]
    po_meta = json.loads((task_dir / "po_meta.json").read_text(encoding="utf-8"))
    by_func = res["hidden_by_func"]
    dec = {}
    for d in po_meta["decisions"]:
        oks = [ok for t in d["tests"] for ok in by_func.get(t, [])]
        dec[d["id"]] = all(oks) if oks else None
    dec_tests = {t for d in po_meta["decisions"] for t in d["tests"]}
    other = [ok for n, oks in by_func.items() if n not in dec_tests for ok in oks]
    info = json.loads((ev.META_ROOT / tid / "trial.json").read_text(encoding="utf-8"))
    po_text = info.get("po_comments", "")
    res.update({
        "decisions_total": len(dec), "decisions_ok": sum(1 for v in dec.values() if v), "decision_status": dec,
        "non_decision_pass_rate": round(sum(other) / len(other), 4) if other else None,
        "po_comments_n": 0 if "Замечаний нет" in po_text else sum(1 for line in po_text.splitlines() if re.match(r"\s*\d+[.)]\s", line)),
    })
    (ev.META_ROOT / tid / "eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ids = [p.name for p in ev.META_ROOT.iterdir() if (p / "trial.json").exists()] if sys.argv[1] == "--all" else sys.argv[1:]
    for t in ids:
        r = evaluate(t)
        print(f"{t}: hidden {r['hidden_passed']}/{r['hidden_total']} decisions {r['decisions_ok']}/{r['decisions_total']} "
              f"other {r['non_decision_pass_rate']} po_comments {r['po_comments_n']} cost {r['cost_usd']}")
