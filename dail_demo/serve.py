"""``python -m dail_demo serve``: the website and the proxy on 127.0.0.1 (PLAN §3.9)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final

from dail_demo.httpd import ProposeHandler
from dail_demo.proxy import REPO_ROOT

HOST: Final = "127.0.0.1"
PATH: Final = "/api/propose"


def make_server(port: int, environ: Mapping[str, str], *, settings: Any = None) -> ThreadingHTTPServer:
    class Handler(ProposeHandler, SimpleHTTPRequestHandler):
        def __init__(self, *args: Any) -> None:
            SimpleHTTPRequestHandler.__init__(self, *args, directory=str(REPO_ROOT / "site"))

        def _local(self) -> bool:
            """Only requests addressed to this machine (a rebound DNS name is refused)."""
            if self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost"):
                return True
            self.send_error(403)
            return False

        def do_GET(self) -> None:  # noqa: N802
            if not self._local():
                return
            if self.path.split("?")[0] == PATH:
                self._answer("GET")
            else:
                SimpleHTTPRequestHandler.do_GET(self)

        def do_HEAD(self) -> None:  # noqa: N802
            if self._local():
                SimpleHTTPRequestHandler.do_HEAD(self)

        def do_POST(self) -> None:  # noqa: N802
            if not self._local():
                return
            if self.path.split("?")[0] == PATH:
                self._answer("POST")
            else:
                self.send_error(404)

    Handler.environ = environ
    Handler.settings = settings
    Handler.extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                              ".mjs": "text/javascript", ".wasm": "application/wasm"}
    class Server(ThreadingHTTPServer):
        request_queue_size = 128  # a browser opens many connections at once
        daemon_threads = True

    return Server((HOST, port), Handler)


def run_serve(port: int) -> int:
    server = make_server(port, os.environ)
    state = "set" if os.environ.get("GEMINI_API_KEY", "").strip() else "not set: the AI tab says so"
    print(f"DAIL Live on http://{HOST}:{server.server_address[1]}/ (GEMINI_API_KEY {state}; Ctrl+C stops it)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
