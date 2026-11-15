"""Human-friendly text and machine-readable JSON reports."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from deadlinemap.model import ScanResult

ORDER = {"risk": 0, "needs-review": 1, "info": 2}


def _display_path(value: str | Path, root: Path) -> str:
    path = Path(value)
    base = root if root.is_dir() else root.parent
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _location(evidence: dict, root: Path) -> str | None:
    source = evidence.get("source")
    if not source:
        return None
    path = _display_path(source, root)
    line = evidence.get("line")
    return f"{path}:{line}" if line else path


def _plain_explanation(finding) -> str:
    if finding.rule_id == "DM001":
        return (
            "NGINX may keep an upstream connection idle longer than Gunicorn does. "
            "That can create a stale-connection race, although NGINX may reconnect cleanly."
        )
    if finding.rule_id == "DM002":
        return (
            "Gunicorn may stop a quiet worker before NGINX gives up waiting between "
            "upstream reads. This matters when a response goes silent for a while."
        )
    if finding.rule_id == "DM003":
        return (
            "NGINX may stop waiting for an upstream response before Gunicorn reaches "
            "its worker timeout. The effect on the application depends on runtime behavior."
        )

    title = finding.title.lower()
    message = finding.message
    if "dynamic" in title:
        return (
            "This value is calculated at runtime. DeadlineMap does not run Gunicorn's "
            "configuration code, so it cannot safely determine the final value."
        )
    if "unresolved" in title:
        return (
            "This setting contains a variable or expression DeadlineMap cannot resolve. "
            "Confirm the value used by the running deployment."
        )
    if "unsupported" in title:
        return f"{message} The value format is not supported, so it was left unresolved rather than guessed."
    if "ambiguous" in title or "duplicate" in message.lower():
        return f"{message} DeadlineMap did not guess which setting would take effect."
    if "worker class is not explicit" in title:
        return (
            "The Gunicorn worker type is not set as a simple, readable value. "
            "Worker-specific timeout checks were skipped."
        )
    return message


def _next_step(finding) -> str:
    if finding.rule_id == "DM001":
        return "Review both keep-alive settings and test connection reuse after an idle period."
    if finding.rule_id in {"DM002", "DM003"}:
        return "Test a representative long request and confirm which timeout closes the connection first."

    title = finding.title.lower()
    if "dynamic" in title or "unresolved" in title or "unsupported" in title:
        return "Check the effective value used by the running deployment."
    if "ambiguous" in title or "duplicate" in finding.message.lower():
        return "Review the matching NGINX block and clarify the duplicate settings."
    if "worker class is not explicit" in title:
        return "Set worker_class explicitly if you want worker-specific checks."
    return "Open the listed config line and review the setting."


def render_text(result: ScanResult, details: bool = False) -> str:
    findings = sorted(
        result.findings,
        key=lambda item: (ORDER.get(item.verdict, 9), item.rule_id, item.title),
    )
    counts = Counter(item.verdict for item in findings)

    if not result.nginx_files and not result.gunicorn_files:
        status = "NO CONFIG FILES FOUND"
    elif counts.get("risk", 0):
        status = "POTENTIAL RISK FOUND"
    elif counts.get("needs-review", 0):
        status = "REVIEW RECOMMENDED"
    elif any("cross-layer checks were skipped" in note for note in result.notes):
        status = "PARTIAL SCAN"
    else:
        status = "NO SUPPORTED CONFLICTS FOUND"

    project = str(result.root)
    if result.root.is_file():
        project = _display_path(result.root, result.root.parent)

    lines = [
        "DeadlineMap",
        "-----------",
        f"Project: {project}",
        f"Status: {status}",
        f"Files checked: {len(result.nginx_files)} NGINX, {len(result.gunicorn_files)} Gunicorn",
        "",
    ]

    if findings:
        summary_parts = []
        risk_count = counts.get("risk", 0)
        review_count = counts.get("needs-review", 0)
        info_count = counts.get("info", 0)
        if risk_count:
            summary_parts.append(f"{risk_count} potential risk{'s' if risk_count != 1 else ''}")
        if review_count:
            summary_parts.append(f"{review_count} item{'s' if review_count != 1 else ''} to review")
        if info_count:
            summary_parts.append(f"{info_count} info")
        lines.extend(["Found: " + " · ".join(summary_parts), "", "What needs attention", ""])

        for index, finding in enumerate(findings, start=1):
            label = finding.verdict.replace("-", " ").upper()
            lines.append(f"{index}. [{finding.rule_id} · {label}] {finding.title}")
            lines.append(f"   {_plain_explanation(finding)}")
            location = next(
                (
                    _location(item, result.root)
                    for item in finding.evidence
                    if _location(item, result.root)
                ),
                None,
            )
            if location:
                lines.append(f"   Location: {location}")
            lines.append(f"   Next step: {_next_step(finding)}")

            if details:
                if finding.evidence:
                    lines.append("   Evidence:")
                    for item in finding.evidence:
                        where = _location(item, result.root) or "unknown location"
                        key = item.get("key", "setting")
                        value = item.get("value")
                        context = " > ".join(item.get("context", []))
                        extra = f" ({context})" if context else ""
                        lines.append(f"     - {key}={value!r} at {where}{extra}")
                if finding.assumptions:
                    lines.append("   Notes:")
                    for assumption in finding.assumptions:
                        lines.append(f"     - {assumption}")
            lines.append("")
    else:
        if result.nginx_files or result.gunicorn_files:
            lines.append("No conflicts were identified by the supported checks.")
            lines.append("This is not a guarantee that every timeout issue has been ruled out.")
        else:
            lines.append("No supported config files were found.")
        lines.append("")

    if result.notes:
        lines.append("Scan notes")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")

    if details and result.settings:
        lines.append("Parsed timeout and keep-alive settings")
        for setting in sorted(
            result.settings, key=lambda item: (str(item.source), item.line, item.key)
        ):
            context = " > ".join(setting.context)
            suffix = f" ({context})" if context else ""
            where = _location(
                {"source": str(setting.source), "line": setting.line}, result.root
            )
            lines.append(
                f"- {setting.key}={setting.value!r} at {where} [{setting.kind}]{suffix}"
            )
        lines.append("")

    lines.append("Static analysis only. No config files were changed and no services were started.")
    if not details and findings:
        lines.append("Run with --details to see every setting and evidence line.")
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)
