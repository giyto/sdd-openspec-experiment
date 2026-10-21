"""Классификация упавших скрытых тестов: нарушение интерфейса или неверное поведение.

Интерфейс: тест падает с TypeError / AttributeError / ImportError / NameError при вызове API,
названного в тикете (неверная сигнатура, отсутствующее имя, иной тип аргумента), или на проверке
сигнатуры (inspect). Поведение: AssertionError или ожидаемое исключение не возникло.

Запуск: python -I classify_failures.py  → results/failure_classes.json
"""
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOTS = {"exp1": EXP / "runs", "exp3": EXP / "runs_po"}
IFACE = re.compile(r"^(TypeError|AttributeError|ImportError|ModuleNotFoundError|NameError)\b")


def classify(repo, task):
    dst = repo / "tests_hidden"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(EXP / "tasks" / task / "hidden_tests", dst)
    xml = repo / "_cls.xml"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests_hidden", f"--junitxml={xml}"],
                   cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    out = {"interface": [], "behavior": []}
    if xml.exists():
        for tc in ET.parse(xml).getroot().iter("testcase"):
            for ch in tc:
                if ch.tag in ("failure", "error"):
                    msg = (ch.get("message") or "").strip()
                    text = ch.text or ""
                    kind = "interface" if IFACE.match(msg) or "inspect.Parameter" in text or "signature" in msg.lower() else "behavior"
                    out[kind].append(tc.get("name"))
        xml.unlink()
    shutil.rmtree(dst, ignore_errors=True)
    return out


def rebuild_from_diff(meta_dir, task):
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="cls_")) / "project"
    shutil.copytree(EXP / "tasks" / task / "repo", tmp, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    # Как в исходном прогоне: репозиторий с базовым коммитом, затем применение diff.
    subprocess.run("git init -q && git add -A && git -c user.name=exp -c user.email=exp@local commit -qm base", cwd=tmp, shell=True)
    r = subprocess.run(["git", "apply", "--3way", "--ignore-whitespace", "--whitespace=nowarn", str(meta_dir / "agent.diff")],
                       cwd=tmp, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git apply failed for {meta_dir.name}: {r.stderr[:300]}")
    return tmp


def from_eval_tail(e):
    """Классификация по сохранённой сводке pytest из eval.json (строки «FAILED имя - Ошибка: …»).
    Сводка обрезана до последних строк; если видны не все упавшие тесты, остальные относятся
    к преобладающему среди видимых классу (в упавших прогонах все ошибки одного рода)."""
    lines = re.findall(r"FAILED \S+::(\w+)(?:\[[^\]]*\])? - ([^\n]*)", e.get("hidden_out_tail", ""))
    out = {"interface": [], "behavior": [], "source": "eval_tail"}
    for name, msg in lines:
        out["interface" if IFACE.match(msg.strip()) else "behavior"].append(name)
    failed = e["hidden_total"] - e["hidden_passed"]
    rest = failed - len(lines)
    if rest > 0:
        major = "interface" if len(out["interface"]) >= len(out["behavior"]) and out["interface"] else "behavior"
        out[major] += ["<не видно в сводке>"] * rest
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    result = {}
    for exp, root in ROOTS.items():
        for p in sorted(root.iterdir()):
            ef = p / "eval.json"
            if not ef.exists():
                continue
            e = json.loads(ef.read_text(encoding="utf-8"))
            if exp == "exp1" and e.get("tag", "v1") != "v2":
                continue  # пилот на тикетах первой версии в сводку не входит
            if e["hidden_passed"] == e["hidden_total"]:
                result[f"{exp}/{p.name}"] = {"interface": [], "behavior": [], "condition": e["condition"], "model": e["model"], "task": e["task"]}
                continue
            repo = Path(json.loads((p / "trial.json").read_text(encoding="utf-8"))["repo"])
            if repo.exists() and any(repo.iterdir()):
                c = classify(repo, e["task"])
            else:
                c = {"interface": [], "behavior": []}
            if len(c["interface"]) + len(c["behavior"]) != e["hidden_total"] - e["hidden_passed"]:
                # Рабочий каталог недоступен или изменился: восстанавливаем итоговый код агента
                # из сохранённого agent.diff поверх исходного проекта задачи.
                c = classify(rebuild_from_diff(p, e["task"]), e["task"])
                c["source"] = "agent.diff"
            c.update({"condition": e["condition"], "model": e["model"], "task": e["task"]})
            result[f"{exp}/{p.name}"] = c
            print(f"{exp}/{p.name}: interface {len(c['interface'])}, behavior {len(c['behavior'])}")
    (EXP / "results").mkdir(exist_ok=True)
    (EXP / "results" / "failure_classes.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    agg = {}
    for k, v in result.items():
        key = (k.split("/")[0], v["model"], v["condition"])
        a = agg.setdefault(key, {"runs": 0, "runs_with_iface": 0, "iface": 0, "behav": 0})
        a["runs"] += 1
        a["runs_with_iface"] += bool(v["interface"])
        a["iface"] += len(v["interface"])
        a["behav"] += len(v["behavior"])
    for k, a in sorted(agg.items()):
        print(k, a)


if __name__ == "__main__":
    main()
