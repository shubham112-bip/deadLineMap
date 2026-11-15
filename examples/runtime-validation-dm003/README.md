# Runtime validation: DM003 (NGINX timeout first)

This isolated Docker Compose example exercises the inverse ordering to DM002 using real NGINX and Gunicorn containers. It uses a local test app only and does not connect to an external service.

## Timeout setup

| Component | Setting | Value |
|---|---|---:|
| Gunicorn | `worker_class` | `sync` |
| Gunicorn | `timeout` | 8 seconds |
| NGINX | `proxy_read_timeout` | 2 seconds |
| Test endpoint | response delay | 6 seconds |

The endpoint stays silent for longer than NGINX's read interval but returns before Gunicorn's configured worker-silence timeout. The expected behavior for this exact scenario is **HTTP 504 from NGINX**, while Gunicorn does not log `WORKER TIMEOUT`.

This is a controlled reproduction, not proof that every proxy-first mismatch has the same result. NGINX's `proxy_read_timeout` is an interval between upstream reads, not a whole-response deadline. Gunicorn's timeout behavior depends on worker type.

## Run it

From the repository root, after installing DeadlineMap:

```bash
python -m pip install -e .
deadlinemap scan examples/runtime-validation-dm003 --format json
bash examples/runtime-validation-dm003/verify.sh
```

Requirements: Docker Desktop (or Docker Engine) with Docker Compose v2, plus `curl`. The stack binds only to `127.0.0.1` on port `18081` and is removed automatically when the verification script exits.

To use another local port:

```bash
DEADLINEMAP_DM003_PORT=28081 bash examples/runtime-validation-dm003/verify.sh
```

The static scan should report **DM003** as `needs-review`. The runtime script then checks for HTTP **504** and verifies that Gunicorn did not log `WORKER TIMEOUT`. If the result differs, retain the container logs and investigate before changing the rule.
