"""``site/`` is static files only and follows PLAN §3.7 (C work package §2, §5). No DAIL needed.

* no server code in ``site/`` (the one proxy function is ``api/propose.py``, PLAN §3.9), no secret-looking strings, no runtime
  CDN: every script, style, font and module the pages load comes from ``site/`` itself;
* the stylesheet uses only the §3.7 palette, radius 0 except status pills, no gradients, blur,
  glass or CloudShield; fonts are self-hosted woff2 files with their OFL texts;
* every page carries the label "Demo, not part of the DAIL evaluation".
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, REPO_ROOT

SITE = REPO_ROOT / "site"
CSS = SITE / "assets" / "css" / "dail.css"
TOKENS = {"#EEECE5", "#111111", "#E4321B", "#0E8A5F", "#FFD60A", "#2340E0", "#55524A"}
SECRETS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),               # a Google API key
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),              # an AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)gh[pousr]_[0-9A-Za-z]{36}"),          # a GitHub token
    re.compile(re.escape(FAKE_KEY)),
)
OWN_TEXT = (".html", ".css", ".js", ".json", ".md", ".txt", ".toml", ".py")


def own_files() -> list[Path]:
    """The site's own files (not the vendored DAIL, TerraPreserve and Pyodide files)."""
    return [p for p in SITE.rglob("*") if p.is_file() and "vendor" not in p.relative_to(SITE).parts]


class StaticOnlyTests(unittest.TestCase):
    def test_no_server_code(self) -> None:
        self.assertFalse((SITE / "api").exists())
        self.assertFalse((SITE / "vercel.json").exists())  # the one function is api/propose.py (test_proxy)
        for path in own_files():
            with self.subTest(file=path.name):
                self.assertNotIn(path.suffix, (".py", ".php", ".rb", ".go", ".ts", ".cjs"))
                self.assertFalse(path.name in ("package.json", "server.js", "middleware.js"))

    def test_python_only_runs_in_the_browser(self) -> None:
        py = [p.relative_to(SITE).as_posix() for p in SITE.rglob("*.py")]
        self.assertTrue(py)
        for name in py:
            self.assertTrue(name.startswith(("vendor/dail/", "vendor/dail_live/")), name)

    def test_no_secret_looking_strings(self) -> None:
        for path in SITE.rglob("*"):
            if not path.is_file() or path.suffix in (".wasm", ".zip", ".whl", ".woff2"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in SECRETS:
                with self.subTest(file=str(path.relative_to(SITE)), pattern=pattern.pattern[:20]):
                    self.assertIsNone(pattern.search(text))

    def test_no_runtime_cdn(self) -> None:
        loads = re.compile(r"""(?:src|href)\s*=\s*["'](https?:)?//|import\s*\(\s*["']https?:|from\s+["']https?:|url\(\s*["']?https?:""")
        for path in own_files():
            if path.suffix not in (".html", ".css", ".js"):
                continue
            text = path.read_text(encoding="utf-8")
            for match in loads.finditer(text):
                # credits.html links to the projects' pages: links, not loads
                line = text[max(0, match.start() - 120): match.end() + 80]
                with self.subTest(file=path.name, at=match.group(0)):
                    self.assertTrue(path.name == "credits.html" and "<a " in line, line)

    def test_every_page_carries_the_demo_label(self) -> None:
        for page in SITE.glob("*.html"):
            with self.subTest(page=page.name):
                self.assertIn("Demo, not part of the DAIL evaluation", page.read_text(encoding="utf-8"))


class DesignRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = CSS.read_text(encoding="utf-8")

    def test_only_the_palette_tokens(self) -> None:
        colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", self.css)}
        self.assertEqual(colours - TOKENS, set())
        self.assertEqual(re.findall(r"\b(?:rgb|rgba|hsl|hsla)\(", self.css), [])
        # the hatch's SVG uses ink only (%23 is "#")
        self.assertEqual({c.upper() for c in re.findall(r"%23([0-9A-Fa-f]{6})", self.css)}, {"111111"})
        named = re.findall(r":\s*(?:white|black|red|green|blue|yellow|gray|grey|transparent)\b", self.css)
        self.assertEqual(named, [])

    def test_each_colour_token_is_used_only_for_its_meaning(self) -> None:
        def rules_using(token: str) -> list[str]:
            return [m.group(1).strip() for m in re.finditer(r"([^{}]+)\{[^}]*var\(--" + token + r"\)[^}]*\}", self.css)]

        for token, allowed in (
            ("signal-red", ("fail", "reject", "bad")),
            ("signal-green", ("pass", "promote", "ok")),
            ("marker", ("affected",)),
            ("cobalt", ("carried", "focus", "a {", "a")),
        ):
            for selector in rules_using(token):
                with self.subTest(token=token, selector=selector):
                    if selector.startswith(":root"):
                        continue
                    self.assertTrue(any(word in selector for word in allowed) or selector in ("a",), selector)

    def test_no_radius_except_pills(self) -> None:
        for match in re.finditer(r"border-radius\s*:\s*([^;]+);", self.css):
            self.assertIn(match.group(1).strip(), ("var(--radius)", "var(--pill)"))
        self.assertIn("--radius: 0;", self.css)

    def test_no_gradient_blur_glass_or_cloudshield(self) -> None:
        for path in own_files():
            if path.suffix not in (".html", ".css", ".js"):
                continue
            text = path.read_text(encoding="utf-8").lower()
            for word in ("gradient(", "blur(", "backdrop-filter", "cloudshield", "text-shadow"):
                with self.subTest(file=path.name, word=word):
                    self.assertNotIn(word, text)

    def test_hard_shadows_only(self) -> None:
        for match in re.finditer(r"box-shadow\s*:\s*([^;]+);", self.css):
            value = match.group(1).strip()
            if value.startswith("var(--shadow)") or value == "none":
                continue
            parts = value.replace("var(--ink)", "").split()
            self.assertLessEqual(len(parts), 3, value)  # x y blur: the blur must be 0
            if len(parts) == 3:
                self.assertEqual(parts[2], "0", value)

    def test_fonts_are_self_hosted_with_their_licences(self) -> None:
        fonts = SITE / "assets" / "fonts"
        for name in ("archivo-latin-wdth-wght.woff2", "instrument-serif-latin-400-italic.woff2",
                     "ibm-plex-mono-latin-400-normal.woff2", "ibm-plex-mono-latin-600-normal.woff2"):
            self.assertTrue((fonts / name).is_file(), name)
            self.assertIn(name, self.css)
        for name in ("OFL-Archivo.txt", "OFL-InstrumentSerif.txt", "OFL-IBMPlexMono.txt"):
            self.assertIn("SIL Open Font License", (fonts / name).read_text(encoding="utf-8"))
        self.assertEqual(self.css.count("font-display: swap"), self.css.count("@font-face"))

    def test_reduced_motion_switches_every_animation_off(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("html.reduce-motion *", self.css)


if __name__ == "__main__":
    unittest.main()
