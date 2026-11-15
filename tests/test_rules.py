from pathlib import Path
from deadlinemap.parsers.gunicorn import parse_gunicorn
from deadlinemap.parsers.nginx import parse_nginx
from deadlinemap.rules import analyze, parse_duration

FIXTURES = Path(__file__).parent / "fixtures"

def fixture(name):
    root = FIXTURES / name
    directives, nginx_issues = parse_nginx(root / "nginx.conf", root)
    gunicorn, gunicorn_issues = parse_gunicorn(root / "gunicorn.conf.py")
    findings, settings = analyze(directives, gunicorn, root / "gunicorn.conf.py")
    return findings, settings, nginx_issues + gunicorn_issues

def test_units():
    assert parse_duration("30") == 30
    assert parse_duration("1m") == 60
    assert parse_duration("500ms") == .5
    assert parse_duration("2h") == 7200
    assert parse_duration("$DYNAMIC") is None

def test_tokenizer_handles_quotes_comments_and_empty_value():
    from deadlinemap.parsers.nginx import tokenize
    tokens = tokenize('proxy_set_header Connection ""; # comment\nproxy_read_timeout 30s;')
    assert [t.value for t in tokens] == [
        "proxy_set_header", "Connection", "", ";", "proxy_read_timeout", "30s", ";"
    ]

def test_dm001_gthread_keepalive_review():
    findings, _, issues = fixture("keepalive-mismatch")
    assert not issues
    assert any(f.rule_id == "DM001" and f.verdict == "needs-review" for f in findings)

def test_dm001_not_applied_to_sync_worker():
    findings, _, issues = fixture("sync-no-keepalive")
    assert not issues
    assert not any(f.rule_id == "DM001" for f in findings)

def test_dm002_sync_worker_timeout_first():
    findings, _, issues = fixture("worker-first")
    assert not issues
    assert any(f.rule_id == "DM002" for f in findings)

def test_dm003_proxy_read_interval_first():
    findings, _, issues = fixture("proxy-first")
    assert not issues
    assert any(f.rule_id == "DM003" for f in findings)

def test_dynamic_nginx_value_is_review():
    findings, _, issues = fixture("dynamic-value")
    assert any(i.code == "DM005" for i in issues)
    assert any(f.rule_id == "DM005" for f in findings)
