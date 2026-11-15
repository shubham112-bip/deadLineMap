"""Tiny WSGI app for the DeadlineMap runtime-validation scenario."""

import time


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")

    if path == "/health":
        body = b"ok\n"
    elif path == "/slow":
        # Longer than Gunicorn's 2s worker-silence timeout, but shorter than
        # NGINX's 10s proxy_read_timeout.
        time.sleep(6)
        body = b"finished after six seconds\n"
    else:
        body = b"not found\n"

    status = "200 OK" if path in {"/health", "/slow"} else "404 Not Found"
    start_response(
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]
