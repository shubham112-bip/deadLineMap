"""Conservative rules for explicit NGINX/Gunicorn timeout settings."""
from __future__ import annotations

import re
from pathlib import Path

from deadlinemap.model import Finding, NginxDirective, TimeoutSetting

MULTIPLIERS = {
    "": 1.0, "s": 1.0, "ms": .001, "m": 60.0,
    "h": 3600.0, "d": 86400.0, "w": 604800.0,
}


def parse_duration(value: str):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w)?\s*", value)
    if not match:
        return None
    return float(match.group(1)) * MULTIPLIERS[match.group(2) or ""]


def _ctx(context, prefix):
    return next(
        (item for item in reversed(context)
         if item == prefix or item.startswith(prefix + " ")),
        None,
    )


def _ev(key, value, path, line, context=()):
    return {
        "key": key, "value": value, "source": str(path),
        "line": line, "context": list(context),
    }


def _scope_of(directive: NginxDirective):
    """Return parser identity when available, otherwise the display context.

    The fallback keeps direct rule-level tests and older integrations working.
    """
    return directive.scope or directive.context


def _nearest_scope_directives(directives, name, target):
    """Find directives at the nearest ancestor scope of a target directive."""
    target_scope = _scope_of(target)
    candidates = []
    for item in directives:
        if item.name != name:
            continue
        item_scope = _scope_of(item)
        if len(item_scope) <= len(target_scope) and target_scope[:len(item_scope)] == item_scope:
            candidates.append(item)

    if not candidates:
        return []

    nearest_depth = max(len(_scope_of(item)) for item in candidates)
    return [item for item in candidates if len(_scope_of(item)) == nearest_depth]


def _effective_single(directives, name, target):
    """Resolve an inheritable scalar directive; duplicate peers are ambiguous."""
    candidates = _nearest_scope_directives(directives, name, target)
    if not candidates:
        return None, False
    if len(candidates) != 1:
        return None, True
    return candidates[0], False


def _effective_connection_header(directives, target):
    """Resolve proxy_set_header Connection using NGINX's all-or-nothing inheritance.

    If a child scope defines any proxy_set_header directive, the parent set is
    not inherited. We therefore inspect only the nearest scope containing the
    directive, then find its Connection entry.
    """
    candidates = _nearest_scope_directives(directives, "proxy_set_header", target)
    if not candidates:
        return None, False

    connections = [
        item for item in candidates
        if item.args and item.args[0].lower() == "connection"
    ]
    if len(connections) > 1:
        return None, True
    if not connections:
        return None, False
    if len(connections[0].args) != 2:
        return None, True
    return connections[0], False


def _is_location_proxy_pass(directive):
    return (
        directive.name == "proxy_pass"
        and bool(directive.args)
        and _ctx(directive.context, "location") is not None
    )


def _finding_dm005(title, message, directive, detail):
    return Finding(
        "DM005", "needs-review", title, message,
        [_ev(directive.name, "ambiguous", directive.source, directive.line, directive.context)],
        [detail],
    )


