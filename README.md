# DeadlineMap

**DeadlineMap** is a read-only Python CLI that inspects supported NGINX and Gunicorn configuration and reports potentially risky timeout relationships with source-file and line-number evidence.

> Current status: early MVP. The first version supports a deliberately limited subset of NGINX configuration and literal module-level settings in `gunicorn.conf.py`. It does not claim to understand every directive, dynamic expression, deployment topology, or runtime behavior.

## What it checks

- **DM001 — upstream idle keep-alive:** a review finding when an explicitly configured NGINX upstream idle-cache timeout exceeds Gunicorn's configured keepalive, but only when an upstream cache and explicit compatible proxy route are found and the worker is `gthread` or `gevent`.
- **DM002 — worker timeout first:** a review finding for an explicit Gunicorn `sync` worker when its worker-silence timeout is shorter than the single unambiguous NGINX `proxy_read_timeout`.
- **DM003 — proxy read interval first:** the inverse ordering for an explicit Gunicorn `sync` worker.
- **DM005 — unresolved configuration:** variables, unsupported values, malformed syntax, unsafe/out-of-root includes, and other constructs the scanner refuses to guess about.

These are static review heuristics, not proof that a deployment will fail. NGINX `proxy_read_timeout` is the interval between successive upstream reads, not a whole-response deadline. Gunicorn's `timeout` is a worker-silence timeout; its behavior depends on worker type. A mismatch therefore normally remains `needs-review` until reproduced in the target environment.

## Requirements

- Python 3.11 or newer
- No runtime third-party dependencies

## Install from a checkout

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
deadlinemap --help
```

## Run a scan

```bash
deadlinemap scan ./path/to/project
deadlinemap scan ./path/to/project --format json
deadlinemap scan ./path/to/project --fail-on needs-review
```

A scan is read-only: it does not execute Gunicorn configuration, start services, send network requests, or modify the scanned project.

## Try the bundled examples

```bash
pytest
deadlinemap scan tests/fixtures/keepalive-mismatch
deadlinemap scan tests/fixtures/worker-first
deadlinemap scan tests/fixtures/proxy-first --format json
```

## Reproduce a live timeout

A small Docker-based NGINX + Gunicorn scenario exercises the DM002 worker-timeout-first case against real containers:

```bash
deadlinemap scan examples/runtime-validation --format json
bash examples/runtime-validation/verify.sh
```

See [the runtime validation guide](examples/runtime-validation/README.md) for the deliberately mismatched settings, observed behavior, and Docker requirements. In this specific run, the request returned HTTP 500 while Gunicorn logged a worker timeout; the status code is runtime-specific.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Scan completed; nothing met the selected `--fail-on` threshold |
| 1 | At least one finding met the selected threshold |
| 2 | Invalid CLI usage |
| 3 | Target path cannot be read or does not exist |
| 4 | No supported configuration entry point was found |

By default, `--fail-on risk` is used. The current MVP emits heuristic findings as `needs-review`; use `--fail-on needs-review` to make those findings fail a CI command.

## Supported input and limitations

- NGINX: files named `nginx.conf`, nested blocks, quoted values, comments, and static includes whose resolved paths remain inside the scanned project root.
- Gunicorn: files named `gunicorn.conf.py` with literal module-level assignments for `worker_class`, `timeout`, and `keepalive`.
- Includes are resolved relative to the including file by this MVP; this is not a complete emulation of NGINX's runtime prefix resolution.
- Dynamic variables, templates, Lua, environment-dependent Python expressions, Gunicorn CLI/Procfile/Docker parsing, all NGINX inheritance rules, and multiple ambiguous topologies are not fully supported.
- The scanner does not infer version-specific defaults.
- Findings are static review hints, not runtime diagnoses or guaranteed HTTP status predictions.

## Development

```bash
python -m pytest
```

See [deadLineMap.md](deadLineMap.md) for the proposal and gated development plan.
