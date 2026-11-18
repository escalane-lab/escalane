#!/usr/bin/env python3
"""Tiny health-gated HTTP server for the Escalane homelab demo stack."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", "8080"))
HEALTH_FILE = Path(os.environ.get("HEALTH_FILE", "/data/health"))
SERVICE_NAME = os.environ.get("SERVICE_NAME", "convenience-app")


def healthy() -> bool:
    if not HEALTH_FILE.exists():
        return True
    text = HEALTH_FILE.read_text(encoding="utf-8").strip().lower()
    return text in ("", "ok", "1", "true", "healthy")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            ok = healthy()
            body = b"ok\n" if ok else b"fail\n"
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = f"{SERVICE_NAME} ready\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HEALTH_FILE.exists():
        HEALTH_FILE.write_text("ok\n", encoding="utf-8")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
