"""Offline unit tests for gazetteer, LLM normalization/rules, vision, faces, text,
and similarity/clustering ML invariants."""
from __future__ import annotations

import math
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from ftf import cluster, config, faces, gazetteer, llm, pipeline, similarity, text, vision, web


def _make_material_entry(
    mid: str,
    indicators: dict[str, list[str]] | None = None,
    persons_visual: list[str] | None = None,
    persons_named: list[str] | None = None,
    llm_attrs: dict | None = None,
    text_summary: dict | None = None,
    vectors: dict | None = None,
) -> tuple[dict, dict]:
    feats = {
        "material_id": mid,
        "name": mid,
        "indicators": indicators or {},
        "persons_visual": persons_visual or [],
        "persons_named": persons_named or [],
        "llm": llm_attrs or {"scam_type": "other", "narrative_template": "other", "creative_format": "other"},
        "text": text_summary or {},
        "images": [],
        "faces": [],
        "file_shas": [],
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
    def test_normalise_rejects_cross_enum_leakage(self):
        raw = {
            "scam_type": "fake_news_article",
            "creative_format": "crypto_investment",
            "narrative_template": "investment_fake_platform",
            "impersonated_persons": ["Rafała Brzoski"],
            "impersonated_brands": ["Orlen S.A."],
        }
        norm = llm.normalise(dict(raw))
        self.assertEqual(norm["scam_type"], "other")
        self.assertEqual(norm["creative_format"], "other")
        self.assertEqual(norm["narrative_template"], "other")
        self.assertIn("Rafał Brzoska", norm["impersonated_persons"])
        self.assertIn("Orlen", norm["impersonated_brands"])

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

    def test_identify_rejects_low_quality_and_small_margin(self):
        v1 = np.zeros(512, dtype=np.float32)
        v1[0] = 1.0
        g_far = np.zeros(512, dtype=np.float32)
        g_far[3] = 1.0

        # Low quality rejected immediately
        with mock.patch("ftf.faces.gallery", return_value=(["Osoba A", "Osoba B"], np.stack([v1, g_far]), {})):
            ident_q, sim_q = faces.identify(v1, quality=0.10)
            self.assertIsNone(ident_q)
            self.assertEqual(sim_q, 0.0)

        # Ambiguous small margin rejected (best=0.70 vs second=0.68 -> diff 0.02 < FACE_MARGIN_MIN)
        q_amb = np.zeros(512, dtype=np.float32)
        q_amb[0] = 1.0
        g1 = np.zeros(512, dtype=np.float32)
        g1[0] = 0.70
        g1[1] = math.sqrt(1 - 0.70 ** 2)
        g2 = np.zeros(512, dtype=np.float32)
        g2[0] = 0.68
        g2[2] = math.sqrt(1 - 0.68 ** 2)
        with mock.patch("ftf.faces.gallery", return_value=(["Osoba A", "Osoba B"], np.stack([g1, g2]), {})):
            ident_amb, best_sim = faces.identify(q_amb, quality=0.80)
            self.assertIsNone(ident_amb)
            self.assertAlmostEqual(best_sim, 0.70, places=3)

        # Clear match with sufficient quality & margin succeeds
        with mock.patch("ftf.faces.gallery", return_value=(["Osoba A", "Osoba B"], np.stack([v1, g_far]), {})):
            ident_ok, sim_ok = faces.identify(v1, quality=0.80)
            self.assertEqual(ident_ok, "Osoba A")
            self.assertAlmostEqual(sim_ok, 1.0, places=3)


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

    def test_title_template_normalizes_persons_and_amounts(self):
        tt1 = text.title_template("Zamach na Rafała Brzoskę — stracił 5000 zł")
        tt2 = text.title_template("Zamach na Monikę Olejnik — stracił 9000 zł")
        self.assertEqual(tt1, tt2)
        self.assertIn("<per>", tt1)
        self.assertIn("<n>", tt1)


class TestSimilarityAndClusteringInvariants(unittest.TestCase):
    def test_small_n_hub_drop_regression(self):
        items = {
            f"m{i}": _make_material_entry(
                f"m{i}",
                indicators={
                    "fb_pixel": ["999999999999"],
                    "api_template": ["POST /api/v1/lead/{id}"],
                    "landing_domain": [f"dom{i}.click"],
                },
            )
            for i in range(4)
        }
        corpus = similarity.Corpus(items)
        self.assertFalse(corpus.is_hub(("fb_pixel", "999999999999")))
        self.assertGreater(corpus.rarity(("fb_pixel", "999999999999")), 0.0)
        self.assertFalse(corpus.is_hub(("api_template", "POST /api/v1/lead/{id}")))
        self.assertGreater(corpus.rarity(("api_template", "POST /api/v1/lead/{id}")), 0.0)

        cl = cluster.build(items)
        self.assertEqual(len(cl["campaigns"]), 1)
        self.assertEqual(len(cl["campaigns"][0]), 4)

    def test_60_percent_dominant_campaign_not_dropped_as_hub(self):
        items = {}
        for i in range(6):
            items[f"camp_{i}"] = _make_material_entry(
                f"camp_{i}",
                indicators={
                    "fb_pixel": ["2012165449475163"],
                    "api_template": ["POST /api/v1/trigger/field/{id}/"],
                    "param_signature": ["acc=A12&pxl=D16"],
                    "landing_domain": [f"camp{i}.pro"],
                },
            )
        for j in range(4):
            items[f"single_{j}"] = _make_material_entry(
                f"single_{j}",
                indicators={
                    "landing_domain": [f"unrelated{j}.shop"],
                    "fb_pixel": [f"700000000000000{j}"],
                },
            )
        corpus = similarity.Corpus(items)
        self.assertFalse(corpus.is_hub(("fb_pixel", "2012165449475163")))
        self.assertFalse(corpus.is_hub(("api_template", "POST /api/v1/trigger/field/{id}/")))
        self.assertFalse(corpus.is_hub(("param_signature", "acc=A12&pxl=D16")))

        cl = cluster.build(items)
        camp_sets = [set(c) for c in cl["campaigns"]]
        expected_dominant = {f"camp_{i}" for i in range(6)}
        self.assertIn(expected_dominant, camp_sets)
        self.assertEqual(len(cl["campaigns"]), 5)

    def test_weak_only_guard_caps_probability(self):
        items = {
            "a": _make_material_entry(
                "a",
                persons_visual=["Rafał Brzoska"],
                llm_attrs={"scam_type": "crypto_investment", "narrative_template": "fake_news_article", "creative_format": "other"},
            ),
            "b": _make_material_entry(
                "b",
                persons_visual=["Rafał Brzoska"],
                llm_attrs={"scam_type": "crypto_investment", "narrative_template": "fake_news_article", "creative_format": "other"},
            ),
        }
        corpus = similarity.Corpus(items)
        lnk = similarity.pair("a", *items["a"], "b", *items["b"], corpus)
        self.assertLessEqual(lnk.p, config.WEAK_ONLY_CAP)
        self.assertNotEqual(lnk.relation, "same_campaign")

    def test_contradiction_guard_penalizes_opposing_scam_types(self):
        base_ind = {"script_name": ["custom_lander.js"], "css_name": ["custom_lander_kit.css"]}
        neutral_items = {
            "a": _make_material_entry("a", indicators=base_ind, llm_attrs={"scam_type": "other"}),
            "b": _make_material_entry("b", indicators=base_ind, llm_attrs={"scam_type": "other"}),
        }
        conflict_items = {
            "a": _make_material_entry("a", indicators=base_ind, llm_attrs={"scam_type": "crypto_investment"}),
            "b": _make_material_entry("b", indicators=base_ind, llm_attrs={"scam_type": "health_miracle_product"}),
        }
        lnk_neutral = similarity.pair("a", *neutral_items["a"], "b", *neutral_items["b"], similarity.Corpus(neutral_items))
        lnk_conflict = similarity.pair("a", *conflict_items["a"], "b", *conflict_items["b"], similarity.Corpus(conflict_items))
        self.assertGreater(lnk_neutral.p, 0.0)
        self.assertAlmostEqual(lnk_conflict.p, lnk_neutral.p * config.CONFLICT_FACTOR, places=6)
        self.assertTrue(any(e.signal == "conflict" for e in lnk_conflict.evidence))

    def test_adversarial_negative_suite_zero_false_same_campaign_links(self):
        items = {}
        for i in range(6):
            ind: dict[str, set[str]] = {"landing_domain": {f"distinct-op-{i}.click"}}
            img_feats = [{"ocr_text": "Zamów na amazon.com lub fb.me/promocja", "ocr_lines": [], "qr": []}]
            pipeline._extract_ocr_ad_facts(img_feats, ind, [])
            self.assertNotIn("ocr_domain", ind)
            items[f"adv_{i}"] = _make_material_entry(
                f"adv_{i}",
                indicators={k: sorted(v) for k, v in ind.items()},
                persons_visual=["Rafał Brzoska"],
                persons_named=["Rafał Brzoska"],
                llm_attrs={
                    "scam_type": "investment_fake_platform",
                    "narrative_template": "celebrity_scandal_or_attack",
                    "creative_format": "fake_news_article",
                },
            )
        links = similarity.all_links(items)
        false_positives = [l for l in links if l.relation in ("same_campaign", "duplicate")]
        self.assertEqual(false_positives, [])
        cl = cluster.build(items, links)
        self.assertEqual(len(cl["campaigns"]), 6)

    def test_synthetic_positive_campaign_and_open_set_assign(self):
        html_ind_1 = web.extract_html("<html><script>fbq('init', '1071875908635809');</script></html>")["indicators"]
        html_ind_2 = web.extract_html("<html><script>fbq('init', '1071875908635809');</script></html>")["indicators"]
        items = {
            "k1": _make_material_entry("k1", indicators={"fb_pixel": sorted(html_ind_1["fb_pixel"]), "landing_domain": ["op-one.click"]}),
            "k2": _make_material_entry("k2", indicators={"fb_pixel": sorted(html_ind_2["fb_pixel"]), "landing_domain": ["op-two.click"]}),
            **{
                f"s{i}": _make_material_entry(
                    f"s{i}",
                    indicators={"fb_pixel": [f"300000000000000{i}"], "landing_domain": [f"other-{i}.shop"]},
                )
                for i in range(6)
            },
        }
        cl = cluster.build(items)
        known_camp = cl["campaign_of"]["k1"]
        self.assertEqual(known_camp, cl["campaign_of"]["k2"])

        # New variant sharing bare fb_pixel via URL ?pxl= parameter
        url_ind = web.url_indicators("https://brand-new-lander.top/offer?pxl=1071875908635809")
        var_f, var_v = _make_material_entry(
            "variant_new",
            indicators={k: sorted(v) for k, v in url_ind.items()},
        )
        res_known = cluster.assign("variant_new", var_f, var_v, items, cl)
        self.assertEqual(res_known["decision"], "known_campaign")
        self.assertEqual(res_known["campaign"], known_camp)

        # Completely novel material -> new_campaign
        novel_f, novel_v = _make_material_entry(
            "novel_1",
            indicators={"fb_pixel": ["8888888888888888"], "landing_domain": ["totally-fresh.xyz"]},
            llm_attrs={"scam_type": "health_miracle_product", "narrative_template": "miracle_cure_testimonial", "creative_format": "product_packshot"},
        )
        res_novel = cluster.assign("novel_1", novel_f, novel_v, items, cl)
        self.assertEqual(res_novel["decision"], "new_campaign")
        self.assertIsNone(res_novel["campaign"])


if __name__ == "__main__":
    unittest.main()
