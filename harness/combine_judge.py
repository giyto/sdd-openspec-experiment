"""Сводит оценки экспертов (judge_output/<task>.json) с таблицей соответствия в results/judge_scores.json."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
mapping = json.loads((HERE / "_private" / "judge_map.json").read_text(encoding="utf-8"))
scores = {}
for f in sorted((RES / "judge_output").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    for letter, sc in data.items():
        tid = mapping.get(f"{f.stem}/{letter}")
        if tid:
            scores[tid] = sc
(RES / "judge_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
print(len(scores), "оценок")
