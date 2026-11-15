"""Conservative rules for explicit NGINX/Gunicorn timeout settings."""
from __future__ import annotations
import re
from pathlib import Path
from deadlinemap.model import Finding, NginxDirective, TimeoutSetting

MULTIPLIERS = {"": 1.0, "s": 1.0, "ms": .001, "m": 60.0, "h": 3600.0, "d": 86400.0, "w": 604800.0}

def parse_duration(value: str):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w)?\s*", value)
    if not match:
        return None
    return float(match.group(1)) * MULTIPLIERS[match.group(2) or ""]

def _ctx(context, prefix):
    return next((item for item in reversed(context) if item == prefix or item.startswith(prefix + " ")), None)

def _ev(key, value, path, line, context=()):
    return {"key": key, "value": value, "source": str(path), "line": line, "context": list(context)}

def analyze(directives: list[NginxDirective], gunicorn: dict, gunicorn_path: Path | None):
    findings, settings = [], []
    for d in directives:
        if d.name in {"proxy_connect_timeout", "proxy_read_timeout", "proxy_send_timeout"}:
            raw = d.args[0] if d.args else ""
            kind = {"proxy_connect_timeout":"connect", "proxy_read_timeout":"read-interval",
                    "proxy_send_timeout":"send-interval"}[d.name]
            seconds = parse_duration(raw)
            settings.append(TimeoutSetting(d.name, raw, seconds, kind, d.source, d.line, d.context))
            if seconds is None:
                findings.append(Finding("DM005", "needs-review", "Unresolved NGINX timeout value",
                    f"{d.name} uses an unsupported or unresolved value: {raw!r}.",
                    [_ev(d.name, raw, d.source, d.line, d.context)],
                    ["Variables and templates are not evaluated."]))
        elif d.name == "keepalive_timeout" and _ctx(d.context, "upstream"):
            raw = d.args[0] if d.args else ""
            seconds = parse_duration(raw)
            settings.append(TimeoutSetting("upstream.keepalive_timeout", raw, seconds,
                                           "idle-keepalive", d.source, d.line, d.context))
            if seconds is None:
                findings.append(Finding("DM005", "needs-review", "Unresolved upstream keep-alive timeout",
                    f"keepalive_timeout uses an unsupported value: {raw!r}.",
                    [_ev("keepalive_timeout", raw, d.source, d.line, d.context)]))

    if gunicorn_path is None:
        return findings, settings

    worker, worker_line = gunicorn.get("worker_class", (None, 0))
    backend_keep, backend_keep_line = gunicorn.get("keepalive", (None, 0))
    backend_timeout, backend_timeout_line = gunicorn.get("timeout", (None, 0))

    if worker is None:
        findings.append(Finding("DM005", "needs-review", "Gunicorn worker class is not explicit",
            "Worker-dependent checks were skipped because worker_class is not a literal setting.",
            [_ev("worker_class", "not explicit", gunicorn_path, 1)],
            ["No worker-class default is inferred."]))
        return findings, settings
    if isinstance(worker, str):
        worker = worker.rsplit(".", 1)[-1]

    keepalive_is_numeric = (
        isinstance(backend_keep, (int, float)) and not isinstance(backend_keep, bool)
    )
    keepalive_is_valid = (
        keepalive_is_numeric
        and backend_keep >= 0
        and float(backend_keep).is_integer()
    )
    if backend_keep is not None and not keepalive_is_valid:
        findings.append(Finding(
            "DM005", "needs-review", "Unsupported Gunicorn keep-alive value",
            f"Gunicorn keepalive must be a non-negative integer; found {backend_keep!r}.",
            [_ev("gunicorn.keepalive", str(backend_keep), gunicorn_path, backend_keep_line)],
            ["The analyzer does not coerce or execute Gunicorn configuration values."],
        ))
    elif keepalive_is_valid:
        settings.append(TimeoutSetting("gunicorn.keepalive", str(backend_keep), float(backend_keep),
                                       "idle-keepalive", gunicorn_path, backend_keep_line))
    if backend_timeout is not None and isinstance(backend_timeout, (int, float)):
        settings.append(TimeoutSetting("gunicorn.timeout", str(backend_timeout), float(backend_timeout),
                                       "worker-silence", gunicorn_path, backend_timeout_line))

    # DM001: conservative conditions. No check for sync workers, implicit proxy
    # defaults, or routes that do not explicitly opt in to upstream keepalive.
    if worker in {"gthread", "gevent"} and keepalive_is_valid and float(backend_keep) > 0:
        upstreams = {}
        for d in directives:
            upstream = _ctx(d.context, "upstream")
            if upstream:
                upstreams.setdefault(upstream, {})[d.name] = d
        for upstream, values in upstreams.items():
            cache, proxy_idle = values.get("keepalive"), values.get("keepalive_timeout")
            if not cache or not cache.args or not proxy_idle or not proxy_idle.args:
                continue
            try:
                cache_enabled = int(cache.args[0]) > 0
            except ValueError:
                cache_enabled = False
            proxy_seconds = parse_duration(proxy_idle.args[0])
            if not cache_enabled or proxy_seconds is None or proxy_seconds <= float(backend_keep):
                continue
            upstream_name = upstream.removeprefix("upstream ")
            routes = []
            for d in directives:
                if d.name != "proxy_pass" or not d.args or d.args[0] not in {
                    f"http://{upstream_name}", f"https://{upstream_name}"
                }:
                    continue
                loc = _ctx(d.context, "location")
                if not loc:
                    continue
                scoped = [x for x in directives if x.context == d.context]
                http_ok = any(x.name == "proxy_http_version" and x.args and x.args[0] in {"1.1", "2"} for x in scoped)
                conn_clear = any(x.name == "proxy_set_header" and len(x.args) >= 2 and
                                 x.args[0].lower() == "connection" and x.args[1] == "" for x in scoped)
                if http_ok and conn_clear:
                    routes.append(d)
            if routes:
                route = routes[0]
                findings.append(Finding("DM001", "needs-review", "Possible upstream idle keep-alive mismatch",
                    f"NGINX's configured upstream idle timeout ({proxy_seconds:g}s) exceeds Gunicorn's "
                    f"keepalive ({float(backend_keep):g}s). A stale-connection race is possible, not guaranteed.",
                    [_ev("upstream.keepalive_timeout", proxy_idle.args[0], proxy_idle.source, proxy_idle.line, proxy_idle.context),
                     _ev("upstream.keepalive", cache.args[0], cache.source, cache.line, cache.context),
                     _ev("gunicorn.keepalive", str(backend_keep), gunicorn_path, backend_keep_line),
                     _ev("proxy_pass", route.args[0], route.source, route.line, route.context)],
                    [f"Explicit worker_class is {worker}.",
                     "The matched route explicitly configures proxy HTTP/1.1 or HTTP/2 and clears Connection.",
                     "Runtime behavior must be reproduced against the target versions."]))

    # DM002/DM003 are review heuristics only for explicitly configured sync workers.
    if worker == "sync" and isinstance(backend_timeout, (int, float)):
        reads = [d for d in directives if d.name == "proxy_read_timeout"]
        if len(reads) == 1 and reads[0].args:
            read = reads[0]
            proxy_seconds = parse_duration(read.args[0])
            worker_seconds = float(backend_timeout)
            if proxy_seconds is not None and proxy_seconds != worker_seconds:
                if worker_seconds < proxy_seconds:
                    code, title = "DM002", "Gunicorn worker timeout is shorter than proxy read interval"
                    message = (f"Gunicorn's sync-worker silence timeout is {worker_seconds:g}s while NGINX "
                               f"permits {proxy_seconds:g}s between upstream reads. If the worker stays silent, "
                               "Gunicorn may terminate it first.")
                else:
                    code, title = "DM003", "Proxy read interval is shorter than Gunicorn worker timeout"
                    message = (f"NGINX permits {proxy_seconds:g}s between upstream reads while Gunicorn's "
                               f"sync-worker silence timeout is {worker_seconds:g}s. NGINX may close an idle "
                               "response first; application cancellation is runtime-dependent.")
                findings.append(Finding(code, "needs-review", title, message,
                    [_ev("proxy_read_timeout", read.args[0], read.source, read.line, read.context),
                     _ev("gunicorn.timeout", str(backend_timeout), gunicorn_path, backend_timeout_line)],
                    ["This is a review heuristic, not a guaranteed HTTP status or total request deadline.",
                     "The result depends on response activity and runtime behavior."]))
    return findings, settings
