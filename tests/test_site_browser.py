"""The real page in headless Chromium (C work package §2, §5; D-21), through its own controls.

* live mode: the regression quick-fill is REJECTED by DAIL while target-only says PROMOTE, the safe
  one is PROMOTED (two clippings), a third typed patch from v1 is PROMOTED (three clippings: promote,
  reject, promote leaves DAIL's lineage), "Verify chain" passes, an edit outside resource blocks is
  refused before DAIL with DAIL's reason, Reset returns to S0; each live decision carries "Terraform
  validation is not run in the browser"; the decisions equal the native engine's;
* replays: every recorded run renders its recorded decisions and check counts, without Pyodide;
* reduced motion and presenter mode classes apply; presenter mode fits at 1366x768; no horizontal
  page scroll at 390, 768 and 1366 px; no console errors and no failed request.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, DataDirCase, dail_root
from tests.test_browser import BROWSER_DIR, node_ready


class SiteInBrowserTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        node = node_ready()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "check.json"
            done = subprocess.run(
                [node, str(BROWSER_DIR / "site.mjs"), str(REPO_ROOT / "site"), sys.executable, "check", str(out)],
                cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=900,
            )
            if done.returncode != 0:
                raise AssertionError(f"the page check failed:\n{done.stdout}\n{done.stderr}")
            cls.r = json.loads(out.read_text(encoding="utf-8"))
        print(f"\n  live ready in {cls.r['liveReadyMs']} ms; first load: replays "
              f"{cls.r['firstLoad_replays']}, live {cls.r['firstLoad_live']}", end="")

    def test_live_decisions_equal_the_native_engine(self) -> None:
        from dail_demo.engine import run_evaluate

        for patch in ("regression", "safe"):
            with self.subTest(patch=patch):
                native = run_evaluate("canonical", patch, environ=self.environ).trace["comparison"]
                shown = self.r[patch]
                self.assertEqual(shown["stamp"], native["C"]["decision"])
                self.assertEqual(shown["ovf"], [
                    {"verdict": native["A"]["decision"], "count": str(native["A"]["check_count"])},
                    {"verdict": native["C"]["decision"], "count": str(native["C"]["check_count"])},
                ])
                self.assertEqual(shown["note"], "Terraform validation is not run in the browser.")

    def test_promote_reject_promote_in_the_tab(self) -> None:
        self.assertEqual(self.r["regression"]["clippings"], ["v0"])
        self.assertEqual(self.r["safe"]["clippings"], ["v1", "v0"])
        self.assertEqual(self.r["safe"]["stamp"], "PROMOTE")
        self.assertEqual(self.r["rejectFromV1"]["stamp"], "REJECT")
        self.assertEqual(self.r["rejectFromV1"]["clippings"], ["v1", "v0"])
        self.assertTrue(self.r["thirdEdit"])
        self.assertEqual(self.r["third"]["stamp"], "PROMOTE")
        self.assertEqual(self.r["third"]["clippings"], ["v2", "v1", "v0"])
        self.assertIn("Chain verified by DAIL: 3 trusted states, 4 candidates", self.r["verifyAfterThree"])

    def test_the_stages_fill_while_dail_works(self) -> None:
        fills = self.r["fills"]
        self.assertEqual([f["done"] for f in fills], [1, 2, 3, 4, 5])  # one by one, in order
        self.assertFalse(any(f["stamp"] for f in fills))  # before the trace and the stamp
        times = [f["t"] for f in fills]
        self.assertEqual(times, sorted(times))
        self.assertGreater(times[-1] - times[0], 50)  # spread over DAIL's own work, not one burst

    def test_switching_modes_keeps_the_session(self) -> None:
        self.assertTrue(self.r["verifyHiddenInReplays"])
        for key in ("clippings", "stamp", "issue"):
            self.assertEqual(self.r["resumed"][key], self.r["third"][key])

    def test_presenter_mode_fits_in_live_mode(self) -> None:
        fits = self.r["presenterLive"]
        for key in ("stages", "stamp", "ovf", "ledger", "newest"):
            self.assertLessEqual(fits[key], fits["vh"], key)
        self.assertEqual(fits["clippings"], 3)  # every state is there
        self.assertTrue(fits["mastheadKept"])
        self.assertGreaterEqual(fits["labelTop"], 0)  # the demo label stays visible
        self.assertEqual(fits["over"], [])

    def test_the_candidate_card_crosses_the_trust_boundary(self) -> None:
        crossing = self.r["crossing"]
        self.assertLess(crossing["min"], crossing["boundary"])
        self.assertGreater(crossing["max"], crossing["boundary"])
        self.assertFalse(crossing["left"])

    def test_a_refusal_before_dail_and_reset(self) -> None:
        self.assertTrue(self.r["refusal"]["refused"])
        self.assertIsNone(self.r["refusal"]["stamp"])
        self.assertIn("outside resource blocks", self.r["refusalText"])
        self.assertEqual(self.r["refusal"]["clippings"], ["v2", "v1", "v0"])
        self.assertEqual(self.r["afterReset"]["clippings"], ["v0"])
        self.assertTrue(self.r["afterReset"]["issue"].startswith("Session 02 · Candidate 00 · Trusted state v0"))

    def test_loading_state_names_the_real_size(self) -> None:
        listing = json.loads((REPO_ROOT / "site" / "vendor" / "files.json").read_text(encoding="utf-8"))
        mb = (listing["size"] + listing["pyodide"]["size"]) / 1e6
        self.assertEqual(self.r["loadingTitle"], f"Loading DAIL into your browser (~{mb:.1f} MB)")

    def test_every_replay_renders_its_recorded_decisions(self) -> None:
        self.assertEqual(len(self.r["replays"]), len(json.loads((REPO_ROOT / "site" / "runs" / "index.json").read_text(encoding="utf-8"))["runs"]))
        for replay in self.r["replays"]:
            with self.subTest(run=replay["file"]):
                self.assertEqual(replay["shown"]["stamp"], replay["expected"]["C"])
                self.assertEqual([c["verdict"] for c in replay["shown"]["ovf"]], [replay["expected"]["A"], replay["expected"]["C"]])
                if "gemini" in replay["file"]:
                    self.assertGreater(replay["gemini"], 0)
        self.assertFalse(self.r["pyodideRequestedInReplays"])
        self.assertLess(self.r["firstLoad_replays"]["bytes"], 1_000_000)
        self.assertGreater(self.r["firstLoad_live"]["bytes"], 15_000_000)  # the worker's downloads are counted

    def test_motion_presenter_and_layout(self) -> None:
        self.assertTrue(self.r["reducedMotionClass"])
        self.assertEqual(self.r["stampAnimation"], "none")
        self.assertTrue(self.r["presenterClass"])
        self.assertEqual(self.r["presenterBodyFont"], "20px")
        fits = self.r["presenterFits"]
        for key in ("stagesBottom", "ledgerBottom"):
            self.assertLessEqual(fits[key], fits["vh"], key)
        for key in ("stamp", "ovf"):
            self.assertLessEqual(fits[key]["bottom"], fits["vh"], key)
        self.assertEqual(self.r["noHorizontalScroll"], {"390": True, "768": True, "1366": True})

    def test_no_console_errors_or_failed_requests(self) -> None:
        self.assertEqual(self.r["liveLog"], [])
        self.assertEqual(self.r["replayLog"], [])


if __name__ == "__main__":
    unittest.main()
