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
    assert "What needs attention" in output
    assert "Parsed timeout and keep-alive settings" not in output


def test_short_command_scan(capsys):
    code = main([str(FIXTURES / "worker-first")])
    output = capsys.readouterr().out
    assert code == 0
    assert "DM002" in output
    assert "REVIEW RECOMMENDED" in output


def test_details_show_settings_and_evidence(capsys):
    code = main(["scan", str(FIXTURES / "keepalive-mismatch"), "--details"])
    output = capsys.readouterr().out
    assert code == 0
    assert "Parsed timeout and keep-alive settings" in output
    assert "Evidence:" in output


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
    output = capsys.readouterr().out
    assert "No supported config files" in output
    assert "No supported configuration" in output


def test_dm003_runtime_scenario_is_detected(capsys):
    scenario = Path(__file__).parents[1] / "examples" / "runtime-validation-dm003"
    code = main(["scan", str(scenario), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(
        item["rule_id"] == "DM003" and item["verdict"] == "needs-review"
        for item in payload["findings"]
    )


def test_dm001_runtime_scenario_is_detected(capsys):
    scenario = Path(__file__).parents[1] / "examples" / "runtime-validation-dm001"
    code = main(["scan", str(scenario), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(
        item["rule_id"] == "DM001" and item["verdict"] == "needs-review"
        for item in payload["findings"]
    )
