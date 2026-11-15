"""DeadlineMap text and JSON reports."""
from __future__ import annotations
import json
from collections import Counter
from deadlinemap.model import ScanResult

ORDER = {"risk": 0, "needs-review": 1, "info": 2}

def render_text(result: ScanResult) -> str:
    lines = [
        "DeadlineMap — timeout configuration report",
        f"Project: {result.root}",
        f"NGINX configs: {len(result.nginx_files)} | Gunicorn configs: {len(result.gunicorn_files)}",
        f"Timeout settings parsed: {len(result.settings)}",
        "",
    ]
    if result.settings:
        lines.append("Discovered settings:")
        for s in sorted(result.settings, key=lambda x: (str(x.source), x.line, x.key)):
            ctx = " > ".join(s.context)
            lines.append(f"  {s.source}:{s.line}  {s.key}={s.value!r} [{s.kind}]" + (f" ({ctx})" if ctx else ""))
        lines.append("")
    if result.findings:
        for f in sorted(result.findings, key=lambda x: (ORDER.get(x.verdict, 9), x.rule_id)):
            lines.append(f"[{f.verdict.upper()}] {f.rule_id} — {f.title}")
            lines.append(f"  {f.message}")
            for e in f.evidence:
                lines.append(f"  -> {e.get('source')}:{e.get('line')} {e.get('key')}={e.get('value')!r}")
            for assumption in f.assumptions:
                lines.append(f"  Assumption: {assumption}")
            lines.append("")
    else:
        lines.extend(["No findings from the currently supported rules.", ""])
    lines.extend(f"Note: {note}" for note in result.notes)
    counts = Counter(f.verdict for f in result.findings)
    lines.extend(["", f"Summary: {counts.get('risk', 0)} risk, "
                  f"{counts.get('needs-review', 0)} needs-review, {counts.get('info', 0)} info",
                  "Static analysis only: no config files changed and no services contacted."])
    return "\n".join(lines)

def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)
