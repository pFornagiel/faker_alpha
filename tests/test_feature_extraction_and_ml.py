"""Offline unit tests for gazetteer, LLM normalization/rules, vision, faces, text,
and the linking method (identifier must-links, df filter, Gower distance, average-linkage cuts, open-set assign)."""
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

    @staticmethod
    def _busy_picture(seed: int, size=(480, 600)) -> Image.Image:
        """A picture with many distinct corners: random rectangles and discs on a noisy background."""
        from PIL import ImageDraw

        rng = np.random.default_rng(seed)
        im = Image.fromarray(rng.integers(100, 140, size=(size[1], size[0], 3), dtype=np.uint8))
        d = ImageDraw.Draw(im)
        for _ in range(90):
            x, y = int(rng.integers(0, size[0] - 40)), int(rng.integers(0, size[1] - 40))
            w, h = int(rng.integers(12, 70)), int(rng.integers(12, 70))
            col = tuple(int(c) for c in rng.integers(0, 255, 3))
            (d.rectangle if rng.random() < 0.6 else d.ellipse)([x, y, x + w, y + h], fill=col)
        return im

    def test_local_match_survives_crop_and_rescale_where_phash_does_not(self):
        a, other = self._busy_picture(1), self._busy_picture(2)
        w, h = a.size
        cropped = a.crop((int(w * .08), int(h * .08), int(w * .92), int(h * .92))).resize((int(w * .5), int(h * .5)))
        da, dc, do = (vision.local_descriptors(x) for x in (a, cropped, other))
        ha, hc = int(vision.hashes(a)["phash"], 16), int(vision.hashes(cropped)["phash"], 16)
        self.assertGreater(bin(ha ^ hc).count("1"), 4)                       # the pHash test fails on the cropped copy
        self.assertGreaterEqual(vision.local_match(da, dc), config.LOCAL_MIN_INLIERS)     # the keypoint test passes
        self.assertLess(vision.local_match(da, do), config.LOCAL_MIN_INLIERS)             # and rejects a different picture
        back = vision.unpack_local(vision.pack_local(da), da[2])
        self.assertTrue(np.array_equal(back[0], da[0]) and np.array_equal(back[1], da[1]) and back[2] == da[2])

    def test_images_view_counts_keypoint_match_and_says_so(self):
        a, other = self._busy_picture(3), self._busy_picture(4)
        w, h = a.size
        cropped = a.crop((int(w * .1), int(h * .05), int(w * .95), int(h * .9))).resize((int(w * .6), int(h * .6)))

        def entry(mid, im):
            loc = vision.local_descriptors(im)
            img = {"src": f"{mid}.png", "kind": "keyframe", "phash": vision.hashes(im)["phash"], "local": [0, len(loc[1]), *loc[2]]}
            return _make_material_entry(mid, images=[img], vectors={"local": vision.pack_local(loc)})

        items = {"orig": entry("orig", a), "copy": entry("copy", cropped), "other": entry("other", other)}
        corpus = similarity.Corpus(items)
        same = similarity.pair("orig", *items["orig"], "copy", *items["copy"], corpus)
        self.assertEqual(same.views, {"images": 1.0})
        self.assertEqual(same.local_images, 1)
        self.assertIn("punktach charakterystycznych", same.explain())
        diff = similarity.pair("orig", *items["orig"], "other", *items["other"], corpus)
        self.assertEqual(diff.views, {"images": 0.0})
        self.assertEqual(diff.local_images, 0)
        with mock.patch.object(similarity.config, "LOCAL_MATCH", False):       # pHash-only behaviour is still available
            off = similarity.pair("orig", *items["orig"], "copy", *items["copy"], corpus)
        self.assertEqual(off.views, {"images": 0.0})

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

    def test_keywords_rank_repeated_phrases_and_names_and_skip_stop_words(self):
        ad = ("Złoty Fundusz to państwowy program. Złoty fundusz gwarantuje zysk bez ryzyka. "
              "Zapisz się do 12.05, a Jan Kowalski z Elbląga już zarabia. Złoty fundusz czeka na Ciebie "
              "na zloty-fundusz.example i https://www.fundusz.example/rejestracja.")
        kw = text.keywords(ad)
        self.assertEqual(kw[0], "złoty fundusz")
        self.assertIn("jan kowalski", kw)
        self.assertNotIn("złoty", kw)        # every occurrence is inside the chosen phrase
        self.assertNotIn("fundusz", kw)
        for word in ("bez", "się", "12.05", "już", "na", "example", "zloty-fundusz", "https", "rejestracja"):
            self.assertNotIn(word, kw)
        self.assertEqual(text.keywords(ad, n=3), kw[:3])
        self.assertEqual(text.keywords("za krótki tekst"), [])


