import io
import json

from warehouse import cli

SCENARIO = [
    {"op": "register", "sku": "BOLT-M8", "name": "Bolt"},
    {"op": "receive", "wh": "MAIN", "sku": "BOLT-M8", "qty": 10},
    {"op": "issue", "wh": "MAIN", "sku": "BOLT-M8", "qty": 3, "ref": "SO-1"},
]


def _write(tmp_path, operations):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(operations), encoding="utf-8")
    return path


def test_cli_prints_stock(tmp_path):
    out = io.StringIO()
    assert cli.main(["run", str(_write(tmp_path, SCENARIO))], out=out) == 0
    assert "MAIN       BOLT-M8  Bolt    7 pcs" in out.getvalue()


def test_cli_prints_log(tmp_path):
    out = io.StringIO()
    assert cli.main(["run", str(_write(tmp_path, SCENARIO)), "--show", "log"], out=out) == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[1].endswith("ISSUE qty=3 ref=SO-1 sku=BOLT-M8 wh=MAIN")


def test_cli_reports_error(tmp_path, capsys):
    bad = SCENARIO + [{"op": "issue", "wh": "MAIN", "sku": "BOLT-M8", "qty": 99}]
    assert cli.main(["run", str(_write(tmp_path, bad))], out=io.StringIO()) == 1
    assert "operation #4" in capsys.readouterr().err
