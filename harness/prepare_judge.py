"""Готовит обезличенные наборы правок для слепой экспертной оценки.

Для каждой задачи берутся все оценённые прогоны эксперимента 1 указанной модели, их agent.diff
(без каталога openspec/) перемешиваются и получают буквы A, B, C, ... Таблица соответствия
пишется отдельно (в каталог harness/_private), эксперт её не видит.

Запуск: python -I prepare_judge.py [--model sonnet]
"""
import json
import random
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
OUT = EXP / "results" / "judge_input"
PRIVATE = HERE / "_private"


def scrub(diff):
    # Убираем явные упоминания методики, чтобы не раскрывать условие эксперта.
    return re.sub(r"(?i)open\s?spec|opsx|tasks\.md|proposal\.md|design\.md", "[...]", diff)


def main():
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "sonnet"
    rng = random.Random(2026)
    mapping = {}
    if OUT.exists():
        shutil.rmtree(OUT)
    for task_dir in sorted((EXP / "tasks").iterdir()):
        task = task_dir.name
        runs = []
        for p in sorted((EXP / "runs").glob(f"{task}__*__{model}__v2")):
            if (p / "eval.json").exists() and (p / "agent.diff").exists():
                runs.append(p.name)
        rng.shuffle(runs)
        dst = OUT / task
        dst.mkdir(parents=True)
        shutil.copytree(task_dir / "repo", dst / "project_before", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copy(task_dir / "ticket.md", dst / "ticket.md")
        for i, tid in enumerate(runs):
            letter = chr(ord("A") + i)
            (dst / f"{letter}.diff").write_text(scrub((EXP / "runs" / tid / "agent.diff").read_text(encoding="utf-8")), encoding="utf-8")
            mapping[f"{task}/{letter}"] = tid
        print(task, len(runs))
    PRIVATE.mkdir(exist_ok=True)
    (PRIVATE / "judge_map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
