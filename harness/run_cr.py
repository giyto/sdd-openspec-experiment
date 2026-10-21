"""Эксперимент 2: запрос на изменение (CR) в новой сессии поверх результата этапа 1.

Берёт итоговое состояние репозитория прогона этапа 1 и продолжает ту же линию:
  baseline — одна новая сессия с текстом CR; у агента есть только код;
  sdd      — change этапа 1 архивируется в основные specs (штатный шаг OpenSpec после
             реализации), затем propose → apply для CR в двух новых сессиях.

Запуск: python -I run_cr.py <stage1_trial_id>
"""
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_trial as rt  # noqa: E402

META_CR = rt.EXP / "runs_cr"


def main(stage1_id):
    info1 = json.loads((rt.META_ROOT / stage1_id / "trial.json").read_text(encoding="utf-8"))
    task_dir = rt.TASKS / info1["task"]
    cr_ticket = (task_dir / "cr_ticket.md").read_text(encoding="utf-8").strip()
    meta_dir = META_CR / stage1_id
    if meta_dir.exists():
        shutil.rmtree(meta_dir)
    meta_dir.mkdir(parents=True)

    work = rt.WORK_ROOT / uuid.uuid4().hex[:10]
    repo = work / "project"
    shutil.copytree(info1["repo"], repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests_hidden*", "tests_regress", "_*.xml"))
    rt.sh("git add -A && git -c user.name=exp -c user.email=exp@local commit -qm stage1 --allow-empty", cwd=repo)

    archive_log = ""
    if info1["condition"] in ("sdd", "sdd_rules"):
        lst = rt.sh([shutil.which("openspec"), "list", "--json"], cwd=repo, check=False).stdout
        try:
            changes = [c["name"] for c in json.loads(lst).get("changes", [])]
        except Exception:
            changes = []
        for ch in changes:
            r = rt.sh([shutil.which("openspec"), "archive", ch, "--yes"], cwd=repo, check=False)
            archive_log += f"$ openspec archive {ch} --yes\n{r.stdout}\n{r.stderr}\n"
        rt.sh("git add -A && git -c user.name=exp -c user.email=exp@local commit -qm archive --allow-empty", cwd=repo)
    (meta_dir / "archive.log").write_text(archive_log, encoding="utf-8")
    base = rt.sh("git rev-parse HEAD", cwd=repo).stdout.strip()

    model = info1["model"]
    sessions = []
    if info1["condition"] == "baseline":
        prompt = f"Выполни задачу из тикета ниже в текущем репозитории.\n\n<ticket>\n{cr_ticket}\n</ticket>\n\n{rt.AUTONOMY_NOTE} Доведи задачу до конца в этой сессии."
        sessions.append(("impl", rt.claude(prompt, repo, model, meta_dir / "log_impl.jsonl")))
    else:
        propose = rt.strip_frontmatter((rt.PROMPTS / "propose.md").read_text(encoding="utf-8"))
        prompt1 = (
            f"{propose}\n\n---\n\n**Input (ARGUMENTS):**\n\n<ticket>\n{cr_ticket}\n</ticket>\n\n"
            f"{rt.AUTONOMY_NOTE} Не задавай вопросов: неоднозначности фиксируй как допущения в артефактах. "
            "Создай все артефакты и проверь их командой `openspec validate`. Код проекта в этой сессии не меняй."
        )
        sessions.append(("propose", rt.claude(prompt1, repo, model, meta_dir / "log_propose.jsonl")))
        lst = rt.sh([shutil.which("openspec"), "list", "--json"], cwd=repo, check=False).stdout
        try:
            changes = [c["name"] for c in json.loads(lst).get("changes", [])]
        except Exception:
            changes = []
        change = changes[0] if changes else ""
        apply_ = rt.strip_frontmatter((rt.PROMPTS / "apply.md").read_text(encoding="utf-8"))
        prompt2 = (
            f"{apply_}\n\n---\n\n**Input (ARGUMENTS):** {change}\n\n"
            f"{rt.AUTONOMY_NOTE} Не останавливайся, чтобы задать вопрос: если задача неясна, реши в духе спецификации, "
            "запиши решение в design.md и продолжай. Выполни все задачи из tasks.md в этой сессии."
        )
        sessions.append(("apply", rt.claude(prompt2, repo, model, meta_dir / "log_apply.jsonl")))
        if (repo / "openspec").exists():
            shutil.copytree(repo / "openspec", meta_dir / "openspec_artifacts", dirs_exist_ok=True)

    info = {
        "trial_id": stage1_id, "stage": "cr", "task": info1["task"], "condition": info1["condition"],
        "rep": info1["rep"], "model": model, "tag": info1.get("tag"),
        "stage1_repo": info1["repo"], "work_dir": str(work), "repo": str(repo), "base_commit": base,
        "sessions": [{"phase": ph, **res} for ph, res in sessions],
    }
    (meta_dir / "trial.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(stage1_id, "cost", [s.get("cost_usd") for _, s in sessions], "rc", [s.get("rc") for _, s in sessions])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
