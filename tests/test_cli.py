import json
from pathlib import Path

from deadlinemap.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_text_scan_is_plain_language(capsys):
    code = main(["scan", str(FIXTURES / "keepalive-mismatch")])
    output = capsys.readouterr().out
    assert code == 0
    assert "keep-alive times may not match" in output
    assert "NGINX:" in output
    assert "Gunicorn:" in output
    assert "Problem:" in output
    assert "What to do:" in output
    assert "DM001" not in output
    assert "needs-review" not in output
    assert "Technical evidence:" not in output


def test_short_command_scan(capsys):
    code = main([str(FIXTURES / "worker-first")])
    output = capsys.readouterr().out
    assert code == 0
    assert "Gunicorn may stop the worker first" in output
    assert "DM002" not in output
    assert "What to do:" in output


def test_dynamic_setting_explained_simply(capsys):
    code = main(["scan", str(FIXTURES / "dynamic-value")])
    output = capsys.readouterr().out
    assert code == 0
    assert "cannot be checked" in output
    assert "DM005" not in output
    assert "Problem:" in output


def test_details_show_rule_ids_and_evidence(capsys):
    code = main(["scan", str(FIXTURES / "keepalive-mismatch"), "--details"])
    output = capsys.readouterr().out
    assert code == 0
    assert "DM001" in output
    assert "Technical evidence:" in output
    assert "Settings read by DeadlineMap" in output


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
    assert "No supported config files were found." in output
    assert "nginx.conf and gunicorn.conf.py" in output


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
