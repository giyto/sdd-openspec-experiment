import io
import json

from ledger.cli import main
from ledger.storage import JsonFileStore


def _run(argv, clock):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, clock=clock, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_import_and_report(tmp_path, write_csv, clock):
    store = tmp_path / "ledger.json"
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps([{"pattern": "кофе", "category": "cafe"}], ensure_ascii=False), encoding="utf-8")
    csv_path = write_csv("date,amount,description\n2026-03-01,-350.00,Кофейня\n2026-03-02,1000.00,Возврат\n")

    code, out, _ = _run(["--store", str(store), "import", str(csv_path), "--rules", str(rules)], clock)
    assert code == 0
    assert out.strip() == "Imported 2 transactions"
    assert len(JsonFileStore(store).all()) == 2

    code, out, _ = _run(["--store", str(store), "report", "2026-03"], clock)
    assert code == 0
    assert "cafe  -350.00" in out


def test_cli_list(tmp_path, write_csv, clock):
    store = tmp_path / "ledger.json"
    _run(["--store", str(store), "import", str(write_csv("date,amount,description\n2026-03-01,-5.00,Чай\n"))], clock)
    code, out, _ = _run(["--store", str(store), "list"], clock)
    assert code == 0
    assert "Чай" in out and "-5.00" in out


def test_cli_reports_errors(tmp_path, write_csv, clock):
    store = tmp_path / "ledger.json"
    code, _, err = _run(["--store", str(store), "import", str(write_csv("foo,bar\n1,2\n"))], clock)
    assert code == 1
    assert err.startswith("error:")
    code, _, err = _run(["--store", str(store), "report", "2026-13"], clock)
    assert code == 1
