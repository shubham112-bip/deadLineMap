# Runtime validation: NGINX + Gunicorn

This isolated Docker Compose example checks one real runtime behavior behind **DM002**. It is intentionally small and uses only a local test app; it does not connect to an external service.

## Timeout setup

| Component | Setting | Value |
|---|---|---:|
| Gunicorn | `worker_class` | `sync` |
| Gunicorn | `timeout` | 2 seconds |
| NGINX | `proxy_read_timeout` | 10 seconds |
| Test endpoint | response delay | 6 seconds |

The request takes longer than Gunicorn's configured worker-silence timeout but less than NGINX's configured upstream read interval. In the live run with this pinned scenario, the request returned **HTTP 500** and Gunicorn logged `WORKER TIMEOUT`. This is the observed behavior of this exact setup; it is not a universal status-code prediction.

This is one controlled reproduction, not proof that every timeout mismatch causes the same status code. NGINX's `proxy_read_timeout` is an interval between upstream reads, not a whole-response deadline. Gunicorn's timeout behavior depends on its worker implementation.

## Run it

From the repository root, after installing DeadlineMap:

```bash
python -m pip install -e .
deadlinemap scan examples/runtime-validation --format json
bash examples/runtime-validation/verify.sh
```

Requirements: Docker Desktop (or Docker Engine) with the Docker Compose v2 plugin, plus `curl`. The test stack binds only to `127.0.0.1` on port `18080` and is removed automatically when the verification script exits.

To use a different local port:

```bash
DEADLINEMAP_PORT=28080 bash examples/runtime-validation/verify.sh
```

The scanner should report **DM002** as `needs-review`. The runtime script then checks for both an HTTP **500** response and Gunicorn's `WORKER TIMEOUT` log entry. If the observed result differs, retain the container logs; do not change the rule based on a single unexplained result.
