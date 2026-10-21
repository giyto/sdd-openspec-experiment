"""Оценка одного прогона. Агент к этому моменту уже завершил работу.

Метрики:
  hidden_pass_rate   доля пройденных скрытых приёмочных тестов
  req_satisfied      доля требований, у которых прошли ВСЕ тесты
  regress_pass_rate  доля пройденных исходных тестов проекта (исходные версии файлов)
  protected_touched  изменённые файлы, которые тикет запрещал трогать
  foreign_deps       импорты не из stdlib в коде пакета
  prod_loc_added/removed, test_loc_added, new_test_funcs
  cc_mean/cc_max     цикломатическая сложность функций, изменённых агентом
  cost/время/ходы    из логов сессий

Запуск: python -I evaluate.py <trial_id> | --all
"""
import ast
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
TASKS = EXP / "tasks"
import os
META_ROOT = Path(os.environ.get("SDD_META_ROOT", EXP / "runs"))
STDLIB = set(sys.stdlib_module_names) | {"pytest", "_pytest"}


def run(cmd, cwd, timeout=600):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, shell=isinstance(cmd, str))


def pytest_junit(repo, target, xml_name):
    xml_path = repo / xml_name
    try:
        r = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target, f"--junitxml={xml_path}"], repo, timeout=900)
        out = r.stdout[-3000:]
    except subprocess.TimeoutExpired:
        return {}, "TIMEOUT"
    results = {}
    if xml_path.exists():
        root = ET.parse(xml_path).getroot()
        for tc in root.iter("testcase"):
            name = tc.get("name").split("[")[0]
            full = f"{tc.get('classname')}::{tc.get('name')}"
            ok = not any(ch.tag in ("failure", "error") for ch in tc) and not any(ch.tag == "skipped" for ch in tc)
            results[full] = (name, ok)
        xml_path.unlink()
    return results, out


def cyclomatic(fn):
    cc = 1
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.For, ast.While, ast.AsyncFor, ast.IfExp, ast.ExceptHandler, ast.Assert, ast.comprehension)):
            cc += 1
        elif isinstance(n, ast.BoolOp):
            cc += len(n.values) - 1
        elif isinstance(n, ast.Match):
            cc += len(n.cases)
    return cc


def changed_functions(repo, base, files):
    """Функции/методы в изменённых файлах пакета, тело которых изменилось относительно базы."""
    out = []
    for f in files:
        p = repo / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            new_tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            out.append({"file": f, "name": "<syntax error>", "cc": None})
            continue
        old_src = run(["git", "show", f"{base}:{f}"], repo).stdout
        old_funcs = {}
        try:
            for n in ast.walk(ast.parse(old_src)) if old_src else []:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    old_funcs[n.name + str(n.lineno)] = ast.dump(n)
        except SyntaxError:
            pass
        old_dumps = set(old_funcs.values())
        for n in ast.walk(new_tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.dump(n) not in old_dumps:
                length = (n.end_lineno or n.lineno) - n.lineno + 1
                out.append({"file": f, "name": n.name, "cc": cyclomatic(n), "len": length})
    return out


def foreign_imports(repo, files):
    bad = set()
    for f in files:
        p = repo / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        local = {x.name.split(".")[0] for x in repo.iterdir()} | {x.stem for x in repo.iterdir()}
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module]
            for m in mods:
                top = m.split(".")[0]
                if top not in STDLIB and top not in local:
                    bad.add(top)
    return sorted(bad)


def is_protected(path, protected):
    for pr in protected:
        pr = pr.rstrip("/")
        if path == pr or path.startswith(pr + "/"):
            return True
    return False


