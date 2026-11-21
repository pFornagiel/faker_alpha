"""Read-only regression tests against the 10 organiser cases and stored SQLite features."""
from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from sklearn.metrics import adjusted_rand_score

from ftf import cluster, config, ingest, pipeline, store, web

ORGANIZER_DIR = config.DATA / "organizer" / "dane"
SQLITE_PATH = config.DATA / "store" / "ftf.sqlite"
LABELS_CSV = config.DATA / "labels_dane.csv"

_FORBIDDEN_ASSET_SUFFIXES = (".js", ".mjs", ".css", ".pobrane", ".pobierz")


def _load_readonly_store(path: Path) -> dict[str, tuple[dict, dict]]:
    """Load materials and vectors strictly read-only so `ftf.sqlite` is never modified."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out: dict[str, tuple[dict, dict]] = {}
        for mid, name, source, label, created, mat, feats in conn.execute(
            "SELECT id,name,source,label,created_at,material,features FROM materials ORDER BY created_at, name"
        ):
            f = json.loads(feats)
            f["_material"] = json.loads(mat)
            f["_label"] = label
            out[mid] = (f, {})
        for mid, kind, blob in conn.execute("SELECT material_id, kind, data FROM vectors"):
            if mid in out:
                out[mid][1][kind] = store._blob_to_np(blob)
        return out
    finally:
        conn.close()


def _leave_one_out(items: dict[str, tuple[dict, dict]]) -> list[dict]:
    full = cluster.build(items)
    ok_decisions = {"known_campaign", "duplicate", "merge_proposal"}
    rows = []
    for mid in items:
        rest = {k: v for k, v in items.items() if k != mid}
        cl = cluster.build(rest)
        f, v = items[mid]
        res = cluster.assign(mid, f, v, rest, cl)
        mates = [m for m in full["campaigns"][full["campaign_of"][mid]] if m != mid]
        if mates:
            target = Counter(cl["campaign_of"][m] for m in mates).most_common(1)[0][0]
            ok = res["decision"] in ok_decisions and res["campaign"] == target
        else:
            ok = res["decision"] == "new_campaign"
        rows.append({"material": f["name"], "decision": res["decision"], "ok": ok})
    return rows


class TestRealDataRegression(unittest.TestCase):
    @unittest.skipUnless(ORGANIZER_DIR.exists(), "organiser dataset not present")
    def test_01_ingest_all_10_organizer_cases(self):
        materials = ingest.load_dataset(ORGANIZER_DIR)
        self.assertEqual(len(materials), 10)
        by_name = {m.name: m for m in materials}

        # Case 61 dotfile .har detected as har page
        m61 = by_name["61"]
        har_names = [Path(pg["path"]).name for pg in m61.pages if pg["kind"] == "har"]
        self.assertIn(".har", har_names)

        # Zero non-image .js / .pobrane / .pobierz / .css files in m.assets across all 10 cases
        for m in materials:
            for asset in m.assets:
                low = Path(asset).name.lower()
                self.assertFalse(
                    low.endswith(_FORBIDDEN_ASSET_SUFFIXES),
                    f"Case {m.name} leaked non-image asset into m.assets: {asset}",
                )

        # Case 14 preserves ineptsolidoval.top URL from sibling MHTML
        m14 = by_name["14"]
        all_urls_14 = list(m14.urls) + [pg.get("url") or "" for pg in m14.pages]
        self.assertTrue(
            any("ineptsolidoval.top" in u for u in all_urls_14),
            f"Case 14 missing ineptsolidoval.top URL: {all_urls_14}",
        )

    @unittest.skipUnless(ORGANIZER_DIR.exists(), "organiser dataset not present")
    def test_02_web_parse_har_and_html_across_all_10_cases(self):
        materials = ingest.load_dataset(ORGANIZER_DIR)
        case48_landing_ok = False

        for m in materials:
            for pg in m.pages:
                p = Path(pg["path"])
                if pg["kind"] == "har":
                    parsed = web.parse_har(p, keep_images=False)
                    ind = parsed["indicators"]
                    if m.name == "48" and p.name == "novumfy.com.har":
                        self.assertTrue(parsed["redirect_chain"])
                        landing = parsed["redirect_chain"][0]
                        self.assertIn("novumfy.com", landing)
                        self.assertNotIn("/api/v1/trigger/", landing)
                        # Verify selected landing corresponds to a GET 200 entry
                        get200 = [
                            r for r in parsed["requests"]
                            if r["method"] == "GET" and r["status"] == 200 and r["url"] == landing
                        ]
                        self.assertTrue(get200, f"Case 48 landing URL was not GET 200: {landing}")
                        case48_landing_ok = True
                elif pg["kind"] == "html":
                    parsed = web.extract_html(p.read_text(encoding="utf-8", errors="replace"), pg.get("url", ""))
                    ind = parsed["indicators"]
                else:
                    continue

                for ep in ind.get("form_endpoint", set()):
                    self.assertNotIn("translate.googleapis.com", ep, f"Case {m.name} leaked translate.googleapis.com")
                self.assertNotIn("google.pl", ind.get("redirect_domain", set()), f"Case {m.name} leaked google.pl")
                for px in ind.get("fb_pixel", set()):
                    self.assertTrue(px.isdigit(), f"Case {m.name} non-bare fb_pixel: {px!r}")
                    self.assertFalse(px.startswith(("pxl=", "fbpx=")))

        self.assertTrue(case48_landing_ok, "Case 48 novumfy.com.har not checked")

    @unittest.skipUnless(
        SQLITE_PATH.exists() and LABELS_CSV.exists(),
        "stored SQLite DB or labels_dane.csv not present",
    )
    def test_03_clustering_ari_loo_and_small_subset_regression(self):
        items = _load_readonly_store(SQLITE_PATH)
        self.assertEqual(len(items), 10)

        cl = cluster.build(items)
        self.assertEqual(len(cl["campaigns"]), 6)

        name2id = {f["name"]: mid for mid, (f, _) in items.items()}
        gold: dict[str, str] = {}
        with LABELS_CSV.open(encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and not row[0].startswith("#"):
                    mid = name2id.get(row[0].strip())
                    if mid:
                        gold[mid] = row[1].strip()
        ids = sorted(gold)
        self.assertEqual(len(ids), 10)
        ari = adjusted_rand_score([gold[m] for m in ids], [cl["campaign_of"][m] for m in ids])
        self.assertEqual(ari, 1.0)

        # Leave-one-out achieves 10/10
        loo = _leave_one_out(items)
        self.assertEqual(len(loo), 10)
        self.assertEqual(sum(r["ok"] for r in loo), 10, f"LOO failures: {[r for r in loo if not r['ok']]}")

        # Subset {1, 2, 48, 61} (N=4) clusters into 1 single campaign
        subset_ids = {name2id[k] for k in ("1", "2", "48", "61")}
        subset_items = {k: v for k, v in items.items() if k in subset_ids}
        sub_cl = cluster.build(subset_items)
        self.assertEqual(len(sub_cl["campaigns"]), 1)
        self.assertEqual(set(sub_cl["campaigns"][0]), subset_ids)

    @unittest.skipUnless(ORGANIZER_DIR.exists(), "organiser dataset not present")
    def test_04_end_to_end_offline_pipeline_case_14_and_48(self):
        by_name = {m.name: m for m in ingest.load_dataset(ORGANIZER_DIR)}

        with tempfile.TemporaryDirectory() as td, mock.patch.object(config, "ARTIFACTS", Path(td)):
            f14, _ = pipeline.analyze(by_name["14"], use_llm=False, enrich_online=False)
            f48, _ = pipeline.analyze(by_name["48"], use_llm=False, enrich_online=False)

        # --- Case 14 assertions ---
        kinds_by_file = {Path(im["src"]).name: im["kind"] for im in f14["images"]}
        self.assertIn("screenshot.png", kinds_by_file)
        self.assertNotEqual(kinds_by_file["screenshot.png"], "ui_screenshot")
        self.assertIn("IMG_3629.PNG", kinds_by_file)
        self.assertNotEqual(kinds_by_file["IMG_3629.PNG"], "ui_screenshot")

        self.assertNotIn("Robert Lewandowski", f14["persons_named"])
        self.assertNotIn("Robert Lewandowski", f14["persons_visual"])

        ind14 = f14["indicators"]
        self.assertTrue(ind14.get("fb_pixel"))
        for px in ind14["fb_pixel"]:
            self.assertTrue(px.isdigit(), f"Expected bare fb_pixel, got {px!r}")
        self.assertTrue(ind14.get("ad_id"))
        for aid in ind14["ad_id"]:
            self.assertTrue(aid.isdigit(), f"Expected bare ad_id, got {aid!r}")

        ocr_doms = set(ind14.get("ocr_domain", []))
        self.assertNotIn("interia.pl", ocr_doms)
        self.assertNotIn("fb.me", ocr_doms)
        self.assertNotIn("extra", f14["llm"])

        # --- Case 48 assertions ---
        self.assertIn("novumfy.com", f48["web"]["landing_domains"])
        self.assertTrue(any("novumfy.com" in u for u in f48["web"]["landing_urls"]))

        session_uuid = "01a18244-1124-71c2-8db4-b31d668058e2"
        self.assertNotIn(session_uuid, f48["indicators"].get("tenant_uuid", []))

        asset_faces = [fc for fc in f48["faces"] if str(fc.get("src", "")).startswith("asset:")]
        self.assertTrue(asset_faces)
        face_keys = [
            (fc["src"], tuple(round(v, 3) for v in fc["box_rel"]))
            for fc in asset_faces
        ]
        self.assertEqual(len(face_keys), len(set(face_keys)), "Duplicate asset faces found after SHA deduplication")


if __name__ == "__main__":
    unittest.main()
