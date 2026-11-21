"""Optional live network smoke tests (skipped unless FTF_LIVE_TESTS=1)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ftf import capture, config, enrich, sources


@unittest.skipUnless(
    os.environ.get("FTF_LIVE_TESTS") == "1",
    "set FTF_LIVE_TESTS=1 to run live network tests",
)
class TestLiveSmoke(unittest.TestCase):
    def test_live_capture_example_com(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(config, "ARTIFACTS", Path(td)):
            res = capture.capture_url("https://example.com", render=False)
        self.assertFalse(res["cloaking"])
        statuses = [p.get("status") for p in res["profiles"].values()]
        self.assertIn(200, statuses)

    def test_live_capture_nask_pl_csp_nonce_regression(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(config, "ARTIFACTS", Path(td)):
            res = capture.capture_url("https://www.nask.pl/", render=False)
        self.assertFalse(res["cloaking"])

    def test_live_enrich_rdap_example_com(self):
        res = enrich.rdap("example.com")
        self.assertNotIn("error", res)
        self.assertTrue(res.get("nameservers"))
        for ns in res["nameservers"]:
            self.assertFalse(ns.endswith("."))

    def test_live_ms_adlib_search(self):
        rows = sources.ms_adlib_search("inwestycje", top=2)
        self.assertIsInstance(rows, list)


if __name__ == "__main__":
    unittest.main()
