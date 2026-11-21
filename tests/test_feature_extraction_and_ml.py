"""Offline unit tests for gazetteer, LLM normalization/rules, vision, faces, text,
and the linking method (identifier must-links, df filter, Gower distance, average-linkage cuts, open-set assign)."""
from __future__ import annotations

import math
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from ftf import cluster, faces, gazetteer, llm, pipeline, similarity, text, vision, web


def _make_material_entry(
    mid: str,
    indicators: dict[str, list[str]] | None = None,
    persons_visual: list[str] | None = None,
    persons_named: list[str] | None = None,
    llm_attrs: dict | None = None,
    text_summary: dict | None = None,
    vectors: dict | None = None,
    images: list[dict] | None = None,
    file_shas: list[str] | None = None,
) -> tuple[dict, dict]:
    feats = {
        "material_id": mid,
        "name": mid,
        "indicators": indicators or {},
        "persons_visual": persons_visual or [],
        "persons_named": persons_named or [],
        "llm": llm_attrs or {"scam_type": "other"},
        "text": text_summary or {},
        "images": images or [],
        "faces": [],
        "file_shas": file_shas or [],
        "web": {"landing_domains": list((indicators or {}).get("landing_domain", []))},
        "dates": [],
    }
    return feats, (vectors or {})


class TestGazetteer(unittest.TestCase):
    def test_mask_entities_handles_polish_declensions(self):
        samples = [
            ("Skandal o Donaldzie Tusku w programie", ("donald", "tusk")),
            ("Wypowiedź o Andrzeju Dudzie obiegła sieć", ("andrzej", "dud")),
            ("Wywiad z Moniką Olejnik został usunięty", ("monik", "olejnik")),
            ("Spółka Rafała Brzoski ogłasza projekt", ("rafal", "brzosk")),
            ("Sławomir Mentzen ujawnia strategię", ("slawomir", "mentzen")),
            ("Konferencja Adama Glapińskiego w NBP", ("adam", "glapinsk")),
        ]
        for sentence, forbidden in samples:
            with self.subTest(sentence=sentence):
                masked = gazetteer.mask_entities(sentence)
                self.assertIn("<per>", masked)
                for stem in forbidden:
                    self.assertNotIn(stem, masked)

    def test_find_persons_robert_lewandowski_precision(self):
        self.assertIn("Robert Lewandowski", gazetteer.find_persons("Robert Lewandowski poleca nową platformę"))
        self.assertNotIn("Robert Lewandowski", gazetteer.find_persons("Agnieszka Lewandowska skomentowała post"))
        self.assertNotIn("Robert Lewandowski", gazetteer.find_persons("Zofia Lewandowska poleca produkt"))
        self.assertNotIn("Robert Lewandowski", gazetteer.find_persons("Tomasz Lewandowski z Warszawy"))


class TestLLMNormalizationAndRules(unittest.TestCase):
    def test_normalise_rejects_unknown_enum_and_drops_removed_fields(self):
        raw = {
            "scam_type": "fake_news_article",
            "narrative_template": "investment_fake_platform",      # field no longer in the schema
            "distinctive_phrases": ["kup teraz"],                  # field no longer in the schema
            "impersonated_persons": ["Rafała Brzoski"],
            "impersonated_brands": ["Orlen S.A."],
        }
        norm = llm.normalise(dict(raw))
        self.assertEqual(norm["scam_type"], "other")
        self.assertNotIn("narrative_template", norm)
        self.assertNotIn("distinctive_phrases", norm)
        self.assertIn("Rafał Brzoska", norm["impersonated_persons"])
        self.assertIn("Orlen", norm["impersonated_brands"])
        self.assertLessEqual(set(llm.rules("Platforma Orzeł Fundaris pozwala zarabiać")), set(llm.SCHEMA["properties"]) | {"_backend"})

    def test_rules_rejects_cta_verbs_as_product_name(self):
        res = llm.rules("Pobierz aplikację Pobierz teraz i odbierz bonus")
        self.assertNotEqual(res["product_or_platform_name"], "Pobierz")
        self.assertIsNone(res["product_or_platform_name"])

        res_ok = llm.rules("Platforma Orzeł Fundaris pozwala zarabiać na akcjach")
        self.assertEqual(res_ok["product_or_platform_name"], "Orzeł Fundaris")


