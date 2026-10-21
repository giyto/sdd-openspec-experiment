"""python -I run_po_batch.py --tasks t1_promo,... --reps 1-3 --jobs 4 [--model sonnet]"""
import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = HERE.parent / "runs_po"


def one(task, cond, rep, model):
    tid = f"{task}__{cond}__r{rep}__{model}__po"
    if (META / tid / "eval.json").exists():
        return tid, "skip"
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", str(HERE / "run_po.py"), task, cond, str(rep), "--model", model],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return tid, f"RUN FAIL {r.stderr[-800:]}"
    e = subprocess.run([sys.executable, "-I", str(HERE / "evaluate_po.py"), tid], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return tid, f"{(time.time() - t0) / 60:.1f} min | {e.stdout.strip() or e.stderr[-800:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--reps", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--conds", default="base_po,sdd_po")
    a = ap.parse_args()
    lo, _, hi = a.reps.partition("-")
    combos = [(t, c, r) for r in range(int(lo), int(hi or lo) + 1) for t in a.tasks.split(",") for c in a.conds.split(",")]
    with ThreadPoolExecutor(a.jobs) as ex:
        for f in as_completed([ex.submit(one, t, c, r, a.model) for t, c, r in combos]):
            tid, msg = f.result()
            print(f"[{time.strftime('%H:%M:%S')}] {tid}: {msg}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