def analyze(directives: list[NginxDirective], gunicorn: dict, gunicorn_path: Path | None):
    findings, settings = [], []

    # Keep every explicit timeout as evidence. Effective inherited values are
    # resolved separately for each proxy_pass location below.
    for d in directives:
        if d.name in {"proxy_connect_timeout", "proxy_read_timeout", "proxy_send_timeout"}:
            raw = d.args[0] if d.args else ""
            kind = {
                "proxy_connect_timeout": "connect",
                "proxy_read_timeout": "read-interval",
                "proxy_send_timeout": "send-interval",
            }[d.name]
            seconds = parse_duration(raw)
            settings.append(TimeoutSetting(d.name, raw, seconds, kind, d.source, d.line, d.context))
            if seconds is None:
                findings.append(Finding(
                    "DM005", "needs-review", "Unresolved NGINX timeout value",
                    f"{d.name} uses an unsupported or unresolved value: {raw!r}.",
                    [_ev(d.name, raw, d.source, d.line, d.context)],
                    ["Variables and templates are not evaluated."],
                ))
        elif d.name == "keepalive_timeout" and _ctx(d.context, "upstream"):
            raw = d.args[0] if d.args else ""
            seconds = parse_duration(raw)
            settings.append(TimeoutSetting(
                "upstream.keepalive_timeout", raw, seconds,
                "idle-keepalive", d.source, d.line, d.context,
            ))
            if seconds is None:
                findings.append(Finding(
                    "DM005", "needs-review", "Unresolved upstream keep-alive timeout",
                    f"keepalive_timeout uses an unsupported value: {raw!r}.",
                    [_ev("keepalive_timeout", raw, d.source, d.line, d.context)],
                ))

    if gunicorn_path is None:
        return findings, settings

    worker, worker_line = gunicorn.get("worker_class", (None, 0))
    backend_keep, backend_keep_line = gunicorn.get("keepalive", (None, 0))
    backend_timeout, backend_timeout_line = gunicorn.get("timeout", (None, 0))

    if worker is None:
        findings.append(Finding(
            "DM005", "needs-review", "Gunicorn worker class is not explicit",
            "Worker-dependent checks were skipped because worker_class is not a literal setting.",
            [_ev("worker_class", "not explicit", gunicorn_path, 1)],
            ["No worker-class default is inferred."],
        ))
        return findings, settings
    if isinstance(worker, str):
        worker = worker.rsplit(".", 1)[-1]

    keepalive_is_numeric = (
        isinstance(backend_keep, (int, float)) and not isinstance(backend_keep, bool)
    )
    keepalive_is_valid = (
        keepalive_is_numeric and backend_keep >= 0 and float(backend_keep).is_integer()
    )
    if backend_keep is not None and not keepalive_is_valid:
        findings.append(Finding(
            "DM005", "needs-review", "Unsupported Gunicorn keep-alive value",
            f"Gunicorn keepalive must be a non-negative integer; found {backend_keep!r}.",
            [_ev("gunicorn.keepalive", str(backend_keep), gunicorn_path, backend_keep_line)],
            ["The analyzer does not coerce or execute Gunicorn configuration values."],
        ))
    elif keepalive_is_valid:
        settings.append(TimeoutSetting(
            "gunicorn.keepalive", str(backend_keep), float(backend_keep),
            "idle-keepalive", gunicorn_path, backend_keep_line,
        ))
    if backend_timeout is not None and isinstance(backend_timeout, (int, float)):
        settings.append(TimeoutSetting(
            "gunicorn.timeout", str(backend_timeout), float(backend_timeout),
            "worker-silence", gunicorn_path, backend_timeout_line,
        ))

    # DM001: resolve inherited proxy directives for each location. A matching
    # proxy_http_version can inherit from http/server; proxy_set_header uses
    # NGINX's special all-or-nothing inheritance rule.
    if worker in {"gthread", "gevent"} and keepalive_is_valid and float(backend_keep) > 0:
        upstreams = {}
        for d in directives:
            upstream_label = _ctx(d.context, "upstream")
            if upstream_label:
                key = (_scope_of(d), upstream_label)
                upstreams.setdefault(key, {})[d.name] = d

        for (upstream_scope, upstream_label), values in upstreams.items():
            cache = values.get("keepalive")
            proxy_idle = values.get("keepalive_timeout")
            if not cache or not cache.args or not proxy_idle or not proxy_idle.args:
                continue
            try:
                cache_enabled = int(cache.args[0]) > 0
            except ValueError:
                cache_enabled = False
            proxy_seconds = parse_duration(proxy_idle.args[0])
            if not cache_enabled or proxy_seconds is None or proxy_seconds <= float(backend_keep):
                continue

            upstream_name = upstream_label.removeprefix("upstream ")
            root_scope = upstream_scope[:1]
            routes = [
                d for d in directives
                if _is_location_proxy_pass(d)
                and _scope_of(d)[:1] == root_scope
                and d.args[0] in {f"http://{upstream_name}", f"https://{upstream_name}"}
            ]

            for route in routes:
                http_version, http_ambiguous = _effective_single(
                    directives, "proxy_http_version", route
                )
                connection_header, header_ambiguous = _effective_connection_header(
                    directives, route
                )
                if http_ambiguous or header_ambiguous:
                    findings.append(Finding(
                        "DM005", "needs-review", "Ambiguous inherited proxy settings",
                        "Multiple effective proxy directives exist at the same scope; "
                        "DM001 was not evaluated for this route.",
                        [_ev("proxy_pass", route.args[0], route.source, route.line, route.context)],
                        ["Review duplicate proxy_http_version or proxy_set_header directives."],
                    ))
                    continue
                http_ok = (
                    http_version is not None and bool(http_version.args)
                    and http_version.args[0] in {"1.1", "2"}
                )
                conn_clear = (
                    connection_header is not None
                    and len(connection_header.args) == 2
                    and connection_header.args[1] == ""
                )
                if not (http_ok and conn_clear):
                    continue

                findings.append(Finding(
                    "DM001", "needs-review", "Possible upstream idle keep-alive mismatch",
                    f"NGINX's configured upstream idle timeout ({proxy_seconds:g}s) exceeds "
                    f"Gunicorn's keepalive ({float(backend_keep):g}s). "
                    "A stale-connection race is possible, not guaranteed.",
                    [
                        _ev("upstream.keepalive_timeout", proxy_idle.args[0],
                            proxy_idle.source, proxy_idle.line, proxy_idle.context),
                        _ev("upstream.keepalive", cache.args[0],
                            cache.source, cache.line, cache.context),
                        _ev("gunicorn.keepalive", str(backend_keep),
                            gunicorn_path, backend_keep_line),
                        _ev("proxy_pass", route.args[0],
                            route.source, route.line, route.context),
                        _ev("proxy_http_version", http_version.args[0],
                            http_version.source, http_version.line, http_version.context),
                        _ev("proxy_set_header Connection", "",
                            connection_header.source, connection_header.line,
                            connection_header.context),
                    ],
                    [
                        f"Explicit worker_class is {worker}.",
                        "Effective proxy HTTP version and Connection header allow upstream keep-alive.",
                        "Runtime behavior must be reproduced against the target versions.",
                    ],
                ))

    # DM002/DM003: resolve proxy_read_timeout independently for every
    # proxy_pass location, including inherited http/server settings.
    if worker == "sync" and isinstance(backend_timeout, (int, float)):
        worker_seconds = float(backend_timeout)
        routes = [d for d in directives if _is_location_proxy_pass(d)]
        for route in routes:
            read, ambiguous = _effective_single(directives, "proxy_read_timeout", route)
            if ambiguous:
                findings.append(_finding_dm005(
                    "Ambiguous inherited proxy read timeout",
                    "Multiple proxy_read_timeout directives exist at the same effective scope; "
                    "the route was not compared.",
                    route,
                    "Review duplicate directives in the matching http/server/location ancestry.",
                ))
                continue
            if read is None or not read.args:
                continue
            proxy_seconds = parse_duration(read.args[0])
            if proxy_seconds is None or proxy_seconds == worker_seconds:
                continue

            if worker_seconds < proxy_seconds:
                code = "DM002"
                title = "Gunicorn worker timeout is shorter than proxy read interval"
                message = (
                    f"Gunicorn's sync-worker silence timeout is {worker_seconds:g}s while NGINX "
                    f"permits {proxy_seconds:g}s between upstream reads. If the worker stays "
                    "silent, Gunicorn may terminate it first."
                )
            else:
                code = "DM003"
                title = "Proxy read interval is shorter than Gunicorn worker timeout"
                message = (
                    f"NGINX permits {proxy_seconds:g}s between upstream reads while Gunicorn's "
                    f"sync-worker silence timeout is {worker_seconds:g}s. NGINX may close an idle "
                    "response first; application cancellation is runtime-dependent."
                )

            findings.append(Finding(
                code, "needs-review", title, message,
                [
                    _ev("proxy_read_timeout", read.args[0],
                        read.source, read.line, read.context),
                    _ev("gunicorn.timeout", str(backend_timeout),
                        gunicorn_path, backend_timeout_line),
                    _ev("proxy_pass", route.args[0],
                        route.source, route.line, route.context),
                ],
                [
                    "This is a review heuristic, not a guaranteed HTTP status or total request deadline.",
                    "The result depends on response activity and runtime behavior.",
                ],
            ))

    return findings, settings
