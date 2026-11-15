# DeadlineMap

**DeadlineMap** is a read-only Python CLI that inspects supported NGINX and Gunicorn configuration and reports potentially risky timeout relationships with source-file and line-number evidence.

> Current status: early MVP. The first version supports a deliberately limited subset of NGINX configuration and literal module-level settings in gunicorn.conf.py. It does not claim to understand every directive, dynamic expression, deployment topology, or runtime behavior.

## What it checks

- **DM001 — upstream idle keep-alive:** a review finding when an explicitly configured NGINX upstream idle-cache timeout exceeds Gunicorn's configured keepalive, but only when an upstream cache and explicit compatible proxy route are found and the worker is gthread or gevent. This is a stale-connection risk heuristic; NGINX may reconnect cleanly.
- **DM002 — worker timeout first:** a review finding for an explicit Gunicorn sync worker when its worker-silence timeout is shorter than the single unambiguous NGINX proxy_read_timeout.
- **DM003 — proxy read interval first:** the inverse ordering for an explicit Gunicorn sync worker.
- **DM005 — unresolved configuration:** variables, unsupported values, malformed syntax, unsafe/out-of-root includes, and other constructs the scanner refuses to guess about.

These are static review heuristics, not proof that a deployment will fail. NGINX proxy_read_timeout is the interval between successive upstream reads, not a whole-response deadline. Gunicorn's timeout is a worker-silence timeout; its behavior depends on worker type. A mismatch therefore normally remains needs-review until reproduced in the target environment.

## Requirements

- Python 3.11 or newer
- No runtime third-party dependencies

## Install from a checkout

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
~~~

## Run a scan

The shortest command is to pass the project folder directly:

~~~bash
deadlinemap .
~~~

You can also scan a specific project or config file:

~~~bash
deadlinemap ./path/to/project
deadlinemap ./path/to/project/nginx.conf
~~~

The default output is deliberately simple: it shows what may be wrong, the exact file and line, and what to check next. It hides internal rule IDs and technical evidence. Use `--details` only when you need the full technical report. DeadlineMap checks supported NGINX and Gunicorn timeout settings; it is not a general-purpose application-code bug finder.

Example:

~~~text
DeadlineMap
Project: analysis-input
Checked: 1 NGINX config file, 1 Gunicorn config file

1 item needs a closer look

1. Gunicorn timeout value cannot be checked
   File: gunicorn.conf.py:37
   Problem: The timeout value is calculated by Python code or an environment variable. DeadlineMap does not run that code, so it cannot know the value used by the running application.
   What to do: Check the final value in the environment where the application runs.

DeadlineMap checks NGINX and Gunicorn timeout settings; it does not find general bugs in application code.
~~~

For the full technical report, use:

~~~bash
deadlinemap . --details
~~~

For scripts and CI, use JSON:

~~~bash
deadlinemap . --format json
~~~

The previous explicit form remains supported:

~~~bash
deadlinemap scan ./path/to/project
~~~

To make a scan fail when review is needed:

~~~bash
deadlinemap . --fail-on needs-review
~~~

A scan is read-only: it does not execute Gunicorn configuration, start services, send network requests, or modify the scanned project.

## Try the bundled examples

~~~bash
pytest
deadlinemap tests/fixtures/keepalive-mismatch
deadlinemap tests/fixtures/worker-first
deadlinemap tests/fixtures/proxy-first --format json
~~~

## Reproduce a live timeout

Docker-based NGINX + Gunicorn scenarios exercise DM001 (upstream idle keep-alive), DM002 (worker timeout first), and DM003 (proxy read interval first) against real containers:

~~~bash
deadlinemap examples/runtime-validation-dm001
bash examples/runtime-validation-dm001/verify.sh
deadlinemap examples/runtime-validation
bash examples/runtime-validation/verify.sh
deadlinemap examples/runtime-validation-dm003
bash examples/runtime-validation-dm003/verify.sh
~~~

See the DM001, DM002, and DM003 runtime guides for the controlled scenarios and Docker requirements. DM001 checks upstream connection reuse/rotation, DM002 observed HTTP 500 with a Gunicorn worker timeout, and DM003 checks the proxy-first case.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Scan completed; nothing met the selected --fail-on threshold |
| 1 | At least one finding met the selected threshold |
| 2 | Invalid CLI usage |
| 3 | Target path cannot be read or does not exist |
| 4 | No supported configuration entry point was found |

By default, --fail-on risk is used. The current MVP emits heuristic findings as needs-review; use --fail-on needs-review to make those findings fail a CI command.

## Supported input and limitations

- NGINX: files named nginx.conf, nested blocks, quoted values, comments, static includes whose resolved paths remain inside the scanned project root, and parent-to-child inheritance for selected proxy directives (proxy_read_timeout, proxy_http_version, and proxy_set_header).
- Gunicorn: files named gunicorn.conf.py with literal module-level assignments for worker_class, timeout, and keepalive.
- Includes are resolved relative to the including file by this MVP; this is not a complete emulation of NGINX's runtime prefix resolution.
- Dynamic variables, templates, Lua, environment-dependent Python expressions, Gunicorn CLI/Procfile/Docker parsing, complete NGINX inheritance semantics, and all ambiguous topologies are not fully supported. Duplicate effective scalar directives are treated as unresolved instead of guessed.
- The scanner does not infer version-specific defaults.
- Findings are static review hints, not runtime diagnoses or guaranteed HTTP status predictions.

## Development

~~~bash
python -m pytest
~~~

See deadLineMap.md for the proposal and gated development plan.
