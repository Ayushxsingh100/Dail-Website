"""``site/`` is static files only and follows PLAN §3.7, Mint and tomato (D package §4, §6). No DAIL needed.

* no server code in ``site/`` (the one proxy function is ``api/propose.py``, PLAN §3.9), no secret-looking strings, no runtime
  CDN: every script, style, font and module the pages load comes from ``site/`` itself;
* the design guards: only the §4.2 colour tokens, only Poppins and IBM Plex Mono, no animation on the page body or
  background, hard shadows, the §4.4 radii, and the contrast table of D-40;
* every page carries the label "Demo, not part of the DAIL evaluation".
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, REPO_ROOT

SITE = REPO_ROOT / "site"
CSS = SITE / "assets" / "css" / "dail.css"
TOKENS = {
    "mint": "#DDF2E6", "mint-soft": "#F1FAF5", "mint-hover": "#C6EAD6", "white": "#FFFFFF", "ink": "#0D1B2A",
    "ink-muted": "#48566A", "ink-muted-on-mint": "#33445A", "tomato": "#FF5A36", "tomato-soft": "#FFD9CF",
    "pass": "#0E8A5F", "pass-soft": "#CFEFDD", "fail": "#C0262D", "fail-soft": "#FBD9D9", "marker": "#FFD60A",
    "carry": "#2340E0", "carry-soft": "#DCE3FF",
}  # fmt: skip
FONTS = {"Poppins", "IBM Plex Mono"}
GENERIC = {"system-ui", "sans-serif", "ui-monospace", "monospace", "inherit", "var(--font)", "var(--mono)"}
# D-40: (text, background) -> the ratio recorded. Body text needs 4.5:1; LARGE_ONLY pairs are set large (3:1).
CONTRAST = {
    ("ink", "mint"): 14.84, ("ink", "white"): 17.39, ("ink", "mint-soft"): 16.34, ("ink", "mint-hover"): 13.37,
    ("ink", "tomato"): 5.61, ("ink", "tomato-soft"): 13.32, ("ink", "marker"): 12.32, ("ink", "pass-soft"): 14.12,
    ("ink", "fail-soft"): 13.28, ("ink", "carry-soft"): 13.65, ("ink-muted", "white"): 7.46,
    ("ink-muted", "mint-soft"): 7.01, ("ink-muted-on-mint", "mint"): 8.47, ("white", "ink"): 17.39,
    ("white", "fail"): 5.90, ("white", "pass"): 4.36, ("carry", "white"): 7.29, ("carry", "mint"): 6.22,
}  # fmt: skip
LARGE_ONLY = {("white", "pass")}
SECRETS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),               # a Google API key
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),              # an AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)gh[pousr]_[0-9A-Za-z]{36}"),          # a GitHub token
    re.compile(re.escape(FAKE_KEY)),
)


def own_files() -> list[Path]:
    """The site's own files (not the vendored DAIL, TerraPreserve and Pyodide files)."""
    return [p for p in SITE.rglob("*") if p.is_file() and "vendor" not in p.relative_to(SITE).parts]


def luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def css_rules(css: str) -> list[tuple[str, str]]:
    """(selector, declarations) of every rule; @media blocks are flattened, comments removed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@keyframes\s+[\w-]+\s*\{.*?\}\s*\}", "", css, flags=re.S)
    css = re.sub(r"@(?:media|supports)[^{]*\{", "", css)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


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
        self.rules = css_rules(self.css)

    def test_only_the_colour_tokens(self) -> None:
        root = dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;", self.css))
        self.assertEqual({k: v.upper() for k, v in root.items()}, TOKENS)
        rest = re.sub(r"--[a-z-]+:\s*#[0-9A-Fa-f]{6}\s*;", "", self.css)
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{3,8}\b", rest), [])  # every other colour is var(--token)
        self.assertEqual(re.findall(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(", self.css), [])
        named = r":\s*[^;{}]*\b(?:black|red|green|blue|yellow|gray|grey|orange|purple|transparent|silver)\b"
        self.assertEqual(re.findall(named, self.css), [])
        for token in re.findall(r"var\(--([a-z0-9-]+)\)", self.css):
            if not token.startswith(("fs-", "r-", "sh-", "b2", "b3", "font", "mono", "scale")):
                self.assertIn(token, TOKENS)
        # the HTML, the scripts and the favicon carry no colour and no inline style of their own
        for path in own_files():
            if path.suffix in (".html", ".js", ".svg"):
                text = path.read_text(encoding="utf-8")
                with self.subTest(file=path.name):
                    self.assertLessEqual({c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", text)}, set(TOKENS.values()))
                    self.assertNotIn("style=", text)

    def test_each_colour_has_one_meaning(self) -> None:
        allowed = {
            "tomato": ("btn--primary", "logo", "headline__ai"),
            "tomato-soft": ("chip--risky", "gemini__stripe", "banner"),
            "marker": ("marker",),
            "carry": ("carry", "focus-visible"),
            "carry-soft": ("carry",),
            "pass": ("pass", "promote", "--ok", "is-new"),
            "fail": ("fail", "reject", "--bad"),
        }
        for selector, body in self.rules:
            if selector.startswith(":root"):
                continue
            for token, words in allowed.items():
                if re.search(r"var\(--" + token + r"\)", body):
                    with self.subTest(token=token, selector=selector):
                        self.assertTrue(any(w in selector for w in words), selector)
        self.assertIn("--sh-you: 5px 5px 0 var(--tomato);", self.css)  # the "You" bubble's shadow

    def test_only_poppins_and_ibm_plex_mono(self) -> None:
        faces = re.findall(r"@font-face\s*\{[^}]*font-family:\s*\"([^\"]+)\"", self.css)
        self.assertEqual(set(faces), FONTS)
        for value in re.findall(r"(?:font-family|--font|--mono)\s*:\s*([^;]+);", self.css):
            for name in (n.strip().strip('"') for n in value.split(",")):
                with self.subTest(font=name):
                    self.assertTrue(name in FONTS or name in GENERIC, name)
        self.assertEqual(re.findall(r"[;{\s]font\s*:(?!\s*inherit)[^;]+;", self.css), [])  # no shorthand naming a family
        fonts = SITE / "assets" / "fonts"
        files = sorted(p.name for p in fonts.iterdir())
        expected = ["OFL-IBMPlexMono.txt", "OFL-Poppins.txt"]
        expected += [f"poppins-latin-{w}-normal.woff2" for w in (400, 500, 600, 700, 800)]
        expected += [f"ibm-plex-mono-latin-{w}-normal.woff2" for w in (400, 500)]
        self.assertEqual(files, sorted(expected))
        for name in files:
            if name.endswith(".woff2"):
                self.assertIn(name, self.css)
                self.assertEqual((fonts / name).read_bytes()[:4], b"wOF2", name)
            else:
                self.assertIn("SIL Open Font License", (fonts / name).read_text(encoding="utf-8"))
        self.assertEqual(self.css.count("font-display: swap"), self.css.count("@font-face"))
        for path in own_files():
            if path.suffix in (".html", ".css", ".js"):
                text = path.read_text(encoding="utf-8").lower()
                for old in ("archivo", "instrument serif", "instrument-serif", "fonts.googleapis"):
                    with self.subTest(file=path.name, font=old):
                        self.assertNotIn(old, text)

    def test_no_animation_on_the_body_or_the_background(self) -> None:
        keyframes = dict(re.findall(r"@keyframes\s+([\w-]+)\s*\{(.*?\})\s*\}", self.css, flags=re.S))
        self.assertEqual(set(keyframes), {"fill", "land", "slide", "blink"})
        for name, body in keyframes.items():
            with self.subTest(keyframes=name):
                self.assertNotRegex(body, r"background|color|filter")
        page = re.compile(r"^(?:html|body|:root|main|\*)(?:$|[>.\[:#])")
        animated = re.compile(r"\b(?:animation(?:-name)?|transition)\s*:\s*(?!none)")
        for selector, body in self.rules:
            if not animated.search(body) or "!important" in body:  # the reduced-motion rules switch everything off
                continue
            for part in selector.split(","):
                part = part.strip()
                with self.subTest(selector=part):
                    self.assertIsNone(page.match(part), part)
                    self.assertNotRegex(body, r"transition\s*:[^;]*background")

    def test_reduced_motion_switches_every_animation_off(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("html.reduce-motion *", self.css)

    def test_hard_shadows_and_the_radii(self) -> None:
        for match in re.finditer(r"box-shadow\s*:\s*([^;]+);", self.css):
            value = match.group(1).strip()
            if value.startswith("var(--sh-") or value == "none":
                continue
            parts = re.sub(r"var\(--[a-z-]+\)", "", value).split()
            self.assertEqual(len(parts), 3, value)  # x y blur
            self.assertEqual(parts[2], "0", value)
        for name, value in (("sh-prompt", "10px 10px 0 var(--ink)"), ("sh-gemini", "8px 8px 0 var(--ink)"),
                            ("sh-button", "5px 5px 0 var(--ink)"), ("sh-you", "5px 5px 0 var(--tomato)")):
            self.assertIn(f"--{name}: {value};", self.css)
        for name, value in (("r-card", 22), ("r-button", 14), ("r-tab", 10), ("r-chip", 12), ("r-pill", 999), ("r-logo", 10)):
            self.assertIn(f"--{name}: {value}px;", self.css)

    def test_no_gradient_blur_glass_or_cloudshield(self) -> None:
        for path in own_files():
            if path.suffix not in (".html", ".css", ".js"):
                continue
            text = path.read_text(encoding="utf-8").lower()
            for word in ("gradient(", "blur(", "backdrop-filter", "cloudshield", "text-shadow", "hatch"):
                with self.subTest(file=path.name, word=word):
                    self.assertNotIn(word, text)

    def test_the_contrast_table(self) -> None:
        decisions = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        for (text, background), recorded in CONTRAST.items():
            value = ratio(TOKENS[text], TOKENS[background])
            with self.subTest(text=text, background=background):
                self.assertAlmostEqual(value, recorded, delta=0.006)
                self.assertGreaterEqual(value, 3.0 if (text, background) in LARGE_ONLY else 4.5)
                self.assertIn(f"{text} on {background} {recorded:.2f}", decisions)
        # white on --pass (4.36:1) is the PROMOTE stamp only, set large (800, 64 px); the status dot holds no text
        on_pass = [sel for sel, body in self.rules if "background: var(--pass)" in body and sel != ".dot--pass"]
        self.assertEqual(on_pass, [".stamp--promote"])
        stamp = next(body for sel, body in self.rules if sel == ".stamp")
        self.assertIn("font-weight: 800", stamp)
        self.assertIn("calc(64px * var(--scale))", stamp)


if __name__ == "__main__":
    unittest.main()
