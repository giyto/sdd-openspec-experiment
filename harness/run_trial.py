"""Один прогон эксперимента: задача x условие x повтор.

Условия:
  baseline — агент получает тикет и сразу выполняет задачу (одна сессия);
  sdd      — OpenSpec: сессия 1 пишет proposal/specs/design/tasks по тикету,
             сессия 2 (чистый контекст) реализует изменение по артефактам.

Обе ветки: одна и та же модель, --safe-mode (без пользовательских CLAUDE.md,
скиллов, MCP, хуков), один набор инструментов, без доступа к сети.

Запуск: python -I run_trial.py <task_id> <baseline|sdd> <rep> [--model sonnet]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
TASKS = EXP / "tasks"
PROMPTS = HERE / "prompts"
import tempfile
# Рабочие копии — вне каталога эксперимента, чтобы агент не мог дотянуться до скрытых тестов.
WORK_ROOT = Path(os.environ.get("SDD_WORK_ROOT", Path(tempfile.gettempdir()) / "sdd_runs"))
META_ROOT = EXP / "runs"
SESSION_TIMEOUT = 45 * 60
BUDGET_USD = "15"

AUTONOMY_NOTE = (
    "Ты работаешь автономно: пользователь недоступен и на вопросы не ответит. "
    "Если что-то неоднозначно, прими разумное решение и продолжай."
)


def sh(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=isinstance(cmd, str))
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {r.stdout}\n{r.stderr}")
    return r


def strip_frontmatter(text):
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def claude(prompt, cwd, model, log_path):
    cmd = [
        shutil.which("claude"), "-p", prompt,
        "--model", model,
        "--safe-mode", "--disable-slash-commands",
        "--tools", "Bash,Read,Edit,Write,Glob,Grep",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence",
        "--max-budget-usd", BUDGET_USD,
    ]
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            p = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=SESSION_TIMEOUT)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    wall = time.time() - t0
    result = None
    for line in open(log_path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "result":
            result = e
    return {
        "rc": rc,
        "wall_s": round(wall, 1),
        "cost_usd": (result or {}).get("total_cost_usd"),
        "duration_ms": (result or {}).get("duration_ms"),
        "num_turns": (result or {}).get("num_turns"),
        "usage": (result or {}).get("usage"),
        "subtype": (result or {}).get("subtype"),
        "final_text": (result or {}).get("result"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("condition", choices=["baseline", "sdd", "sdd_rules"])
    ap.add_argument("rep", type=int)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--ticket", default="ticket.md", help="файл тикета в каталоге задачи")
    ap.add_argument("--tag", default="v2", help="метка версии тикета в id прогона")
    a = ap.parse_args()

    task_dir = TASKS / a.task
    ticket = (task_dir / a.ticket).read_text(encoding="utf-8").strip()
    trial_id = f"{a.task}__{a.condition}__r{a.rep}__{a.model}__{a.tag}"
    # Каталог прогона с нейтральным именем, чтобы путь не подсказывал агенту условие.
    work = WORK_ROOT / uuid.uuid4().hex[:10]
    meta_dir = META_ROOT / trial_id
    if meta_dir.exists():
        shutil.rmtree(meta_dir)
    meta_dir.mkdir(parents=True)
    repo = work / "project"
    shutil.copytree(task_dir / "repo", repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))

    if a.condition in ("sdd", "sdd_rules"):
        sh([shutil.which("openspec"), "init", "--tools", "none", "--no-animation", "."], cwd=repo)
    if a.condition == "sdd_rules":
        # Разведочный вариант: правила проекта OpenSpec о сохранении публичного API из задачи.
        shutil.copy(PROMPTS / "openspec_rules.yaml", repo / "openspec" / "config.yaml")

    sh("git init -q && git add -A && git -c user.name=exp -c user.email=exp@local commit -qm base", cwd=repo)
    base = sh("git rev-parse HEAD", cwd=repo).stdout.strip()

    sessions = []
    if a.condition == "baseline":
        prompt = f"Выполни задачу из тикета ниже в текущем репозитории.\n\n<ticket>\n{ticket}\n</ticket>\n\n{AUTONOMY_NOTE} Доведи задачу до конца в этой сессии."
        sessions.append(("impl", claude(prompt, repo, a.model, meta_dir / "log_impl.jsonl")))
    else:
        propose = strip_frontmatter((PROMPTS / "propose.md").read_text(encoding="utf-8"))
        prompt1 = (
            f"{propose}\n\n---\n\n**Input (ARGUMENTS):**\n\n<ticket>\n{ticket}\n</ticket>\n\n"
            f"{AUTONOMY_NOTE} Не задавай вопросов: неоднозначности фиксируй как допущения в артефактах. "
            "Создай все артефакты и проверь их командой `openspec validate`. Код проекта в этой сессии не меняй."
        )
        sessions.append(("propose", claude(prompt1, repo, a.model, meta_dir / "log_propose.jsonl")))
        lst = sh([shutil.which("openspec"), "list", "--json"], cwd=repo, check=False).stdout
        try:
            changes = [c["name"] for c in json.loads(lst).get("changes", [])]
        except Exception:
            changes = []
        change = changes[0] if changes else ""
        apply_ = strip_frontmatter((PROMPTS / "apply.md").read_text(encoding="utf-8"))
        prompt2 = (
            f"{apply_}\n\n---\n\n**Input (ARGUMENTS):** {change}\n\n"
            f"{AUTONOMY_NOTE} Не останавливайся, чтобы задать вопрос: если задача неясна, реши в духе спецификации, "
            "запиши решение в design.md и продолжай. Выполни все задачи из tasks.md в этой сессии."
        )
        sessions.append(("apply", claude(prompt2, repo, a.model, meta_dir / "log_apply.jsonl")))
        if (repo / "openspec").exists():
            shutil.copytree(repo / "openspec", meta_dir / "openspec_artifacts", dirs_exist_ok=True)

    info = {
        "trial_id": trial_id, "task": a.task, "condition": a.condition, "rep": a.rep, "model": a.model, "tag": a.tag, "ticket_file": a.ticket,
        "work_dir": str(work), "repo": str(repo), "base_commit": base,
        "sessions": [{"phase": ph, **res} for ph, res in sessions],
    }
    (meta_dir / "trial.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("trial_id", "repo")}, ensure_ascii=False))
    print("cost", [s.get("cost_usd") for _, s in sessions], "rc", [s.get("rc") for _, s in sessions])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
