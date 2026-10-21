"""Оценка прогона эксперимента 2 (CR в новой сессии).

Метрики:
  cr_pass_rate / cr_req_satisfied  выполнение нового запроса (скрытые тесты CR)
  preserved_rate   доля тестов этапа 1, которые CR не отменял и которые проходили после этапа 1,
                   и всё ещё проходят после CR («старое не сломано»)
  stage1_valid_pass_rate  доля всех неотменённых тестов этапа 1, проходящих после CR
  regress_rate     исходные тесты проекта
  protected_touched, foreign_deps, prod_loc, cc, стоимость
Запуск: python -I evaluate_cr.py <stage1_trial_id> | --all
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev  # noqa: E402

META_CR = ev.EXP / "runs_cr"


def hidden_results(repo, src_dir, dst_name, xml):
    dst = repo / dst_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src_dir, dst)
    res, out = ev.pytest_junit(repo, dst_name, xml)
    shutil.rmtree(dst, ignore_errors=True)
    # Ключ — полный id теста (параметризованные варианты не схлопываются), имя функции — для привязки.
    return {full: (name, ok) for full, (name, ok) in res.items()} if res else {}, out


def evaluate(stage1_id):
    meta_dir = META_CR / stage1_id
    info = json.loads((meta_dir / "trial.json").read_text(encoding="utf-8"))
    repo, repo1 = Path(info["repo"]), Path(info["stage1_repo"])
    task_dir = ev.TASKS / info["task"]
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    cr_meta = json.loads((task_dir / "cr_meta.json").read_text(encoding="utf-8"))
    cr_reqs = json.loads((task_dir / "cr_requirements.json").read_text(encoding="utf-8"))
    invalid = set(cr_meta.get("invalidated_stage1_tests", []))
    protected = set(meta.get("protected_paths", [])) | set(cr_meta.get("protected_paths", []))
    pkg, base = meta["package"], info["base_commit"]

    ev.run("git add -A", repo)
    numstat = ev.run(["git", "diff", "--cached", "--numstat", base], repo).stdout
    changed = []
    for line in numstat.splitlines():
        a, d, f = line.split("\t", 2)
        changed.append((f, int(a) if a != "-" else 0, int(d) if d != "-" else 0))
    (meta_dir / "agent.diff").write_text(
        ev.run(["git", "diff", "--cached", base, "--", ".", ":(exclude)openspec"], repo).stdout, encoding="utf-8")
    prod = [(f, a, d) for f, a, d in changed if f.startswith(pkg + "/")]
    prod_files = [f for f, _, _ in prod]
    protected_touched = [f for f, _, _ in changed if ev.is_protected(f, protected)]
    funcs = ev.changed_functions(repo, base, prod_files)
    ccs = [x["cc"] for x in funcs if x.get("cc") is not None]

    # Тесты CR.
    cr_res, cr_out = hidden_results(repo, task_dir / "hidden_tests_cr", "tests_hidden_cr", "_cr.xml")
    per_req = {r["id"]: [] for r in cr_reqs}
    explicit = {t: r["id"] for r in cr_reqs for t in r.get("tests", [])}
    for name, ok in cr_res.values():
        m = re.match(r"test_(C\d+)_", name)
        rid = explicit.get(name) or (m.group(1) if m else None)
        if rid in per_req:
            per_req[rid].append(ok)
    for r in cr_reqs:
        if not per_req[r["id"]] and r.get("kind") == "constraint":
            per_req[r["id"]].append(not protected_touched and not ev.foreign_imports(repo, prod_files))
    cr_status = {k: (all(v) if v else None) for k, v in per_req.items()}

    # Тесты этапа 1: до CR (на репозитории этапа 1) и после CR.
    s1_after, _ = hidden_results(repo, task_dir / "hidden_tests", "tests_hidden", "_s1a.xml")
    s1_before, _ = hidden_results(repo1, task_dir / "hidden_tests", "tests_hidden", "_s1b.xml")
    valid_after = {f: ok for f, (n, ok) in s1_after.items() if n not in invalid}
    was_ok = [f for f, (n, ok) in s1_before.items() if ok and n not in invalid]
    preserved = [n for n in was_ok if valid_after.get(n)]
    broken = sorted(set(was_ok) - set(preserved))

    rdst = repo / "tests_regress"
    if rdst.exists():
        shutil.rmtree(rdst)
    shutil.copytree(task_dir / "repo" / "tests", rdst, ignore=shutil.ignore_patterns("__pycache__"))
    regress, _ = ev.pytest_junit(repo, "tests_regress", "_regress.xml")
    shutil.rmtree(rdst, ignore_errors=True)
    ev.run("git reset -q", repo)

    sessions = info["sessions"]
    def ssum(k):
        v = [s.get(k) for s in sessions if s.get(k) is not None]
        return round(sum(v), 4) if v else None
    out_tokens = sum((s.get("usage") or {}).get("output_tokens", 0) for s in sessions)

    res = {
        "trial_id": stage1_id, "stage": "cr", "task": info["task"], "condition": info["condition"],
        "rep": info["rep"], "model": info["model"], "tag": info.get("tag"),
        "cr_total": len(cr_res), "cr_passed": sum(ok for _, ok in cr_res.values()),
        "cr_pass_rate": round(sum(ok for _, ok in cr_res.values()) / len(cr_res), 4) if cr_res else 0.0,
        "cr_req_total": len(cr_reqs), "cr_req_satisfied": sum(1 for v in cr_status.values() if v), "cr_req_status": cr_status,
        "stage1_was_ok": len(was_ok), "stage1_preserved": len(preserved),
        "preserved_rate": round(len(preserved) / len(was_ok), 4) if was_ok else None,
        "stage1_broken_tests": broken,
        "stage1_valid_total": len(valid_after), "stage1_valid_passed": sum(valid_after.values()),
        "stage1_valid_pass_rate": round(sum(valid_after.values()) / len(valid_after), 4) if valid_after else None,
        "regress_total": len(regress), "regress_passed": sum(ok for _, ok in regress.values()),
        "protected_touched": protected_touched, "foreign_deps": ev.foreign_imports(repo, prod_files),
        "prod_loc": sum(a + d for _, a, d in prod), "files_changed": [f for f, _, _ in changed if not f.startswith("openspec/")],
        "cc_mean": round(sum(ccs) / len(ccs), 2) if ccs else None,
        "cost_usd": ssum("cost_usd"), "wall_s": ssum("wall_s"), "num_turns": ssum("num_turns"), "output_tokens": out_tokens,
        "session_subtypes": [s.get("subtype") for s in sessions],
        "cr_out_tail": cr_out[-1500:],
    }
    (meta_dir / "eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ids = [p.name for p in META_CR.iterdir() if (p / "trial.json").exists()] if sys.argv[1] == "--all" else sys.argv[1:]
    for t in ids:
        r = evaluate(t)
        print(f"{t}: CR {r['cr_passed']}/{r['cr_total']} req {r['cr_req_satisfied']}/{r['cr_req_total']} "
              f"preserved {r['stage1_preserved']}/{r['stage1_was_ok']} regress {r['regress_passed']}/{r['regress_total']} "
              f"protected {r['protected_touched']} cost {r['cost_usd']}")