def evaluate(trial_id):
    meta_dir = META_ROOT / trial_id
    info = json.loads((meta_dir / "trial.json").read_text(encoding="utf-8"))
    repo = Path(info["repo"])
    task_dir = TASKS / info["task"]
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    reqs = json.loads((task_dir / "requirements.json").read_text(encoding="utf-8"))
    pkg = meta["package"]
    base = info["base_commit"]

    # Изменения агента: всё, включая неотслеживаемые файлы, относительно базового коммита.
    run("git add -A", repo)
    numstat = run(["git", "diff", "--cached", "--numstat", base], repo).stdout
    status = run(["git", "diff", "--cached", "--name-status", base], repo).stdout
    changed = []
    for line in numstat.splitlines():
        a, d, f = line.split("\t", 2)
        changed.append((f, int(a) if a != "-" else 0, int(d) if d != "-" else 0))
    patch = run(["git", "diff", "--cached", base, "--", ".", ":(exclude)openspec"], repo).stdout
    (meta_dir / "agent.diff").write_text(patch, encoding="utf-8")

    def kind(f):
        if f.startswith("openspec/"):
            return "spec"
        if f.startswith("tests/") or "/tests/" in f or Path(f).name.startswith("test_"):
            return "test"
        if f.startswith(pkg + "/"):
            return "prod"
        return "other"

    prod_files = [f for f, _, _ in changed if kind(f) == "prod"]
    protected_touched = [f for f, _, _ in changed if is_protected(f, meta.get("protected_paths", []))]
    loc = {"prod_added": 0, "prod_removed": 0, "test_added": 0, "spec_added": 0, "other_files": []}
    for f, a, d in changed:
        k = kind(f)
        if k == "prod":
            loc["prod_added"] += a
            loc["prod_removed"] += d
        elif k == "test":
            loc["test_added"] += a
        elif k == "spec":
            loc["spec_added"] += a
        else:
            loc["other_files"].append(f)

    new_test_funcs = 0
    for f, _, _ in changed:
        if kind(f) == "test" and (repo / f).exists() and f.endswith(".py"):
            new_src = (repo / f).read_text(encoding="utf-8", errors="replace")
            old_src = run(["git", "show", f"{base}:{f}"], repo).stdout
            new_test_funcs += len(re.findall(r"^\s*def test_", new_src, re.M)) - len(re.findall(r"^\s*def test_", old_src, re.M))

    funcs = changed_functions(repo, base, prod_files)
    ccs = [x["cc"] for x in funcs if x.get("cc") is not None]

    # Скрытые тесты.
    hidden_dst = repo / "tests_hidden"
    if hidden_dst.exists():
        shutil.rmtree(hidden_dst)
    shutil.copytree(task_dir / "hidden_tests", hidden_dst)
    hidden, hidden_out = pytest_junit(repo, "tests_hidden", "_hidden.xml")
    shutil.rmtree(hidden_dst, ignore_errors=True)

    req_ids = [r["id"] for r in reqs]
    per_req = {rid: [] for rid in req_ids}
    api_tests = []
    # Привязка тестов к требованиям: по полю "tests" в requirements.json, иначе по префиксу test_RNN_.
    explicit = {t: r["id"] for r in reqs for t in r.get("tests", [])}
    for full, (name, ok) in hidden.items():
        m = re.match(r"test_(R\d+)_", name)
        if name.startswith("test_API"):
            api_tests.append(ok)
        if name in explicit:
            per_req[explicit[name]].append(ok)
        elif m and m.group(1) in per_req:
            per_req[m.group(1)].append(ok)
    # Требования-ограничения без своих тестов: выполнены, если не тронуты защищённые файлы,
    # нет сторонних зависимостей и прошли все тесты совместимости API.
    for r in reqs:
        if not per_req[r["id"]] and r.get("kind") == "constraint":
            per_req[r["id"]].append(not protected_touched and not foreign_imports(repo, prod_files) and all(api_tests))
    req_status = {rid: (all(v) if v else None) for rid, v in per_req.items()}
    total_hidden = len(hidden)
    passed_hidden = sum(ok for _, ok in hidden.values())

    # Регрессия: исходные тесты проекта в исходном виде.
    regress_dst = repo / "tests_regress"
    if regress_dst.exists():
        shutil.rmtree(regress_dst)
    shutil.copytree(task_dir / "repo" / "tests", regress_dst, ignore=shutil.ignore_patterns("__pycache__"))
    regress, regress_out = pytest_junit(repo, "tests_regress", "_regress.xml")
    shutil.rmtree(regress_dst, ignore_errors=True)

    # Тесты, которые написал агент (весь каталог tests/ в его версии).
    own, _ = pytest_junit(repo, "tests", "_own.xml")
    run("git reset -q", repo)

    sessions = info["sessions"]
    def ssum(key):
        vals = [s.get(key) for s in sessions if s.get(key) is not None]
        return round(sum(vals), 4) if vals else None
    usage_tot = {}
    for s in sessions:
        for k, v in (s.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                usage_tot[k] = usage_tot.get(k, 0) + v

    res = {
        "trial_id": trial_id, "task": info["task"], "condition": info["condition"], "rep": info["rep"], "model": info["model"], "tag": info.get("tag", "v1"),
        "hidden_total": total_hidden, "hidden_passed": passed_hidden,
        "hidden_pass_rate": round(passed_hidden / total_hidden, 4) if total_hidden else 0.0,
        "req_total": len(req_ids),
        "req_satisfied": sum(1 for v in req_status.values() if v),
        "req_status": req_status,
        "api_compat_pass": (sum(api_tests), len(api_tests)),
        "regress_total": len(regress), "regress_passed": sum(ok for _, ok in regress.values()),
        "own_tests_total": len(own), "own_tests_passed": sum(ok for _, ok in own.values()),
        "protected_touched": protected_touched,
        "foreign_deps": foreign_imports(repo, prod_files),
        "files_changed": [f for f, _, _ in changed if kind(f) != "spec"],
        "loc": loc, "new_test_funcs": new_test_funcs,
        "changed_funcs": len(funcs), "cc_mean": round(sum(ccs) / len(ccs), 2) if ccs else None,
        "cc_max": max(ccs) if ccs else None, "funcs_cc_gt10": sum(1 for c in ccs if c > 10),
        "cost_usd": ssum("cost_usd"), "wall_s": ssum("wall_s"), "num_turns": ssum("num_turns"),
        "output_tokens": usage_tot.get("output_tokens"),
        "input_tokens_total": sum(usage_tot.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        "session_rcs": [s.get("rc") for s in sessions], "session_subtypes": [s.get("subtype") for s in sessions],
        "hidden_by_func": {n: [ok for _, (nn, ok) in hidden.items() if nn == n] for n in sorted({nn for _, (nn, _o) in hidden.items()})},
        "hidden_out_tail": hidden_out[-1500:],
    }
    (meta_dir / "eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ids = [p.name for p in META_ROOT.iterdir() if (p / "trial.json").exists()] if sys.argv[1] == "--all" else sys.argv[1:]
    for t in ids:
        r = evaluate(t)
        print(f"{t}: hidden {r['hidden_passed']}/{r['hidden_total']} req {r['req_satisfied']}/{r['req_total']} "
              f"regress {r['regress_passed']}/{r['regress_total']} protected {r['protected_touched']} cost {r['cost_usd']}")
