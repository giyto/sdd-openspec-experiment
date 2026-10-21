"""Эксперимент 3: неполная постановка и один раунд обратной связи от владельца продукта (PO).

Условия (в обоих ровно три сессии агента-разработчика/PO и один раунд замечаний):
  sdd_po  — propose по ticket_po.md → PO читает артефакты OpenSpec → apply с учётом замечаний;
  base_po — реализация по ticket_po.md с отчётом о допущениях → PO читает отчёт → исправление кода.

PO — отдельная сессия без инструментов, всегда одной и той же модели (PO_MODEL), со списком решений
po_decisions.md. Он комментирует только то, что явно написано в документе.

Запуск: python -I run_po.py <task_id> <sdd_po|base_po> <rep> [--model sonnet]
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_trial as rt  # noqa: E402

META_PO = rt.EXP / "runs_po"
PO_MODEL = "sonnet"

PO_PROMPT = """Ты владелец продукта (product owner). Разработчик прислал тебе документ по задаче, чтобы ты проверил,
правильно ли он понял, что нужно сделать. Код ты не читаешь, только этот документ.

Ниже твои решения по задаче: ты знаешь их, а разработчик их не знает (в тикете их не было).

<решения>
{decisions}
</решения>

Правила ответа:
- Комментируй только то, что явно написано в документе. Если написанное расходится с твоим решением,
  коротко поправь: что не так и как должно быть.
- Если о каком-то решении в документе ничего не сказано, ничего о нём не пиши: ты реагируешь на документ,
  а не пересказываешь свой список.
- Не комментируй то, с чем ты согласен, и не давай советов по реализации.
- Ответ: нумерованный список замечаний. Если замечаний нет, ответь одной строкой: «Замечаний нет».