def _sig(shared: int, seed: int) -> list[int]:
    """MinHash-like signature: the first `shared` of 128 slots equal across seeds -> Jaccard = shared / 128."""
    return [i for i in range(shared)] + [seed * 1000 + i for i in range(128 - shared)]


def _unrelated(i: int) -> tuple[dict, dict]:
    return _make_material_entry(f"u{i}", indicators={"landing_domain": [f"unrelated-{i}.shop"]})


class TestSimilarityAndClustering(unittest.TestCase):
    def test_shared_platform_host_and_public_service_do_not_must_link(self):
        """Two unrelated pages on AWS ECS that both load a public flag CDN and report to Cloudflare RUM share nothing."""
        def entry(mid: str, ecs: str) -> tuple[dict, dict]:
            return _make_material_entry(mid, indicators={
                "page_host": [f"{ecs}.ecs.us-east-1.on.aws", "flagcdn.com"],
                "api_template": ["POST /cdn-cgi/rum"], "email": ["name@example.com"]})

        items = {"a": entry("a", "xd-f1cf3d4f"), "b": entry("b", "dv-c3e594c6"), "c": entry("c", "xd-f1cf3d4f")}
        corpus = similarity.Corpus(items)
        ab = similarity.pair("a", *items["a"], "b", *items["b"], corpus)
        ac = similarity.pair("a", *items["a"], "c", *items["c"], corpus)
        self.assertFalse(ab.must_link)
        self.assertEqual(ab.shared_ids, [])
        self.assertTrue(ac.must_link)
        self.assertEqual([s.value for s in ac.shared_ids], ["xd-f1cf3d4f.ecs.us-east-1.on.aws"])

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


