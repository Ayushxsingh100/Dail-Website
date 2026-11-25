"""Vercel Python function ``/api/propose``: the Gemini proxy (PLAN §3.9). See dail_demo/proxy.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dail_demo.httpd import ProposeHandler  # noqa: E402


class handler(ProposeHandler):  # noqa: N801 - the name Vercel's Python runtime looks for
    pass