<документ разработчика>
{document}
</документ разработчика>
"""


def po_review(decisions, document, log_path):
    prompt = PO_PROMPT.format(decisions=decisions, document=document)
    # Текст передаётся через stdin: длинная спецификация не помещается в командную строку Windows.
    cmd = [shutil.which("claude"), "-p", "--model", PO_MODEL, "--safe-mode", "--disable-slash-commands",
           "--tools", "", "--output-format", "json", "--no-session-persistence"]
    rt.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=rt.WORK_ROOT, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    Path(log_path).write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    try:
        res = json.loads(r.stdout)
    except json.JSONDecodeError:
        res = {}
    return {"rc": r.returncode, "wall_s": round(time.time() - t0, 1), "cost_usd": res.get("total_cost_usd"),
            "num_turns": res.get("num_turns"), "usage": res.get("usage"), "subtype": res.get("subtype"),
            "final_text": res.get("result") or ""}


def change_document(repo):
    """Склеивает артефакты активного change OpenSpec в один документ для PO."""
    changes = repo / "openspec" / "changes"
    parts = []
    for ch in sorted(p for p in changes.iterdir() if p.is_dir() and p.name != "archive") if changes.exists() else []:
        for f in sorted(ch.rglob("*.md")):
            parts.append(f"### {f.relative_to(ch).as_posix()}\n\n{f.read_text(encoding='utf-8', errors='replace')}")
    return "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("condition", choices=["sdd_po", "base_po", "sdd_po_rules", "plan_po"])
    ap.add_argument("rep", type=int)
    ap.add_argument("--model", default="sonnet")
    a = ap.parse_args()

    task_dir = rt.TASKS / a.task
    ticket = (task_dir / "ticket_po.md").read_text(encoding="utf-8").strip()
    decisions = (task_dir / "po_decisions.md").read_text(encoding="utf-8").strip()
    trial_id = f"{a.task}__{a.condition}__r{a.rep}__{a.model}__po"
    meta_dir = META_PO / trial_id
    if meta_dir.exists():
        shutil.rmtree(meta_dir)
    meta_dir.mkdir(parents=True)
    work = rt.WORK_ROOT / uuid.uuid4().hex[:10]
    repo = work / "project"
    shutil.copytree(task_dir / "repo", repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if a.condition in ("sdd_po", "sdd_po_rules"):
        rt.sh([shutil.which("openspec"), "init", "--tools", "none", "--no-animation", "."], cwd=repo)
    if a.condition == "sdd_po_rules":
        shutil.copy(rt.PROMPTS / "openspec_rules.yaml", repo / "openspec" / "config.yaml")
    rt.sh("git init -q && git add -A && git -c user.name=exp -c user.email=exp@local commit -qm base", cwd=repo)
    base = rt.sh("git rev-parse HEAD", cwd=repo).stdout.strip()

    sessions = []
    if a.condition in ("sdd_po", "sdd_po_rules"):
        propose = rt.strip_frontmatter((rt.PROMPTS / "propose.md").read_text(encoding="utf-8"))
        p1 = (f"{propose}\n\n---\n\n**Input (ARGUMENTS):**\n\n<ticket>\n{ticket}\n</ticket>\n\n"
              f"{rt.AUTONOMY_NOTE} Не задавай вопросов: неоднозначности фиксируй как допущения в артефактах. "
              "Создай все артефакты и проверь их командой `openspec validate`. Код проекта в этой сессии не меняй.")
        sessions.append(("propose", rt.claude(p1, repo, a.model, meta_dir / "log_propose.jsonl")))
        doc = change_document(repo)
        (meta_dir / "po_input.md").write_text(doc, encoding="utf-8")
        po = po_review(decisions, doc, meta_dir / "log_po.json")
        sessions.append(("po", po))
        lst = rt.sh([shutil.which("openspec"), "list", "--json"], cwd=repo, check=False).stdout
        try:
            change = [c["name"] for c in json.loads(lst).get("changes", [])][0]
        except Exception:
            change = ""
        apply_ = rt.strip_frontmatter((rt.PROMPTS / "apply.md").read_text(encoding="utf-8"))
        p2 = (f"{apply_}\n\n---\n\n**Input (ARGUMENTS):** {change}\n\n"
              f"Владелец продукта прочитал артефакты этого change и оставил замечания:\n\n<замечания>\n{po['final_text']}\n</замечания>\n\n"
              "Сначала приведи артефакты (proposal, specs, design, tasks) в соответствие с замечаниями, затем реализуй все задачи. "
              f"{rt.AUTONOMY_NOTE} Не останавливайся, чтобы задать вопрос: если задача неясна, реши в духе спецификации, "
              "запиши решение в design.md и продолжай.")
        sessions.append(("apply", rt.claude(p2, repo, a.model, meta_dir / "log_apply.jsonl")))
        if (repo / "openspec").exists():
            shutil.copytree(repo / "openspec", meta_dir / "openspec_artifacts", dirs_exist_ok=True)
    elif a.condition == "plan_po":
        # Контрольное условие по замечанию рецензента: согласование до кода, но без OpenSpec.
        # План свободным текстом → замечания владельца → реализация в новой сессии (она видит и тикет, и план).
        p1 = (f"Ниже тикет на доработку текущего репозитория. Сначала изучи проект и составь план реализации. "
              f"Код проекта в этой сессии не меняй.\n\n<ticket>\n{ticket}\n</ticket>\n\n"
              "Запиши план в файл PLAN.md в корне репозитория: что и где будет изменено, и отдельным списком все решения и "
              "допущения, которые ты принимаешь там, где тикет не даёт однозначного ответа. "
              f"{rt.AUTONOMY_NOTE} Не задавай вопросов, допущения фиксируй в плане.")
        sessions.append(("plan", rt.claude(p1, repo, a.model, meta_dir / "log_plan.jsonl")))
        plan_path = repo / "PLAN.md"
        doc = plan_path.read_text(encoding="utf-8", errors="replace") if plan_path.exists() else ""
        (meta_dir / "po_input.md").write_text(doc, encoding="utf-8")
        po = po_review(decisions, doc, meta_dir / "log_po.json")
        sessions.append(("po", po))
        p2 = (f"Выполни задачу из тикета ниже в текущем репозитории. Перед этим был составлен план реализации (файл PLAN.md "
              f"в корне репозитория), и владелец продукта оставил к нему замечания. Сначала поправь план по замечаниям, затем "
              f"реализуй задачу.\n\n<ticket>\n{ticket}\n</ticket>\n\n<замечания>\n{po['final_text']}\n</замечания>\n\n"
              f"{rt.AUTONOMY_NOTE} Доведи задачу до конца в этой сессии.")
        sessions.append(("impl", rt.claude(p2, repo, a.model, meta_dir / "log_impl.jsonl")))
    else:
        p1 = (f"Выполни задачу из тикета ниже в текущем репозитории.\n\n<ticket>\n{ticket}\n</ticket>\n\n"
              f"{rt.AUTONOMY_NOTE} Доведи задачу до конца в этой сессии. В конце работы напиши отчёт для владельца продукта: "
              "что сделано и какие решения и допущения ты принял там, где тикет не давал однозначного ответа.")
        s1 = rt.claude(p1, repo, a.model, meta_dir / "log_impl.jsonl")
        sessions.append(("impl", s1))
        doc = s1.get("final_text") or ""
        (meta_dir / "po_input.md").write_text(doc, encoding="utf-8")
        po = po_review(decisions, doc, meta_dir / "log_po.json")
        sessions.append(("po", po))
        p2 = (f"Ранее в этом репозитории была выполнена задача по тикету ниже. Владелец продукта прочитал отчёт о сделанной работе "
              f"и оставил замечания. Внеси в код исправления по замечаниям.\n\n<ticket>\n{ticket}\n</ticket>\n\n"
              f"<отчёт разработчика>\n{doc}\n</отчёт разработчика>\n\n<замечания>\n{po['final_text']}\n</замечания>\n\n"
              f"{rt.AUTONOMY_NOTE} Доведи исправления до конца в этой сессии.")
        sessions.append(("fix", rt.claude(p2, repo, a.model, meta_dir / "log_fix.jsonl")))

    info = {"trial_id": trial_id, "task": a.task, "condition": a.condition, "rep": a.rep, "model": a.model,
            "tag": "po", "work_dir": str(work), "repo": str(repo), "base_commit": base,
            "po_comments": po["final_text"],
            "sessions": [{"phase": ph, **res} for ph, res in sessions]}
    (meta_dir / "trial.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(trial_id, "cost", [s.get("cost_usd") for _, s in sessions])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
