"""The HTTP face of the proxy: one ``BaseHTTPRequestHandler`` for Vercel and for ``serve``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler
from typing import Any

from dail_demo import proxy


# An oversized body up to this size is read and thrown away before the fixed 400 answer, so that the client
# always receives the answer (closing a socket with unread data makes the OS reset the connection instead).
# Anything larger is refused without reading it: answering it is not worth reading megabytes.
MAX_DRAIN = 1_000_000
CHUNK = 65_536


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
                if proxy.MAX_BODY < length <= MAX_DRAIN:
                    self._discard(length)
                self.close_connection = True
                return self._send(proxy.Answer(400, {"error": {"code": "bad_request", "message": proxy.BAD_REQUEST}}))
            raw = self.rfile.read(length)
        headers = {name.lower(): value for name, value in self.headers.items()}
        self._send(proxy.handle(method, headers, raw, self.environ, settings=self.settings))

    def discard_body(self) -> None:
        """Before refusing a POST unread (404, 403): read its body, up to MAX_DRAIN, so the refusal arrives."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= MAX_DRAIN:
            self._discard(length)
        self.close_connection = True

    def _discard(self, length: int) -> None:
        """Read ``length`` bytes of the body and keep none of them."""
        while length > 0:
            chunk = self.rfile.read(min(CHUNK, length))
            if not chunk:
                return
            length -= len(chunk)

    def _send(self, answer: proxy.Answer) -> None:
        data = json.dumps(answer.body, ensure_ascii=False).encode("utf-8", "replace")
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        try:
            self.end_headers()
            self.wfile.write(data)
        except ConnectionError:  # the visitor pressed Stop or left: nobody is waiting for the answer
            self.close_connection = True

    def do_POST(self) -> None:  # noqa: N802
        self._answer("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._answer("GET")