class PageStructureSignalsTests(unittest.TestCase):
    """Class-vocabulary and script-skeleton views, the language rule and the certificate-batch identifier."""

    def test_extract_html_survives_canonical_inside_noscript(self):
        from ftf import web

        html = ('<html><head><title>t</title><noscript><link rel="canonical" href="https://shop.example/x">'
                '<meta property="og:url" content="https://shop.example/y"></noscript></head><body><p>hello</p></body></html>')
        e = web.extract_html(html)
        self.assertTrue(e["title"] == "t" and "hello" in e["text"])


    def test_class_vocabulary_masks_generated_parts(self):
        from ftf import web

        v = web.class_vocabulary(["lead-form__step", "css-1x2y3z9", "col-12", "sc-bdVaJa", "a", "x" * 80])
        self.assertTrue("lead-form__step" in v and "col-#" in v)
        self.assertTrue("css-1x2y3z9" not in v and "sc-bdVaJa" not in v)
        self.assertTrue("a" not in v and "x" * 80 not in v)


    def test_script_shingles_ignore_literals_and_public_snippets(self):
        from ftf import web

        kit = "function send(a){var u='%s';fetch(u+'/lead',{method:'POST',body:JSON.stringify({id:%d,name:a})}).then(function(r){return r.json()}).then(function(d){if(d.ok){window.location=u+'/thanks'}else{alert('%s')}});}" * 2
        a = web.script_shingles([kit % ("https://one.example", 11, "Error", "https://one.example", 11, "Error")])
        b = web.script_shingles([kit % ("https://two.example", 2907, "Błąd", "https://two.example", 2907, "Błąd")])
        self.assertTrue(a and a == b)
        self.assertTrue(web.script_shingles(["window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}" * 5]) == set())
        self.assertTrue(web.script_shingles(["var a=1;"]) == set())


    def test_cert_batch_only_for_own_certificate(self):
        from ftf import web

        own = {"hostname": "shop.example.com", "tls_valid_from": "2026-11-02T12:54:47.000Z", "tls_san": ["example.com", "*.example.com"]}
        self.assertTrue(web.cert_batch(own) == "2026-11-02T12:54")
        self.assertTrue(web.cert_batch({**own, "hostname": "tenant.pages.dev", "tls_san": ["*.pages.dev"]}) == "")
        self.assertTrue(web.cert_batch({**own, "tls_san": ["example.com", "other.net"]}) == "")
        self.assertTrue(web.cert_batch({k: v for k, v in own.items() if k != "tls_san"}) == "")


    def test_language_detection_and_differ(self):
        from ftf import lang

        pl = "To jest strona, na której można się zarejestrować i już dziś zacząć zarabiać, ale nie jest to oferta dla każdego. " * 3
        en = "This is the page where you can register and start earning today, but it is not an offer for everyone and that is fine. " * 3
        self.assertTrue(lang.language(pl) == "pl" and lang.language(en) == "en")
        self.assertTrue(lang.language("krótki tekst") == lang.UNKNOWN)
        self.assertTrue(lang.differ("pl", "en") and not lang.differ("pl", "pl"))
        self.assertTrue(not lang.differ("pl", lang.UNKNOWN) and not lang.differ(None, "en"))


    def test_views_skip_word_views_across_languages_and_add_structure_views(self):
        from ftf import similarity, text

        sig = text.minhash_sig("jeden dwa trzy cztery piec szesc siedem osiem dziewiec dziesiec")
        other = text.minhash_sig("one two three four five six seven eight nine ten eleven")
        css = text.set_sig({f"kit-{i}" for i in range(20)}, 13, 10)
        fa = {"text": {"minhash_masked": sig, "minhash_ocr_masked": sig, "lang": "pl", "lang_ocr": "und"}}
        fb = {"text": {"minhash_masked": other, "minhash_ocr_masked": other, "lang": "en"}}
        fc = {"text": {"minhash_masked": other, "minhash_ocr_masked": other, "lang": "pl"}}
        va, vb = {"css": [css]}, {"css": [css], "js": [css]}
        corpus = similarity.Corpus({"a": (fa, va), "b": (fb, vb), "c": (fc, {})})
        cross = similarity.views("a", fa, va, "b", fb, vb, corpus)
        self.assertTrue("text" not in cross and "ocr" not in cross)   # different languages: not comparable word by word
        self.assertTrue(cross["css"] == 1.0 and "js" not in cross)   # js only on one side
        same = similarity.views("a", fa, va, "c", fc, {}, corpus)
        self.assertTrue(same["text"] < 0.2 and same["ocr"] < 0.2)   # same language: compared, and dissimilar
        link = similarity.pair("a", fa, va, "b", fb, vb, corpus)
        self.assertTrue(link.distance == 0.0 and link.comparable)

    def test_shared_certificate_batch_is_a_must_link(self):
        from ftf import similarity

        fa = {"indicators": {"cert_batch": ["2026-11-02T12:54"], "landing_domain": ["one.example"]}}
        fb = {"indicators": {"cert_batch": ["2026-11-02T12:54"], "landing_domain": ["two.example"]}}
        fc = {"indicators": {"cert_batch": ["2026-11-02T12:55"], "landing_domain": ["three.example"]}}
        corpus = similarity.Corpus({"a": (fa, {}), "b": (fb, {}), "c": (fc, {}), "d": ({}, {}), "e": ({}, {})})
        link = similarity.pair("a", fa, {}, "b", fb, {}, corpus)
        self.assertTrue(link.must_link)
        self.assertEqual([s.group for s in link.shared_ids], ["certificates"])
        self.assertIn("certyfikat TLS", link.explain())
        self.assertFalse(similarity.pair("a", fa, {}, "c", fc, {}, corpus).must_link)


if __name__ == "__main__":
    unittest.main()
