# Runtime validation: DM001 (upstream idle keep-alive)

This isolated Docker Compose example exercises DM001 with a real NGINX + Gunicorn stack. It deliberately checks connection reuse and idle-connection rotation instead of assuming the mismatch must produce an HTTP error.

## Timeout setup

| Component | Setting | Value |
|---|---|---:|
| Gunicorn | `worker_class` | `gthread` |
| Gunicorn | `keepalive` | 2 seconds |
| NGINX | upstream `keepalive_timeout` | 10 seconds |
| NGINX | upstream `keepalive` cache | 8 idle connections |

The app exposes a diagnostic endpoint that returns the TCP peer port seen by Gunicorn. Two immediate requests should reuse the same NGINX-to-Gunicorn connection. After a 4-second idle gap, Gunicorn should have closed its 2-second keep-alive connection even though NGINX's configured idle-cache timeout is 10 seconds.

A normal outcome is that NGINX notices the closed upstream connection and opens a fresh one. A stale-connection race can instead surface as an upstream error. Neither outcome is guaranteed across every timing, OS, or software version. The static DM001 result therefore remains `needs-review`, not a guaranteed failure.

## Run it

From the repository root:

```bash
deadlinemap scan examples/runtime-validation-dm001 --format json
bash examples/runtime-validation-dm001/verify.sh
```

Requirements: Docker Desktop (or Docker Engine) with Docker Compose v2, plus `curl` and Python 3 for parsing the response. The stack binds only to `127.0.0.1` on port `18082` and is removed automatically when the verification script exits.

To use another local port:

```bash
DEADLINEMAP_DM001_PORT=28082 bash examples/runtime-validation-dm001/verify.sh
```

A passing test confirms that the configured upstream connection was reused and then rotated after Gunicorn's shorter idle keep-alive. It does **not** claim to have reproduced an HTTP failure unless the script explicitly reports the observed HTTP 502 branch.
