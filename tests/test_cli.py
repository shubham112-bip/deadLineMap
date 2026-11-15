import json
from pathlib import Path
from deadlinemap.cli import main

FIXTURES = Path(__file__).parent / "fixtures"

def test_text_scan(capsys):
    code = main(["scan", str(FIXTURES / "keepalive-mismatch")])
    output = capsys.readouterr().out
    assert code == 0
    assert "DM001" in output
    assert "nginx.conf:" in output

def test_json_scan(capsys):
    code = main(["scan", str(FIXTURES / "worker-first"), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(x["rule_id"] == "DM002" for x in payload["findings"])

def test_fail_on_needs_review(capsys):
    code = main(["scan", str(FIXTURES / "proxy-first"), "--fail-on", "needs-review"])
    capsys.readouterr()
    assert code == 1

def test_missing_path_returns_three(capsys):
    code = main(["scan", str(FIXTURES / "missing")])
    assert code == 3
    assert "cannot read" in capsys.readouterr().err

def test_empty_project_returns_four(capsys, tmp_path):
    code = main(["scan", str(tmp_path)])
    assert code == 4
    assert "No supported configuration" in capsys.readouterr().out

 
def test_dm003_runtime_scenario_is_detected(capsys):
    scenario = Path(__file__).parents[1] / "examples" / "runtime-validation-dm003"
    code = main(["scan", str(scenario), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(
        item["rule_id"] == "DM003" and item["verdict"] == "needs-review"
        for item in payload["findings"]
    )