class TestVisionHelpers(unittest.TestCase):
    def test_is_ui_screenshot_distinguishes_fake_news_from_ad_library(self):
        self.assertFalse(pipeline.is_ui_screenshot("Artykuł specjalny. Komentarze (42) Zostaw komentarz poniżej"))
        self.assertTrue(pipeline.is_ui_screenshot("Szczegóły reklamy Identyfikator biblioteki: 123456789012"))

    def test_creative_crop_preserves_square_and_respects_min_area_on_portrait(self):
        rng = np.random.default_rng(7)
        sq = Image.fromarray(rng.integers(0, 255, size=(500, 500, 3), dtype=np.uint8))
        sq_crop = vision.creative_crop(sq)
        self.assertEqual(sq_crop.size, (500, 500))

        # Portrait image (400x800) with only a tiny high-variance band (20% height < 35% area)
        arr = np.full((800, 400, 3), 245, dtype=np.uint8)
        arr[200:360, 40:360, :] = rng.integers(0, 200, size=(160, 320, 3), dtype=np.uint8)
        portrait_small = Image.fromarray(arr)
        cropped_small = vision.creative_crop(portrait_small)
        self.assertGreaterEqual(cropped_small.size[0] * cropped_small.size[1], 0.35 * 400 * 800)
        self.assertEqual(cropped_small.size, (400, 800))

        # Portrait image (400x800) with a large 50% creative band -> cropped, still >= 35% area
        arr2 = np.full((800, 400, 3), 245, dtype=np.uint8)
        arr2[180:580, 10:390, :] = rng.integers(0, 200, size=(400, 380, 3), dtype=np.uint8)
        portrait_big = Image.fromarray(arr2)
        cropped_big = vision.creative_crop(portrait_big)
        self.assertGreaterEqual(cropped_big.size[0] * cropped_big.size[1], 0.35 * 400 * 800)

    def test_hashes_returns_phash_only(self):
        im = Image.new("RGB", (64, 64), (120, 80, 200))
        h = vision.hashes(im)
        self.assertEqual(set(h.keys()), {"phash"})
        self.assertEqual(len(h["phash"]), 16)


class TestFaces(unittest.TestCase):
    def test_umeyama_2d_recovers_exact_similarity_transform(self):
        theta = math.radians(23.5)
        scale = 1.75
        tx, ty = 42.3, -18.7
        R = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]], dtype=np.float64)
        src = faces.ARC_TEMPLATE.astype(np.float64)
        dst = (scale * (src @ R.T)) + np.array([tx, ty])

        M = faces._umeyama_2d(src, dst)
        self.assertIsNotNone(M)
        src_h = np.hstack([src, np.ones((src.shape[0], 1))])
        pred = src_h @ M.T
        max_err = float(np.max(np.abs(pred - dst)))
        self.assertLess(max_err, 1e-3)

    def test_identify_uses_top1_cosine_threshold_only(self):
        v1 = np.zeros(512, dtype=np.float32)
        v1[0] = 1.0
        g_far = np.zeros(512, dtype=np.float32)
        g_far[3] = 1.0
        with mock.patch("ftf.faces.gallery", return_value=(["Osoba A", "Osoba B"], np.stack([v1, g_far]), {})):
            self.assertEqual(faces.identify(v1), ("Osoba A", 1.0))
        q = np.zeros(512, dtype=np.float32)
        q[0], q[5] = 0.3, math.sqrt(1 - 0.09)                  # cosine 0.30 < FACE_MATCH_THRESHOLD
        with mock.patch("ftf.faces.gallery", return_value=(["Osoba A", "Osoba B"], np.stack([v1, g_far]), {})):
            ident, sim = faces.identify(q)
            self.assertIsNone(ident)
            self.assertAlmostEqual(sim, 0.30, places=3)


