"""Simple human-readable scan report plus optional technical details."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from deadlinemap.model import ScanResult

ORDER = {"risk": 0, "needs-review": 1, "info": 2}


def _relative_file(source: str | Path, root: Path) -> str:
    path = Path(source)
    base = root if root.is_dir() else root.parent
    try:
        return str(path.relative_to(base))
    except ValueError:
        return path.name


def _where(evidence: dict, root: Path) -> str | None:
    source = evidence.get("source")
    if not source:
        return None
    location = _relative_file(source, root)
    line = evidence.get("line")
    return f"{location}:{line}" if line else location


def _evidence(finding, key: str) -> dict | None:
    return next((item for item in finding.evidence if item.get("key") == key), None)


def _value(finding, key: str, default: str = "unknown") -> str:
    item = _evidence(finding, key)
    if item is None:
        return default
    value = item.get("value")
    return str(value) if value not in (None, "") else default


def _location_line(finding, key: str, root: Path) -> str | None:
    item = _evidence(finding, key)
    return _where(item, root) if item else None


def _simple_finding(finding, root: Path) -> tuple[str, str, list[str], str]:
    """Return a short title, explanation, locations, and action."""
    if finding.rule_id == "DM001":
        nginx_value = _value(finding, "upstream.keepalive_timeout")
        gunicorn_value = _value(finding, "gunicorn.keepalive")
        locations = []
        nginx_where = _location_line(finding, "upstream.keepalive_timeout", root)
        gunicorn_where = _location_line(finding, "gunicorn.keepalive", root)
        if nginx_where:
            locations.append(f"NGINX: {nginx_where}")
        if gunicorn_where:
            locations.append(f"Gunicorn: {gunicorn_where}")
        explanation = (
            f"NGINX keeps an upstream connection idle for {nginx_value}, while "
            f"Gunicorn keeps it for {gunicorn_value}. This may cause NGINX to reuse "
            "a connection that Gunicorn has already closed."
        )
        action = (
            "Review both keep-alive values and test a new request after the connection "
            "has been idle. This warning does not mean a request will definitely fail."
        )
        return "NGINX and Gunicorn keep-alive times may not match", explanation, locations, action

    if finding.rule_id == "DM002":
        nginx_value = _value(finding, "proxy_read_timeout")
        gunicorn_value = _value(finding, "gunicorn.timeout")
        locations = []
        nginx_where = _location_line(finding, "proxy_read_timeout", root)
        gunicorn_where = _location_line(finding, "gunicorn.timeout", root)
        if nginx_where:
            locations.append(f"NGINX: {nginx_where}")
        if gunicorn_where:
            locations.append(f"Gunicorn: {gunicorn_where}")
        explanation = (
            f"Gunicorn may stop a quiet worker after {gunicorn_value}, while NGINX "
            f"allows {nginx_value} between reads from the application. Gunicorn may "
            "stop the worker first."
        )
        action = (
            "Check how long your application can remain silent while handling a request. "
            "Test with a request that takes a similar amount of time."
        )
        return "Gunicorn may stop the worker first", explanation, locations, action

    if finding.rule_id == "DM003":
        nginx_value = _value(finding, "proxy_read_timeout")
        gunicorn_value = _value(finding, "gunicorn.timeout")
        locations = []
        nginx_where = _location_line(finding, "proxy_read_timeout", root)
        gunicorn_where = _location_line(finding, "gunicorn.timeout", root)
        if nginx_where:
            locations.append(f"NGINX: {nginx_where}")
        if gunicorn_where:
            locations.append(f"Gunicorn: {gunicorn_where}")
        explanation = (
            f"NGINX allows {nginx_value} without receiving data from the application, "
            f"while Gunicorn allows {gunicorn_value} for a quiet worker. NGINX may stop "
            "waiting first."
        )
        action = (
            "Check how long your application can remain silent while handling a request. "
            "Test with a request that takes a similar amount of time."
        )
        return "NGINX may stop waiting first", explanation, locations, action

    title = finding.title.lower()
    first = finding.evidence[0] if finding.evidence else {}
    location = _where(first, root)
    locations = [location] if location else []

    if " is dynamic" in title and "gunicorn" in title:
        match = re.search(r"Gunicorn setting ['\\"]([^'\\"]+)", finding.title, re.IGNORECASE)
        setting = match.group(1) if match else "setting"
        explanation = (
            f"The {setting} value is calculated by Python code or an environment "
            "variable. DeadlineMap does not run that code, so it cannot know the "
            "value used by the running application."
        )
        action = "Check the final value in the environment where the application runs."
        return f"Gunicorn {setting} value cannot be checked", explanation, locations, action

    if "worker class is not explicit" in title:
        explanation = (
            "The Gunicorn worker type is not written as a fixed value. "
            "DeadlineMap cannot safely run checks that depend on the worker type."
        )
        action = "Set worker_class explicitly in gunicorn.conf.py if you want these checks."
        return "Gunicorn worker type is not set clearly", explanation, locations, action

    if "unresolved nginx timeout" in title or "unresolved upstream keep-alive" in title:
        key = first.get("key", "NGINX setting")
        value = first.get("value", "unknown")
        explanation = (
            f"The {key} value ({value}) is not a fixed number that DeadlineMap can read. "
            "It may depend on a variable or template."
        )
        action = "Check the actual value used by NGINX when it starts."
        return "An NGINX timeout value cannot be checked", explanation, locations, action

    if "ambiguous" in title or "duplicate" in finding.message.lower():
        explanation = (
            "More than one setting could apply here. DeadlineMap cannot safely choose "
            "which one NGINX will use."
        )
        action = "Review the matching NGINX blocks and remove or clarify duplicate settings."
        return "More than one timeout setting may apply", explanation, locations, action

    if "unsupported gunicorn keep-alive" in title:
        explanation = "Gunicorn's keepalive value is not a plain non-negative whole number."
        action = "Use a fixed number, or check the value supplied by your deployment."
        return "Gunicorn keep-alive value needs checking", explanation, locations, action

    if "could not parse" in title or "malformed" in title:
        explanation = "DeadlineMap could not read this configuration file because its syntax is invalid or unsupported."
        action = "Check the file's syntax near the location shown."
        return "A configuration file could not be read", explanation, locations, action

    if "could not read" in title or "include" in title:
        explanation = "DeadlineMap could not read a configuration file needed for this scan."
        action = "Check that the file exists and that its include path is inside the project folder."
        return "A configuration file could not be read", explanation, locations, action

    explanation = finding.message.splitlines()[0] if finding.message else "This setting needs a manual check."
    action = "Open the file at the location shown and check this setting."
    return "A configuration setting needs checking", explanation, locations, action


def _file_counts(result: ScanResult) -> str:
    nginx = len(result.nginx_files)
    gunicorn = len(result.gunicorn_files)
    return (
        f"{nginx} NGINX config file{'s' if nginx != 1 else ''}, "
        f"{gunicorn} Gunicorn config file{'s' if gunicorn != 1 else ''}"
    )


def render_text(result: ScanResult, details: bool = False) -> str:
    findings = sorted(
        result.findings,
        key=lambda item: (ORDER.get(item.verdict, 9), item.rule_id, item.title),
    )
    counts = Counter(item.verdict for item in findings)
    project_name = result.root.name or str(result.root)
    lines = [
        "DeadlineMap",
        f"Project: {project_name}",
        f"Checked: {_file_counts(result)}",
        "",
    ]

    if not result.nginx_files and not result.gunicorn_files:
        lines.extend([
            "No supported config files were found.",
            "DeadlineMap looks for nginx.conf and gunicorn.conf.py.",
        ])
    elif findings:
        count_word = "item needs" if len(findings) == 1 else "items need"
        lines.append(f"{len(findings)} {count_word} a closer look")
        lines.append("")
        for index, finding in enumerate(findings, start=1):
            title, explanation, locations, action = _simple_finding(finding, result.root)
            if details:
                lines.append(f"{index}. {title} ({finding.rule_id})")
            else:
                lines.append(f"{index}. {title}")
            for location in locations:
                lines.append(f"   File: {location}")
            lines.append(f"   Problem: {explanation}")
            lines.append(f"   What to do: {action}")

            if details and finding.evidence:
                lines.append("   Technical evidence:")
                for item in finding.evidence:
                    where = _where(item, result.root) or "unknown location"
                    context = " > ".join(item.get("context", []))
                    suffix = f" [{context}]" if context else ""
                    lines.append(
                        f"     {item.get('key', 'setting')} = {item.get('value')!r} "
                        f"({where}){suffix}"
                    )
                for note in finding.assumptions:
                    lines.append(f"     Note: {note}")
            lines.append("")
    else:
        if result.nginx_files and result.gunicorn_files:
            lines.append("No supported timeout problems were found.")
        else:
            found = "NGINX" if result.nginx_files else "Gunicorn"
            missing = "Gunicorn" if result.nginx_files else "NGINX"
            lines.append(f"Only {found} config was found. No {missing} config was found.")
            lines.append(f"DeadlineMap could not compare both sets of timeout settings.")

    if details and result.settings:
        lines.extend(["", "Settings read by DeadlineMap"])
        for setting in sorted(
            result.settings, key=lambda item: (str(item.source), item.line, item.key)
        ):
            location = _relative_file(setting.source, result.root)
            lines.append(f"- {setting.key}: {setting.value} ({location}:{setting.line})")

    if details and result.notes:
        lines.extend(["", "Scan notes"])
        lines.extend(f"- {note}" for note in result.notes)

    lines.extend([
        "",
        "DeadlineMap checks NGINX and Gunicorn timeout settings; it does not find general bugs in application code.",
    ])
    if details:
        lines.append("No config files were changed and no services were started.")
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)
