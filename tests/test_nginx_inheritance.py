"""NGINX directive inheritance and sibling-scope regression tests."""

from pathlib import Path

from deadlinemap.parsers.gunicorn import parse_gunicorn
from deadlinemap.parsers.nginx import parse_nginx
from deadlinemap.rules import analyze


def run_config(tmp_path: Path, nginx_text: str, gunicorn_text: str):
    nginx_path = tmp_path / "nginx.conf"
    gunicorn_path = tmp_path / "gunicorn.conf.py"
    nginx_path.write_text(nginx_text, encoding="utf-8")
    gunicorn_path.write_text(gunicorn_text, encoding="utf-8")
    directives, issues = parse_nginx(nginx_path, tmp_path)
    gunicorn, gunicorn_issues = parse_gunicorn(gunicorn_path)
    findings, settings = analyze(directives, gunicorn, gunicorn_path)
    return directives, findings, settings, issues + gunicorn_issues


GUNICORN_SYNC = 'worker_class = "sync"\ntimeout = 8\n'
GUNICORN_GTHREAD = 'worker_class = "gthread"\nkeepalive = 2\n'


def ids(findings):
    return [item.rule_id for item in findings]


def test_http_level_proxy_read_timeout_is_inherited_by_location(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    proxy_read_timeout 30s;
    server {
        location /api {
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_SYNC,
    )

    assert not issues
    finding = next(item for item in findings if item.rule_id == "DM002")
    assert finding.evidence[0]["value"] == "30s"
    assert finding.evidence[-1]["value"] == "http://backend"


def test_location_override_takes_precedence_over_http_timeout(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    proxy_read_timeout 30s;
    server {
        location /api {
            proxy_read_timeout 2s;
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_SYNC,
    )

    assert not issues
    finding = next(item for item in findings if item.rule_id == "DM003")
    assert finding.evidence[0]["value"] == "2s"


def test_sibling_locations_resolve_independently(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    server {
        location /slow {
            proxy_pass http://backend;
            proxy_read_timeout 30s;
        }
        location /fast {
            proxy_pass http://backend;
            proxy_read_timeout 2s;
        }
    }
}
""",
        GUNICORN_SYNC,
    )

    assert not issues
    by_rule = {item.rule_id: item for item in findings if item.rule_id in {"DM002", "DM003"}}
    assert set(by_rule) == {"DM002", "DM003"}
    assert by_rule["DM003"].evidence[-1]["value"] == "http://backend"
    assert by_rule["DM002"].evidence[0]["value"] == "30s"


def test_same_named_sibling_server_blocks_do_not_leak_overrides(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    server {
        location /slow {
            proxy_pass http://backend;
        }
        proxy_read_timeout 30s;
    }
    server {
        proxy_read_timeout 2s;
        location /fast {
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_SYNC,
    )

    assert not issues
    values = {
        item.rule_id: item.evidence[0]["value"]
        for item in findings if item.rule_id in {"DM002", "DM003"}
    }
    assert values == {"DM002": "30s", "DM003": "2s"}


def test_duplicate_timeout_at_same_scope_is_not_guessed(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    server {
        proxy_read_timeout 20s;
        proxy_read_timeout 30s;
        location /api {
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_SYNC,
    )

    assert not issues
    assert "DM005" in ids(findings)
    assert not ({"DM002", "DM003"} & set(ids(findings)))


def test_dm001_inherits_proxy_http_version_and_connection_header(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    upstream backend {
        server app:8000;
        keepalive 8;
        keepalive_timeout 10s;
    }
    server {
        location /api {
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_GTHREAD,
    )

    assert not issues
    finding = next(item for item in findings if item.rule_id == "DM001")
    keys = {item["key"] for item in finding.evidence}
    assert "proxy_http_version" in keys
    assert "proxy_set_header Connection" in keys


def test_dm001_proxy_set_header_child_directive_stops_parent_header_inheritance(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    upstream backend {
        server app:8000;
        keepalive 8;
        keepalive_timeout 10s;
    }
    server {
        proxy_set_header X-Request-ID $request_id;
        location /api {
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_GTHREAD,
    )

    assert not issues
    assert "DM001" not in ids(findings)


def test_dm001_location_http_version_override_blocks_inherited_keepalive(tmp_path):
    _, findings, _, issues = run_config(
        tmp_path,
        """
events {}
http {
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    upstream backend {
        server app:8000;
        keepalive 8;
        keepalive_timeout 10s;
    }
    server {
        location /api {
            proxy_http_version 1.0;
            proxy_pass http://backend;
        }
    }
}
""",
        GUNICORN_GTHREAD,
    )

    assert not issues
    assert "DM001" not in ids(findings)
