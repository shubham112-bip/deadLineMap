"""Shared data structures for DeadlineMap."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class NginxDirective:
    name: str
    args: tuple[str, ...]
    context: tuple[str, ...]
    source: Path
    line: int

@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    source: Path
    line: int
    detail: str = ""

@dataclass(frozen=True)
class TimeoutSetting:
    key: str
    value: str
    seconds: float | None
    kind: str
    source: Path
    line: int
    context: tuple[str, ...] = ()
    explicit: bool = True

@dataclass
class Finding:
    rule_id: str
    verdict: str
    title: str
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class ScanResult:
    root: Path
    nginx_files: list[Path] = field(default_factory=list)
    gunicorn_files: list[Path] = field(default_factory=list)
    settings: list[TimeoutSetting] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": {"nginx": [str(p) for p in self.nginx_files],
                      "gunicorn": [str(p) for p in self.gunicorn_files]},
            "settings": [{"key": x.key, "value": x.value, "seconds": x.seconds,
                          "kind": x.kind, "source": str(x.source), "line": x.line,
                          "context": list(x.context), "explicit": x.explicit}
                         for x in self.settings],
            "findings": [x.to_dict() for x in self.findings],
            "issues": [{"code": x.code, "message": x.message, "source": str(x.source),
                        "line": x.line, "detail": x.detail} for x in self.issues],
            "notes": self.notes,
        }
