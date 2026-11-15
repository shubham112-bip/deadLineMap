"""WSGI probe for upstream keep-alive connection reuse."""

import json


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")

    if path == "/health":
        payload = {"status": "ok"}
    elif path == "/connection-info":
        payload = {
            "remote_addr": environ.get("REMOTE_ADDR"),
            "remote_port": environ.get("REMOTE_PORT"),
        }
    else:
        payload = {"error": "not found"}

    status = "200 OK" if path in {"/health", "/connection-info"} else "404 Not Found"
    body = (json.dumps(payload) + "\n").encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]
