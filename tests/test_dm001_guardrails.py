"""DM001 guardrails: avoid warnings when the full keep-alive path is absent."""

from pathlib import Path

import pytest

from deadlinemap.model import NginxDirective
from deadlinemap.rules import analyze


MISSING = object()


def analyze_dm001(
    tmp_path: Path,
    *,
    worker="gthread",
    backend_keep=2,
    upstream_cache=16,
    upstream_idle="10s",
    proxy_target="http://app_server",
    proxy_http_version="1.1",
    connection_value="",
    connection_context=None,
):
    nginx_path = tmp_path / "nginx.conf"
    gunicorn_path = tmp_path / "gunicorn.conf.py"
    upstream_context = ("http", "upstream app_server")
    route_context = ("http", "server", "location /")
    directives = []

    if upstream_cache is not None:
        directives.append(NginxDirective(
            "keepalive", (str(upstream_cache),), upstream_context, nginx_path, 4
        ))
    if upstream_idle is not None:
        directives.append(NginxDirective(
            "keepalive_timeout", (upstream_idle,), upstream_context, nginx_path, 5
        ))
    if proxy_target is not None:
        directives.append(NginxDirective(
            "proxy_pass", (proxy_target,), route_context, nginx_path, 10
        ))
    if proxy_http_version is not None:
        directives.append(NginxDirective(
            "proxy_http_version", (proxy_http_version,), route_context, nginx_path, 11
        ))
    if connection_value is not None:
        directives.append(NginxDirective(
            "proxy_set_header", ("Connection", connection_value),
            connection_context or route_context, nginx_path, 12
        ))

    gunicorn = {"worker_class": (worker, 1)}
    if backend_keep is not MISSING:
        gunicorn["keepalive"] = (backend_keep, 2)

    findings, settings = analyze(directives, gunicorn, gunicorn_path)
    return findings, settings


def has_rule(findings, rule_id):
    return any(item.rule_id == rule_id for item in findings)


def test_dm001_reports_complete_gthread_configuration(tmp_path):
    findings, settings = analyze_dm001(tmp_path)

    assert has_rule(findings, "DM001")
    finding = next(item for item in findings if item.rule_id == "DM001")
    assert finding.verdict == "needs-review"
    assert {item["key"] for item in finding.evidence} == {
        "upstream.keepalive_timeout",
        "upstream.keepalive",
        "gunicorn.keepalive",
        "proxy_http_version",
        "proxy_pass",
        "proxy_set_header Connection",
    }
    assert any(item.key == "gunicorn.keepalive" for item in settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"worker": "sync"},
        {"upstream_cache": None},
        {"upstream_cache": 0},
        {"proxy_target": "http://another_upstream"},
        {"proxy_http_version": None},
        {"proxy_http_version": "1.0"},
        {"connection_value": None},
        {"connection_value": "keep-alive"},
        {"upstream_idle": "2s"},  # equal to Gunicorn keepalive
        {"upstream_idle": "1s"},  # NGINX expires first
    ],
)
def test_dm001_skips_incomplete_or_non_mismatched_paths(tmp_path, overrides):
    findings, _ = analyze_dm001(tmp_path, **overrides)

    assert not has_rule(findings, "DM001")


def test_dm001_does_not_borrow_connection_header_from_another_location(tmp_path):
    findings, _ = analyze_dm001(
        tmp_path,
        connection_context=("http", "server", "location /unrelated"),
    )

    assert not has_rule(findings, "DM001")


def test_dm001_requires_an_explicit_backend_keepalive(tmp_path):
    findings, _ = analyze_dm001(tmp_path, backend_keep=MISSING)

    assert not has_rule(findings, "DM001")


@pytest.mark.parametrize("value", [-1, 2.5, "two"])
def test_invalid_gunicorn_keepalive_is_reviewed_not_compared(tmp_path, value):
    findings, settings = analyze_dm001(tmp_path, backend_keep=value)

    assert not has_rule(findings, "DM001")
    assert has_rule(findings, "DM005")
    assert not any(item.key == "gunicorn.keepalive" for item in settings)


def test_zero_gunicorn_keepalive_does_not_trigger_dm001(tmp_path):
    findings, settings = analyze_dm001(tmp_path, backend_keep=0)

    assert not has_rule(findings, "DM001")
    assert not has_rule(findings, "DM005")
    assert any(item.key == "gunicorn.keepalive" and item.seconds == 0 for item in settings)


def test_dm001_matches_only_the_named_upstream(tmp_path):
    nginx = tmp_path / "nginx.conf"
    gunicorn_path = tmp_path / "gunicorn.conf.py"
    app_ctx = ("http", "upstream app_server")
    other_ctx = ("http", "upstream other_server")
    route_ctx = ("http", "server", "location /")
    directives = [
        NginxDirective("keepalive", ("16",), app_ctx, nginx, 3),
        NginxDirective("keepalive_timeout", ("10s",), app_ctx, nginx, 4),
        NginxDirective("keepalive", ("16",), other_ctx, nginx, 7),
        NginxDirective("keepalive_timeout", ("1s",), other_ctx, nginx, 8),
        NginxDirective("proxy_pass", ("http://app_server",), route_ctx, nginx, 12),
        NginxDirective("proxy_http_version", ("1.1",), route_ctx, nginx, 13),
        NginxDirective("proxy_set_header", ("Connection", ""), route_ctx, nginx, 14),
    ]

    findings, _ = analyze(
        directives,
        {"worker_class": ("gthread", 1), "keepalive": (2, 2)},
        gunicorn_path,
    )

    finding = next(item for item in findings if item.rule_id == "DM001")
    assert finding.evidence[0]["value"] == "10s"
