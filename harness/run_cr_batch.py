"""Серия прогонов эксперимента 2 поверх готовых прогонов этапа 1.

python -I run_cr_batch.py --model sonnet --tag v2 --jobs 4 [--tasks t1_promo,...]
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
META1 = HERE.parent / "runs"
META_CR = HERE.parent / "runs_cr"


def one(tid):
    if (META_CR / tid / "eval.json").exists():
        return tid, "skip"
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", str(HERE / "run_cr.py"), tid], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return tid, f"RUN FAIL {r.stderr[-800:]}"
    e = subprocess.run([sys.executable, "-I", str(HERE / "evaluate_cr.py"), tid], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return tid, f"{(time.time() - t0) / 60:.1f} min | {e.stdout.strip() or e.stderr[-800:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--tag", default="v2")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    tasks = set(filter(None, a.tasks.split(",")))
    ids = []
    for p in sorted(META1.iterdir()):
        if not (p / "eval.json").exists():
            continue
        e = json.loads((p / "eval.json").read_text(encoding="utf-8"))
        if e["model"] == a.model and e.get("tag") == a.tag and (not tasks or e["task"] in tasks):
            ids.append(p.name)
    with ThreadPoolExecutor(a.jobs) as ex:
        for f in as_completed([ex.submit(one, t) for t in ids]):
            tid, msg = f.result()
            print(f"[{time.strftime('%H:%M:%S')}] {tid}: {msg}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
