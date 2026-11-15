"""Read-only scan orchestration."""
from pathlib import Path
from deadlinemap.discovery import discover
from deadlinemap.model import Finding, ScanResult
from deadlinemap.parsers.gunicorn import parse_gunicorn
from deadlinemap.parsers.nginx import parse_nginx
from deadlinemap.rules import analyze

def scan(target: Path) -> ScanResult:
    target = target.resolve()
    result = ScanResult(root=target)
    if target.is_file():
        nginx = [target] if target.name == "nginx.conf" else []
        gunicorn = [target] if target.name == "gunicorn.conf.py" else []
    else:
        nginx, gunicorn = discover(target)
    result.nginx_files, result.gunicorn_files = nginx, gunicorn
    directives = []
    for path in nginx:
        parsed, issues = parse_nginx(path, target if target.is_dir() else target.parent)
        directives.extend(parsed)
        result.issues.extend(issues)
    settings, config_path = {}, None
    if len(gunicorn) == 1:
        config_path = gunicorn[0]
        settings, issues = parse_gunicorn(config_path)
        result.issues.extend(issues)
    elif len(gunicorn) > 1:
        result.notes.append("Multiple Gunicorn configs found; cross-layer checks were skipped to avoid guessing the active config.")
    findings, parsed_settings = analyze(
        directives, settings if len(gunicorn) == 1 else {},
        config_path if len(gunicorn) == 1 else None
    )
    result.findings.extend(findings)
    result.settings.extend(parsed_settings)
    for issue in result.issues:
        result.findings.append(Finding(
            issue.code, "needs-review", issue.message, issue.detail or issue.message,
            [{"key": issue.code, "value": issue.detail, "source": str(issue.source),
              "line": issue.line, "context": []}]
        ))
    if nginx and not gunicorn:
        result.notes.append("NGINX config found, but no Gunicorn config was found; cross-layer checks were skipped.")
    elif gunicorn and not nginx:
        result.notes.append("Gunicorn config found, but no nginx.conf was found; cross-layer checks were skipped.")
    elif not nginx and not gunicorn:
        result.notes.append("No supported configuration found. Entry points: nginx.conf and gunicorn.conf.py.")
    if len(nginx) > 1:
        result.notes.append("Multiple nginx.conf files found; review source paths and service topology.")
    return result
