"""The HTTP face of the proxy: one ``BaseHTTPRequestHandler`` for Vercel and for ``serve``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler
from typing import Any

from dail_demo import proxy


class ProposeHandler(BaseHTTPRequestHandler):
    environ: Mapping[str, str] = os.environ
    settings: Any = None

    def log_message(self, *args: Any) -> None:
        """Nothing is logged: no path, no header, no body."""

    def _answer(self, method: str) -> None:
        raw = b""
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= proxy.MAX_BODY:
                self.close_connection = True
                return self._send(proxy.Answer(400, {"error": {"code": "bad_request", "message": proxy.BAD_REQUEST}}))
            raw = self.rfile.read(length)
        headers = {name.lower(): value for name, value in self.headers.items()}
        self._send(proxy.handle(method, headers, raw, self.environ, settings=self.settings))

    def _send(self, answer: proxy.Answer) -> None:
        data = json.dumps(answer.body, ensure_ascii=False).encode("utf-8", "replace")
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        self._answer("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._answer("GET")
