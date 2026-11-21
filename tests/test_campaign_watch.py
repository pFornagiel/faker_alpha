"""Offline tests for the campaign watch (pivot search on known campaigns' own identifiers).

All network calls are mocked and every test uses a temporary SQLite store — the real data/store is never touched.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ftf import ingest, scheduler, sources
from ftf.engine import Engine
from ftf.store import Store

ADV = "AR12345678901234567890"


def _feat(name: str, indicators: dict, product: str | None = None) -> dict:
    return {"name": name, "indicators": indicators, "llm": {"product_or_platform_name": product} if product else {}}


def _engine(td: str) -> Engine:
    st = Store(Path(td) / "watch.sqlite")
    rows = [
        ("m1", _feat("m1", {"landing_domain": ["healthlinkq.pro"], "page_host": ["cdn-common-host.com"],
                            "product": ["orzel fundaris"]})),
        ("m2", _feat("m2", {"landing_domain": ["healthlinkq.pro"], "page_host": ["cdn-common-host.com"],
                            "product": ["orzel fundaris"], "ocr_domain": ["interia.pl"]})),
        ("m3", _feat("m3", {"landing_domain": ["other-scam.top"], "page_host": ["cdn-common-host.com"],
                            "product": ["facebook"], "advertiser_id": [ADV], "ad_id": ["library=4414624315417273"]})),
    ]
    for mid, f in rows:
        st.upsert(ingest.Material(id=mid, name=mid, source="test", source_ref=mid), f, {})
    return Engine(store=st)


def _campaign_of(eng: Engine, mid: str) -> int:
    return eng.clustering()["campaign_of"][mid]


class _Mocks:
    """Patch every public source used by the watch; record what was queried."""

    def __init__(self):
        self.calls: list[tuple] = []

    def atc(self, domain=None, advertiser_id=None, n=40):
        self.calls.append(("google_atc", domain or advertiser_id))
        key = domain or advertiser_id
        return [{"source": "google_atc", "advertiser_id": "AR999", "creative_id": f"CR-{key}", "domain": key}]

    def ms(self, keyword, top=25):
        self.calls.append(("ms_adlib", keyword))
        return [{"source": "ms_adlib", "ad_id": f"ms-{keyword}", "url": f"https://lp.example/{keyword.replace(' ', '-')}",
                 "title": keyword}]

    def meta(self, keyword, days=7, limit=50):
        self.calls.append(("meta_api", keyword))
        return []

    def cert(self, store, stems, limit=200):
        self.calls.append(("cert_pl", tuple(stems)))
        return [{"source": "cert_pl", "domain": "healthlinkq-pl.click", "url": "https://healthlinkq-pl.click/",
                 "match": ["healthlinkq"]}]

    def patches(self):
        return [mock.patch.object(sources, "google_atc_creatives", side_effect=self.atc),
                mock.patch.object(sources, "ms_adlib_search", side_effect=self.ms),
                mock.patch.object(sources, "meta_api_search", side_effect=self.meta),
                mock.patch.object(sources, "cert_pl_watch", side_effect=self.cert),
                mock.patch.object(scheduler, "REQUEST_PAUSE", 0)]


def _run_patched(mocks: _Mocks, fn):
    ps = mocks.patches()
    for p in ps:
        p.start()
    try:
        return fn()
    finally:
        for p in reversed(ps):
            p.stop()


class TestCampaignSeeds(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.eng = _engine(self.td.name)

    def tearDown(self):
        self.eng.store.db.close()
        self.td.cleanup()

    def test_seeds_are_counted_identifiers_without_generic_or_brand_values(self):
        seeds = scheduler.campaign_seeds(self.eng)
        c12, c3 = _campaign_of(self.eng, "m1"), _campaign_of(self.eng, "m3")
        self.assertEqual(c12, _campaign_of(self.eng, "m2"))
        vals = {(s["campaign"], s["group"], s["value"]) for s in seeds}
        self.assertIn((c12, "domains", "healthlinkq.pro"), vals)
        self.assertIn((c12, "product", "orzel fundaris"), vals)
        self.assertIn((c3, "ad_library", ADV), vals)
        flat = {s["value"] for s in seeds}
        self.assertNotIn("cdn-common-host.com", flat)       # held by 3/3 materials: df/N > MAX_DF, not counted
        self.assertNotIn("interia.pl", flat)                # decoy media domain
        self.assertNotIn("facebook", flat)                  # real brand name -> legitimate ads
        self.assertNotIn("library=4414624315417273", flat)  # an ad ID names one ad, not an advertiser
        dom = next(s for s in seeds if s["value"] == "healthlinkq.pro")
        self.assertEqual(dom["sources"], ["google_atc", "ms_adlib", "cert_pl"])
        self.assertEqual(dom["cert_stem"], "healthlinkq")
        adv = next(s for s in seeds if s["value"] == ADV)
        self.assertEqual(adv["sources"], ["google_atc"])
        prod = next(s for s in seeds if s["value"] == "orzel fundaris")
        self.assertEqual(prod["cert_stem"], "orzelfundaris")

    def test_seed_order_and_caps(self):
        seeds = scheduler.campaign_seeds(self.eng, max_campaigns=1, max_seeds=1)
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["campaign"], _campaign_of(self.eng, "m1"))   # multi-material campaign first
        self.assertEqual(seeds[0]["group"], "domains")
        one = scheduler.campaign_seeds(self.eng, campaigns=[_campaign_of(self.eng, "m3")])
        self.assertTrue(one and all(s["campaign"] == _campaign_of(self.eng, "m3") for s in one))

    def test_non_google_advertiser_id_is_skipped(self):
        srcs, stem, note = scheduler._seed_plan("ad_library", "1183383648198728")
        self.assertEqual(srcs, [])
        self.assertIsNone(stem)
        self.assertTrue(note)


class TestWatchCampaigns(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.eng = _engine(self.td.name)

    def tearDown(self):
        self.eng.store.db.close()
        self.td.cleanup()

    def test_hits_carry_seed_provenance_and_are_deduplicated(self):
        # an item found earlier by the keyword scan: kept once, provenance added
        self.eng.store.put("scheduler_found", [{"source": "ms_adlib", "url": "https://lp.example/healthlinkq.pro", "score": 0.1,
                                                "why": []}])
        m = _Mocks()
        out = _run_patched(m, lambda: scheduler.watch_campaigns(self.eng))
        queried = {c for c in m.calls if c[0] != "cert_pl"}
        self.assertIn(("google_atc", "healthlinkq.pro"), queried)
        self.assertIn(("ms_adlib", "healthlinkq.pro"), queried)
        self.assertIn(("ms_adlib", "orzel fundaris"), queried)
        self.assertIn(("google_atc", ADV), queried)
        self.assertNotIn(("ms_adlib", "facebook"), queried)
        self.assertEqual(sum(1 for c in m.calls if c[0] == "cert_pl"), 1)    # one CERT pass for all stems
        self.assertTrue(out["hits"])
        for h in out["hits"]:
            self.assertEqual(set(h["seed"]), {"campaign", "campaign_label", "group", "type", "value", "source"})
        cert = next(h for h in out["hits"] if h["source"] == "cert_pl")
        self.assertEqual(cert["seed"]["value"], "healthlinkq.pro")
        self.assertEqual(cert["seed"]["campaign"], _campaign_of(self.eng, "m1"))
        # ordered by campaign (largest first), then source
        order = [(h["seed"]["campaign"] != _campaign_of(self.eng, "m1"), h["seed"]["source"]) for h in out["hits"]]
        self.assertEqual(order, sorted(order))

        stored = self.eng.store.get("scheduler_found")
        old = [x for x in stored if x.get("url") == "https://lp.example/healthlinkq.pro"]
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0]["seed"]["value"], "healthlinkq.pro")
        self.assertEqual(out["fresh"], len(stored) - 1)
        self.assertEqual(self.eng.store.get("watch_last")["seeds"], out["seeds"])
        kinds = {e["kind"] for e in self.eng.store.events(200)}
        self.assertIn("watch_scan", kinds)
        self.assertIn("watch_run", kinds)

        again = _run_patched(_Mocks(), lambda: scheduler.watch_campaigns(self.eng))
        self.assertEqual(again["fresh"], 0)
        self.assertEqual(len(self.eng.store.get("scheduler_found")), len(stored))

    def test_source_error_is_recorded_not_raised(self):
        m = _Mocks()

        def boom(**_kw):
            raise RuntimeError("429 rate limited")

        m.atc = boom
        out = _run_patched(m, lambda: scheduler.watch_campaigns(self.eng))
        self.assertTrue(any(k.startswith("google_atc:") for k in out["errors"]))
        self.assertTrue(any(h["source"] == "ms_adlib" for h in out["hits"]))

    def test_analysis_outcome_comes_from_normal_assignment(self):
        c12 = _campaign_of(self.eng, "m1")
        c3 = _campaign_of(self.eng, "m3")

        def fake_analyse(engine, r, allow_domain=False):
            self.assertTrue(allow_domain)
            same = r["seed"]["campaign"] == c12 and r["source"] == "cert_pl"
            return {"decision": "known_campaign" if same else "new_campaign", "campaign": c12 if same else None,
                    "material": SimpleNamespace(id=f"new-{r['source']}")}

        with mock.patch.object(scheduler, "_analyse_hit", side_effect=fake_analyse):
            out = _run_patched(_Mocks(), lambda: scheduler.watch_campaigns(self.eng, analyse=True, max_analyse=50))
        self.assertTrue(out["analysed"])
        conf = [a for a in out["analysed"] if a["confirmed"]]
        self.assertEqual(len(conf), 1)
        self.assertEqual(conf[0]["campaign_label"], f"C{c12 + 1}")
        self.assertEqual(out["confirmed"], 1)
        stored = {x.get("url"): x for x in self.eng.store.get("scheduler_found")}
        self.assertTrue(stored["https://healthlinkq-pl.click/"]["outcome"]["confirmed"])
        others = [x for x in stored.values() if x.get("outcome") and not x["outcome"]["confirmed"]]
        self.assertTrue(others)
        self.assertTrue(all(x["outcome"]["decision"] == "new_campaign" for x in others))
        self.assertNotEqual(c12, c3)

    def test_run_once_includes_watch_when_flagged(self):
        m = _Mocks()
        with mock.patch.object(sources, "cert_pl_new", return_value=[]), \
                mock.patch.object(sources, "google_atc_suggest", return_value=[]):
            out = _run_patched(m, lambda: scheduler.run_once(self.eng, keywords=["kw"], watch=True))
            plain = _run_patched(_Mocks(), lambda: scheduler.run_once(self.eng, keywords=["kw"]))
        self.assertIn("watch", out)
        self.assertTrue(out["watch"]["seeds"])
        self.assertNotIn("watch", plain)


class TestCertPlWatch(unittest.TestCase):
    def test_matches_campaign_stems_with_own_watermark(self):
        feed = [
            {"RegisterPositionId": 10, "DomainAddress": "healthlinkq-pl.click"},
            {"RegisterPositionId": 11, "DomainAddress": "orzel-fundaris.online"},
            {"RegisterPositionId": 12, "DomainAddress": "unrelated-shop.pl"},
            {"RegisterPositionId": 13, "DomainAddress": "healthlinkq.top", "DeleteDate": "2026-11-01"},
        ]
        with tempfile.TemporaryDirectory() as td:
            st = Store(Path(td) / "cert.sqlite")
            try:
                st.put("cert_pl_last_id", 999)          # keyword scan watermark must not affect / be changed by the watch
                with mock.patch.object(sources, "_fetch_cert_pl_json", return_value=feed):
                    res = sources.cert_pl_watch(st, ["healthlinkq", "orzelfundaris"])
                    self.assertEqual({r["domain"] for r in res}, {"healthlinkq-pl.click", "orzel-fundaris.online"})
                    self.assertEqual(st.get("cert_pl_watch_last_id"), 13)
                    self.assertEqual(st.get("cert_pl_last_id"), 999)
                    self.assertEqual(sources.cert_pl_watch(st, ["healthlinkq"]), [])   # nothing new since watermark
            finally:
                st.db.close()


class TestWatchApi(unittest.TestCase):
    def setUp(self):
        from ftf import api

        self.api = api
        self.td = tempfile.TemporaryDirectory()
        self.eng = _engine(self.td.name)
        self._old = api._ENGINE
        api._ENGINE = self.eng

    def tearDown(self):
        self.api._ENGINE = self._old
        self.eng.store.db.close()
        self.td.cleanup()

    def test_seeds_endpoint_and_watch_job(self):
        from fastapi import HTTPException

        ci = _campaign_of(self.eng, "m1")
        seeds = self.api.scanner_seeds(campaign=ci)["seeds"]
        self.assertTrue(seeds and all(s["campaign"] == ci for s in seeds))
        self.assertTrue(all(s["group_label"] and s["sources_label"] is not None for s in seeds))
        with self.assertRaises(HTTPException):
            self.api.scanner_seeds(campaign=99)

        m = _Mocks()
        ps = m.patches()
        for p in ps:
            p.start()
        try:
            job = self.api.scanner_watch(self.api.WatchReq(campaign=ci, analyse=False))
            for _ in range(200):
                if job["status"] in ("done", "error"):
                    break
                time.sleep(0.02)
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(job["status"], "done", job.get("error"))
        res = job["result"]
        self.assertTrue(res["hits"])
        self.assertTrue(all(h["seed"]["campaign"] == ci and h["seed"]["source_label"] for h in res["hits"]))
        st = self.api.scanner_status()
        self.assertTrue(st["watch_found"])
        self.assertTrue(st["watch_last"]["seeds"])
        self.assertTrue(any(e["kind"] == "watch_run" for e in st["events"]))


if __name__ == "__main__":
    unittest.main()
