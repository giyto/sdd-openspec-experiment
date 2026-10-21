"""Серия прогонов параллельно, с оценкой каждого сразу после завершения.

python -I run_batch.py --tasks t1_promo,t2_reserve --conds baseline,sdd --reps 1-3 --jobs 4 [--model sonnet]
Уже оценённые прогоны пропускаются (eval.json существует).
"""
import argparse
import itertools
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
META_ROOT = HERE.parent / "runs"


def one(task, cond, rep, model, ticket, tag):
    tid = f"{task}__{cond}__r{rep}__{model}__{tag}"
    if (META_ROOT / tid / "eval.json").exists():
        return tid, "skip"
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", str(HERE / "run_trial.py"), task, cond, str(rep), "--model", model, "--ticket", ticket, "--tag", tag],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return tid, f"RUN FAIL {r.stderr[-800:]}"
    e = subprocess.run([sys.executable, "-I", str(HERE / "evaluate.py"), tid],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return tid, f"{(time.time() - t0) / 60:.1f} min | {e.stdout.strip() or e.stderr[-800:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--conds", default="baseline,sdd")
    ap.add_argument("--reps", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--ticket", default="ticket.md")
    ap.add_argument("--tag", default="v2")
    a = ap.parse_args()
    lo, _, hi = a.reps.partition("-")
    reps = range(int(lo), int(hi or lo) + 1)
    # Порядок перемешан по условиям, чтобы условия шли вперемешку во времени.
    combos = [(t, c, r) for r in reps for t in a.tasks.split(",") for c in a.conds.split(",")]
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(one, t, c, r, a.model, a.ticket, a.tag) for t, c, r in combos]
        for f in as_completed(futs):
            tid, msg = f.result()
            print(f"[{time.strftime('%H:%M:%S')}] {tid}: {msg}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