class TestTextFeatures(unittest.TestCase):
    def test_masked_minhash_high_jaccard_on_swapped_celebrities(self):
        base = (
            "PILNE! Brutalny skandal w programie na żywo z udziałem {name}. "
            "Zaledwie 37 minut po emisji wywiadu nagranie usunięto z internetu, "
            "ponieważ gość ujawnił sekretny sposób na automatyczny dochód pasywny dla każdego obywatela Polski. "
            "Banki próbowały zablokować stronę projektu, ale redakcja zachowała link do rejestracji "
            "na oficjalnej platformie inwestycyjnej z minimalną wpłatą 250 złotych."
        )
        t1 = base.format(name="Rafała Brzoski")
        t2 = base.format(name="Donalda Tuska")
        s1 = text.minhash_sig(t1, masked=True)
        s2 = text.minhash_sig(t2, masked=True)
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        jac = text.jaccard_sig(s1, s2)
        self.assertGreaterEqual(jac, 0.70)


def _sig(shared: int, seed: int) -> list[int]:
    """MinHash-like signature: the first `shared` of 128 slots equal across seeds -> Jaccard = shared / 128."""
    return [i for i in range(shared)] + [seed * 1000 + i for i in range(128 - shared)]


def _unrelated(i: int) -> tuple[dict, dict]:
    return _make_material_entry(f"u{i}", indicators={"landing_domain": [f"unrelated-{i}.shop"]})


