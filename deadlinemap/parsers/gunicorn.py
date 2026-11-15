"""Read literal module-level Gunicorn settings without executing the file."""
from __future__ import annotations
import ast
from pathlib import Path
from deadlinemap.model import ParseIssue

KEYS = {"worker_class", "timeout", "keepalive"}

def parse_gunicorn(path: Path):
    settings = {}
    issues = []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeError) as exc:
        return settings, [ParseIssue("DM005", "Could not read Gunicorn config", path, 1, str(exc))]
    except SyntaxError as exc:
        return settings, [ParseIssue("DM005", "Could not parse Gunicorn config", path, exc.lineno or 1, exc.msg)]
    for node in tree.body:
        name, value_node = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value_node = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value_node = node.target.id, node.value
        if name not in KEYS or value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, TypeError, SyntaxError):
            issues.append(ParseIssue("DM005", f"Gunicorn setting {name!r} is dynamic", path, node.lineno,
                                     "The configuration is never executed."))
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            issues.append(ParseIssue("DM005", f"Unsupported Gunicorn value for {name!r}", path, node.lineno, repr(value)))
            continue
        settings[name] = (value, node.lineno)
    return settings, issues
