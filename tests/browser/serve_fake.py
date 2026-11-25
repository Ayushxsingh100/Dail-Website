"""The real ``serve`` (site and proxy) with a fake Gemini on 127.0.0.1 (D package §4). Tests only.

    python tests/browser/serve_fake.py <seen.json>

Prints the port. The fake answers the canonical regression patch first and, when the prompt carries
DAIL's reason, the safe patch. A visitor text of FAIL ALWAYS, GARBAGE or QUOTA changes that. Every
request the fake Gemini got is written to <seen.json> (never its headers).
"""

from __future__ import annotations

import dataclasses
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from dail_demo import proxy  # noqa: E402

proxy._import_dail()
from dail_demo.evaluate_core import typed_response  # noqa: E402
from dail_demo.serve import make_server  # noqa: E402
from dail_demo.settings import gemini_settings  # noqa: E402

PACK = proxy.VENDOR / "scenarios" / "canonical"
FAKE_KEY = "TEST-KEY-123456"  # gitleaks:allow  (a fake value; see D-11)


def reply(patch: str) -> str:
    made = typed_response(PACK / "s0", PACK / "patches" / patch).to_dict()
    made.pop("confidence")
    return json.dumps({**made, "summary": f"test reply: {patch}", "rationale": "test"})


REPLIES = {name: reply(name) for name in ("regression", "safe")}


def main(seen_file: str) -> None:
    seen: list[dict] = []

    class Gemini(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            task = body["contents"][0]["parts"][0]["text"]
            seen.append({"task": task, "system": body["systemInstruction"]["parts"][0]["text"], "path": self.path})
            Path(seen_file).write_text(json.dumps(seen), encoding="utf-8")
            time.sleep(0.8)
            retry = "Your previous patch was rejected by DAIL" in task
            status, text = 200, REPLIES["safe" if retry else "regression"]
            if "FAIL ALWAYS" in task:
                text = REPLIES["regression"]
            elif "GARBAGE" in task and not retry:
                text = "Sure! Here is <b>a fix</b>."
            elif "QUOTA" in task:
                status = 429
            data = json.dumps({
                "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            }).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Gemini)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    settings = dataclasses.replace(
        gemini_settings(), endpoint=f"http://127.0.0.1:{fake.server_address[1]}", timeout_seconds=20.0
    )
    server = make_server(0, {"GEMINI_API_KEY": FAKE_KEY}, settings=settings)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1])