class TestSimilarityAndClustering(unittest.TestCase):
    def test_gower_distance_is_mean_of_available_views(self):
        items = {
            "a": _make_material_entry("a", text_summary={"minhash_masked": _sig(128, 1)},
                                      images=[{"phash": "ffffffff00000000", "kind": "screenshot"}]),
            "b": _make_material_entry("b", text_summary={"minhash_masked": _sig(128, 2)},
                                      images=[{"phash": "00000000ffffffff", "kind": "screenshot"}]),
        }
        lnk = similarity.pair("a", *items["a"], "b", *items["b"], similarity.Corpus(items))
        self.assertEqual(set(lnk.views), {"text", "images"})
        self.assertAlmostEqual(lnk.views["text"], 1.0)
        self.assertAlmostEqual(lnk.views["images"], 0.0)
        self.assertAlmostEqual(lnk.distance, 0.5)
        self.assertAlmostEqual(lnk.p, 0.5)
        self.assertTrue(lnk.comparable)

    def test_gower_skips_views_missing_on_either_side(self):
        dom = np.array([list(range(128))])
        items = {
            "a": _make_material_entry("a", text_summary={"minhash_masked": _sig(96, 1)}, vectors={"dom": dom}),
            "b": _make_material_entry("b", text_summary={"minhash_masked": _sig(96, 2)}),           # no HTML
            "c": _make_material_entry("c", images=[{"phash": "ffffffff00000000", "kind": "screenshot"}]),
        }
        corpus = similarity.Corpus(items)
        ab = similarity.pair("a", *items["a"], "b", *items["b"], corpus)
        self.assertEqual(set(ab.views), {"text"})
        self.assertAlmostEqual(ab.distance, 0.25)                   # 1 - 96/128, html not counted as 0
        ac = similarity.pair("a", *items["a"], "c", *items["c"], corpus)
        self.assertEqual(ac.views, {})
        self.assertEqual(ac.distance, 1.0)
        self.assertFalse(ac.comparable)
        self.assertEqual(ac.relation, "none")

    def test_ui_screenshots_excluded_from_images_view(self):
        ui = [{"phash": "ffffffff00000000", "kind": "ui_screenshot"}]
        items = {"a": _make_material_entry("a", images=ui), "b": _make_material_entry("b", images=ui)}
        lnk = similarity.pair("a", *items["a"], "b", *items["b"], similarity.Corpus(items))
        self.assertNotIn("images", lnk.views)

    def test_df_filter_ignores_too_common_values(self):
        items = {f"m{i}": _make_material_entry(f"m{i}", indicators={
            "fb_pixel": ["111111111111111"] if i < 4 else [f"20000000000000{i}"],     # 4 / 6 > MAX_DF
            "gtm": ["GTM-ABCD"] if i < 3 else [f"GTM-X{i}"],                         # 3 / 6 <= MAX_DF
            "landing_domain": [f"op-{i}.click"]}) for i in range(6)}
        corpus = similarity.Corpus(items)
        lnk = similarity.pair("m0", *items["m0"], "m1", *items["m1"], corpus)
        by_type = {s.type: s for s in lnk.shared_ids}
        self.assertTrue(by_type["fb_pixel"].ignored)
        self.assertEqual(by_type["fb_pixel"].df, 4)
        self.assertFalse(by_type["gtm"].ignored)
        self.assertTrue(lnk.must_link)
        lnk03 = similarity.pair("m0", *items["m0"], "m3", *items["m3"], corpus)
        self.assertFalse(lnk03.must_link)                          # only the ignored pixel is shared
        self.assertEqual(lnk03.relation, "none")
        self.assertTrue(lnk03.shared_ids[0].ignored)
        # a value held by just the compared pair always counts (even when N = 2)
        two = {k: items[k] for k in ("m0", "m1")}
        self.assertTrue(similarity.pair("m0", *two["m0"], "m1", *two["m1"], similarity.Corpus(two)).must_link)

    def test_domains_compared_as_registrable_and_ocr_decoys_dropped(self):
        items = {
            "a": _make_material_entry("a", indicators={"page_host": ["promo.op-one.click"], "ocr_domain": ["interia.pl"]}),
            "b": _make_material_entry("b", indicators={"landing_domain": ["op-one.click"]}),
            "c": _make_material_entry("c", indicators={"landing_domain": ["interia.pl"]}),
            **{f"u{i}": _unrelated(i) for i in range(3)},
        }
        corpus = similarity.Corpus(items)
        ab = similarity.pair("a", *items["a"], "b", *items["b"], corpus)
        self.assertEqual([(s.group, s.value) for s in ab.shared_ids], [("domains", "op-one.click")])
        self.assertEqual(ab.p, 1.0)
        self.assertEqual(ab.relation, "same_campaign")
        ac = similarity.pair("a", *items["a"], "c", *items["c"], corpus)
        self.assertEqual(ac.shared_ids, [])

    def test_must_link_is_transitive(self):
        items = {
            "a": _make_material_entry("a", indicators={"fb_pixel": ["1071875908635809"], "landing_domain": ["a-op.click"]}),
            "b": _make_material_entry("b", indicators={"fb_pixel": ["1071875908635809"], "landing_domain": ["b-op.click"],
                                                       "telegram": ["opchannel"]}),
            "c": _make_material_entry("c", indicators={"telegram": ["opchannel"], "landing_domain": ["c-op.click"]}),
            **{f"u{i}": _unrelated(i) for i in range(4)},
        }
        links = similarity.all_links(items)
        ac = next(l for l in links if {l.a, l.b} == {"a", "c"})
        self.assertFalse(ac.must_link)
        cl = cluster.build(items, links)
        self.assertEqual(cl["campaign_of"]["a"], cl["campaign_of"]["c"])
        self.assertEqual(set(cl["campaigns"][0]), {"a", "b", "c"})
        self.assertEqual(len(cl["campaigns"]), 5)

    def test_campaign_and_family_cuts(self):
        # x~y: d = 0.25 (same campaign by content); x~z, y~z: d = 0.75 (same family only); w unrelated
        items = {
            "x": _make_material_entry("x", text_summary={"minhash_masked": _sig(128, 1)}),
            "y": _make_material_entry("y", text_summary={"minhash_masked": _sig(96, 2)}),
            "z": _make_material_entry("z", text_summary={"minhash_masked": _sig(32, 3)}),
            "w": _make_material_entry("w", text_summary={"minhash_masked": _sig(0, 4)}),
        }
        cl = cluster.build(items)
        self.assertEqual(cl["campaign_of"]["x"], cl["campaign_of"]["y"])
        self.assertNotEqual(cl["campaign_of"]["x"], cl["campaign_of"]["z"])
        self.assertEqual(cl["family_of"]["x"], cl["family_of"]["z"])
        self.assertNotEqual(cl["family_of"]["x"], cl["family_of"]["w"])
        rel = {frozenset((l.a, l.b)): l.relation for l in cl["links"]}
        self.assertEqual(rel[frozenset("xy")], "same_campaign")
        self.assertEqual(rel[frozenset("xz")], "similar")
        self.assertEqual(rel[frozenset("xw")], "none")

    def test_shared_persons_and_scam_type_never_link(self):
        items = {}
        for i in range(6):
            ind: dict[str, set[str]] = {"landing_domain": {f"distinct-op-{i}.click"}}
            img_feats = [{"ocr_text": "Zamów na amazon.com lub fb.me/promocja", "ocr_lines": [], "qr": []}]
            pipeline._extract_ocr_ad_facts(img_feats, ind, [])
            self.assertNotIn("ocr_domain", ind)
            items[f"adv_{i}"] = _make_material_entry(
                f"adv_{i}", indicators={k: sorted(v) for k, v in ind.items()},
                persons_visual=["Rafał Brzoska"], persons_named=["Rafał Brzoska"],
                llm_attrs={"scam_type": "investment_fake_platform", "spoofed_media_outlet": "Gazeta.pl"})
        links = similarity.all_links(items)
        self.assertEqual([l for l in links if l.relation != "none"], [])
        self.assertEqual(len(cluster.build(items, links)["campaigns"]), 6)

    def _base(self):
        items = {
            "k1": _make_material_entry("k1", indicators={"fb_pixel": ["1071875908635809"], "landing_domain": ["op-one.click"]},
                                       text_summary={"minhash_masked": _sig(128, 1)}, file_shas=["sha-k1"]),
            "k2": _make_material_entry("k2", indicators={"fb_pixel": ["1071875908635809"], "landing_domain": ["op-two.click"]},
                                       text_summary={"minhash_masked": _sig(100, 2)}),
            "j1": _make_material_entry("j1", indicators={"gtm": ["GTM-JJJJ"], "landing_domain": ["jj-one.top"]},
                                       text_summary={"minhash_masked": _sig(0, 3)}),
            "j2": _make_material_entry("j2", indicators={"gtm": ["GTM-JJJJ"], "landing_domain": ["jj-two.top"]}),
            **{f"s{i}": _make_material_entry(f"s{i}", indicators={"landing_domain": [f"other-{i}.shop"]}) for i in range(4)},
        }
        return items, cluster.build(items)

    def test_assign_known_campaign_by_identifier(self):
        items, cl = self._base()
        url_ind = web.url_indicators("https://brand-new-lander.top/offer?pxl=1071875908635809")
        f, v = _make_material_entry("new", indicators={k: sorted(x) for k, x in url_ind.items()})
        res = cluster.assign("new", f, v, items, cl)
        self.assertEqual(res["decision"], "known_campaign")
        self.assertEqual(res["campaign"], cl["campaign_of"]["k1"])

    def test_assign_merge_proposal_when_ids_hit_two_campaigns(self):
        items, cl = self._base()
        self.assertNotEqual(cl["campaign_of"]["k1"], cl["campaign_of"]["j1"])
        f, v = _make_material_entry("new", indicators={"fb_pixel": ["1071875908635809"], "gtm": ["GTM-JJJJ"]})
        res = cluster.assign("new", f, v, items, cl)
        self.assertEqual(res["decision"], "merge_proposal")
        self.assertIn(res["campaign"], (cl["campaign_of"]["k1"], cl["campaign_of"]["j1"]))

    def test_assign_duplicate_by_identical_file(self):
        items, cl = self._base()
        f, v = _make_material_entry("new", file_shas=["sha-k1"])
        res = cluster.assign("new", f, v, items, cl)
        self.assertEqual(res["decision"], "duplicate")
        self.assertEqual(res["duplicates"], ["k1"])
        self.assertEqual(res["campaign"], cl["campaign_of"]["k1"])

    def test_assign_by_content_known_then_new_with_similar_family(self):
        items, cl = self._base()
        # mean d to {k1, k2}: text view only -> (1 - 120/128 + 1 - 100/128) / 2 ~ 0.14 <= CAMPAIGN_CUT
        f, v = _make_material_entry("near", text_summary={"minhash_masked": _sig(120, 9)})
        res = cluster.assign("near", f, v, items, cl)
        self.assertEqual(res["decision"], "known_campaign")
        self.assertEqual(res["campaign"], cl["campaign_of"]["k1"])
        # mean d ~ 0.80 to {k1, k2} (only text comparable): new campaign, but same family
        f, v = _make_material_entry("far", text_summary={"minhash_masked": _sig(26, 9)})
        res = cluster.assign("far", f, v, items, cl)
        self.assertEqual(res["decision"], "new_campaign")
        self.assertIsNone(res["campaign"])
        self.assertEqual(res["nearest"]["campaign"], cl["campaign_of"]["k1"])
        self.assertEqual(res["similar_family"], cl["campaign_of"]["k1"])
        # nothing in common at all
        f, v = _make_material_entry("novel", indicators={"landing_domain": ["totally-fresh.xyz"]})
        res = cluster.assign("novel", f, v, items, cl)
        self.assertEqual(res["decision"], "new_campaign")
        self.assertIsNone(res["similar_family"])

    def test_assign_uses_nearest_neighbour_not_campaign_mean(self):
        # k1..k3 are one campaign only through a shared pixel; their texts differ. A near copy of k3 must join it
        # although its mean distance to the campaign is large (1-NN, Cover & Hart 1967).
        px = {"fb_pixel": ["1071875908635809"]}
        items = {
            "k1": _make_material_entry("k1", indicators=px, text_summary={"minhash_masked": _sig(0, 1)}),
            "k2": _make_material_entry("k2", indicators=px, text_summary={"minhash_masked": _sig(0, 2)}),
            "k3": _make_material_entry("k3", indicators=px, text_summary={"minhash_masked": _sig(128, 3)}),
            **{f"s{i}": _make_material_entry(f"s{i}", indicators={"landing_domain": [f"other-{i}.shop"]}) for i in range(4)},
        }
        cl = cluster.build(items)
        f, v = _make_material_entry("copy", text_summary={"minhash_masked": _sig(115, 9)})
        res = cluster.assign("copy", f, v, items, cl)
        self.assertEqual(res["decision"], "known_campaign")
        self.assertEqual(res["campaign"], cl["campaign_of"]["k3"])
        self.assertEqual(res["nearest"]["material"], "k3")
        self.assertAlmostEqual(res["nearest"]["distance"], round(1 - 115 / 128, 3))

    def test_ocr_view_compares_creative_text_and_falls_back_to_stored_ocr_text(self):
        ad = ("PILNE skandal w studiu telewizyjnym gość ujawnił sekretny sposób na dochód pasywny "
              "rejestracja na oficjalnej platformie z minimalną wpłatą dwieście pięćdziesiąt złotych dziś")
        page = _sig(128, 1)
        items = {
            "full": _make_material_entry("full", text_summary={"minhash_masked": page, "ocr_text": ad}),   # legacy record
            "creative": _make_material_entry("creative", text_summary={"minhash_ocr_masked": text.minhash_sig(ad, masked=True)}),
        }
        lnk = similarity.pair("full", *items["full"], "creative", *items["creative"], similarity.Corpus(items))
        self.assertEqual(set(lnk.views), {"ocr"})
        self.assertAlmostEqual(lnk.views["ocr"], 1.0)
        self.assertAlmostEqual(lnk.distance, 0.0)

    def test_link_explain_is_polish_and_lists_reasons(self):
        items, cl = self._base()
        l = next(l for l in cl["links"] if {l.a, l.b} == {"k1", "k2"})
        txt = l.explain()
        self.assertIn("Facebook Pixel", txt)
        self.assertIn("tekst strony", txt)
        self.assertIn("odległość treści", txt)


if __name__ == "__main__":
    unittest.main()
