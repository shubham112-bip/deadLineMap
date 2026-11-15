"""Read-only discovery of supported configuration entry points."""
from __future__ import annotations
import os
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
             ".mypy_cache", ".tox", "site-packages", "dist", "build"}

def discover(root: Path):
    nginx, gunicorn = [], []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        base = Path(current)
        if "nginx.conf" in files:
            nginx.append(base / "nginx.conf")
        if "gunicorn.conf.py" in files:
            gunicorn.append(base / "gunicorn.conf.py")
    return sorted(nginx), sorted(gunicorn)
