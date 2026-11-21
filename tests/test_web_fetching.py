"""Offline unit tests for SSRF/network safety, cloaking classification, ingestion safety,
canonical web parsing, domain enrichment, public sources, scheduler, and SQLite Store."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from requests.structures import CaseInsensitiveDict

from ftf import capture, enrich, ingest, net, scheduler, sources, store, web


def _fake_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    encoding: str = "utf-8",
):
    resp = mock.MagicMock()
    hdrs = CaseInsensitiveDict(headers or {})
    resp.status_code = status_code
    resp.headers = hdrs
    resp.is_redirect = status_code in (301, 302, 303, 307, 308) and "location" in hdrs
    resp.encoding = encoding
    resp.iter_content.return_value = [body] if body else []
    resp.close = mock.MagicMock()
    return resp


def _public_addrinfo(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


# Minimal valid 1x1 PNG bytes (with valid PNG signature)
_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestSSRFAndNetworkSafety(unittest.TestCase):
    def test_validate_public_url_rejects_unsafe_targets(self):
        blocked = [
            "file:///etc/passwd",
            "/etc/passwd",
            "ftp://example.com",
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://[::ffff:127.0.0.1]/",
        ]
        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    net.validate_public_url(url)

    def test_validate_public_url_accepts_public_literal_ip(self):
        clean, ips = net.validate_public_url("https://93.184.216.34/path")
        self.assertEqual(clean, "https://93.184.216.34/path")
        self.assertEqual(ips, ["93.184.216.34"])

    def test_capture_url_blocks_file_scheme_without_launching_playwright(self):
        with mock.patch("ftf.capture.render_browser") as mock_render:
            res = capture.capture_url("file:///etc/passwd", render=True)
        self.assertEqual(res["cloaking_verdict"], "invalid_url")
        self.assertFalse(res["cloaking"])
        mock_render.assert_not_called()

    def test_follow_profile_blocks_private_redirect_hop(self):
        r1 = _fake_response(302, {"Location": "http://127.0.0.1/admin"})
        with mock.patch("ftf.net.socket.getaddrinfo", side_effect=_public_addrinfo), \
                mock.patch("requests.Session.get", return_value=r1) as mock_get:
            res = capture.follow_profile("https://public.example/start", "desktop_pl", capture.PROFILES["desktop_pl"])
        self.assertEqual(mock_get.call_count, 1)
        self.assertIsNotNone(res["error"])
        self.assertIn("blocked redirect target", res["error"])
        self.assertEqual(res["final_url"], "https://public.example/start")

    def test_follow_profile_stops_on_redirect_cycle(self):
        responses = {
            "https://a.example/": _fake_response(302, {"Location": "https://b.example/"}),
            "https://b.example/": _fake_response(302, {"Location": "https://a.example/"}),
        }
        with mock.patch("ftf.net.socket.getaddrinfo", side_effect=_public_addrinfo), \
                mock.patch("requests.Session.get", side_effect=lambda u, **kw: responses[u]) as mock_get:
            res = capture.follow_profile("https://a.example/", "desktop_pl", capture.PROFILES["desktop_pl"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(res["error"], "redirect cycle detected")
        self.assertEqual(res["chain"], ["https://a.example/", "https://b.example/"])

    def test_follow_profile_unescapes_meta_refresh_amp(self):
        hop1_html = (
            b'<html><head><meta http-equiv="refresh" '
            b'content="0; url=https://b.example/offer?a=1&amp;b=2"></head><body>Redirecting</body></html>'
        )
        hop2_html = b"<html><head><title>Landing</title></head><body>Loaded cleanly</body></html>"
        responses = {
            "https://a.example/go": _fake_response(200, {"Content-Type": "text/html"}, hop1_html),
            "https://b.example/offer?a=1&b=2": _fake_response(200, {"Content-Type": "text/html"}, hop2_html),
        }
        with mock.patch("ftf.net.socket.getaddrinfo", side_effect=_public_addrinfo), \
                mock.patch("requests.Session.get", side_effect=lambda u, **kw: responses[u]):
            res = capture.follow_profile("https://a.example/go", "desktop_pl", capture.PROFILES["desktop_pl"])
        self.assertIsNone(res["error"])
        self.assertEqual(res["final_url"], "https://b.example/offer?a=1&b=2")
        self.assertNotIn("&amp;", res["final_url"])
        self.assertEqual(res["status"], 200)

    def test_cloudflare_and_cdn_ip_classification(self):
        self.assertTrue(net.is_cloudflare_ip("188.114.105.1"))
        self.assertTrue(net.is_cdn_ip("188.114.105.1"))

        self.assertFalse(net.is_cloudflare_ip("23.32.0.1"))
        self.assertTrue(net.is_cdn_ip("23.32.0.1"))

        self.assertFalse(net.is_cloudflare_ip("23.1.2.3"))
        self.assertFalse(net.is_cdn_ip("23.1.2.3"))

        for ip in ("8.8.8.8", "93.184.216.34"):
            self.assertFalse(net.is_cloudflare_ip(ip))
            self.assertFalse(net.is_cdn_ip(ip))

        for bad in ("", "not-an-ip", "999.999.999.999"):
            self.assertFalse(net.is_cloudflare_ip(bad))
            self.assertFalse(net.is_cdn_ip(bad))


class TestCloakingClassifier(unittest.TestCase):
    def _nask_html(self, nonce: str) -> str:
        return (
            f'<!doctype html><html><head><title>NASK - Państwowy Instytut Badawczy</title>'
            f'<script nonce="{nonce}">window.__nonce="{nonce}";</script></head>'
            f'<body><header><nav><a href="/o-nas">O nas</a><a href="/cert">CERT Polska</a></nav></header>'
            f'<main><h1>Bezpieczeństwo w sieci i analiza zagrożeń</h1>'
            f'<p>Instytut NASK prowadzi badania nad cyberbezpieczeństwem, analizą kampanii phishingowych '
            f'oraz ochroną obywateli przed oszustwami internetowymi w Polsce i Europie.</p></main></body></html>'
        )

    def test_csp_nonce_diff_not_cloaking(self):
        profiles = {
            "bot": {"status": 200, "final_url": "https://www.nask.pl/", "html": self._nask_html("n1")},
            "desktop_pl": {"status": 200, "final_url": "https://www.nask.pl/", "html": self._nask_html("n2")},
            "fb_mobile": {"status": 200, "final_url": "https://www.nask.pl/", "html": self._nask_html("n3")},
        }
        res = capture.classify_cloaking(profiles)
        self.assertFalse(res["cloaking"])
        self.assertEqual(res["verdict"], "none")

    def test_responsive_mobile_variant_not_cloaking(self):
        article = (
            "<article><h1>Wiadomości dnia z kraju i ze świata</h1>"
            "<p>Najważniejsze informacje gospodarcze, polityczne oraz lokalne przygotowane przez redakcję "
            "portalu informacyjnego na podstawie oficjalnych komunikatów i relacji korespondentów.</p>"
            "<p>Czytaj także komentarze ekspertów oraz szczegółowe analizy wydarzeń bieżącego tygodnia.</p></article>"
        )
        desktop = (
            f"<html><head><title>Onet - Wiadomości</title></head><body>"
            f"<header><nav><ul><li><a href='/kraj'>Kraj</a></li><li><a href='/swiat'>Świat</a></li>"
            f"<li><a href='/biznes'>Biznes</a></li></ul></nav></header><main>{article}</main>"
            f"<aside><div>Pogoda</div></aside><footer>Redakcja</footer></body></html>"
        )
        mobile = (
            f"<html><head><title>Onet - Wiadomości</title></head><body>"
            f"<div class='m-nav'><button>Menu</button></div><section>{article}</section>"
            f"<footer>Redakcja</footer></body></html>"
        )
        profiles = {
            "bot": {"status": 200, "final_url": "https://www.onet.pl/", "html": desktop},
            "desktop_pl": {"status": 200, "final_url": "https://www.onet.pl/", "html": desktop},
            "fb_mobile": {"status": 200, "final_url": "https://www.onet.pl/", "html": mobile},
        }
        res = capture.classify_cloaking(profiles)
        self.assertFalse(res["cloaking"])
        self.assertIn(res["verdict"], ("none", "responsive_variant"))

    def test_waf_bot_block_not_cloaking(self):
        body = self._nask_html("same")
        profiles = {
            "bot": {"status": 403, "final_url": "https://protected.example/", "html": "<html><body>Access Denied</body></html>"},
            "desktop_pl": {"status": 200, "final_url": "https://protected.example/", "html": body},
            "fb_mobile": {"status": 200, "final_url": "https://protected.example/", "html": body},
        }
        res = capture.classify_cloaking(profiles)
        self.assertFalse(res["cloaking"])
        self.assertEqual(res["verdict"], "bot_blocked")

    def test_domain_redirect_cloaking(self):
        profiles = {
            "bot": {"status": 200, "final_url": "https://whitepage.example/", "html": "<html><title>Blog</title><body>White page</body></html>"},
            "desktop_pl": {"status": 200, "final_url": "https://whitepage.example/", "html": "<html><title>Blog</title><body>White page</body></html>"},
            "fb_mobile": {"status": 200, "final_url": "https://scamoffer.click/offer", "html": "<html><title>Oferta</title><body>Scam offer</body></html>"},
        }
        res = capture.classify_cloaking(profiles)
        self.assertTrue(res["cloaking"])
        self.assertEqual(res["verdict"], "cloaking_suspected")

    def test_content_cloaking_same_domain(self):
        white = (
            "<html><head><title>Business Coaching Blog</title></head><body>"
            "<header><nav><ul><li>Home</li><li>Leadership</li><li>Workshops</li></ul></nav></header>"
            "<aside><dl><dt>Schedule</dt><dd>Weekly mentoring calls for executive managers</dd></dl></aside>"
            "<div><blockquote>Effective team leadership requires transparent quarterly planning, "
            "clear communication habits, employee feedback surveys, agile retrospective rituals, "
            "structured onboarding guides, and calm conflict resolution frameworks across remote departments.</blockquote></div>"
            "<footer><address>Consulting Studio Warsaw</address></footer></body></html>"
        )
        scam = (
            "<html><head><title>Rafał Brzoska Inwestycja — Specjalny Raport</title></head><body>"
            "<main><article><figure><img src='/hero.jpg'><figcaption>Nagranie usunięto przed północą</figcaption></figure>"
            "<section><h2>Rafał Brzoska ujawnia sekretny algorytm kryptowalutowy</h2>"
            "<p>Tysiące Polaków zarabia już od 250 zł depozytu dzięki automatycznej platformie handlowej. "
            "Zarejestruj numer telefonu w formularzu poniżej aby odebrać gwarantowany dochód pasywny jeszcze dzisiaj "
            "zanim banki zablokują dostęp do naszego programu inwestycyjnego.</p></section>"
            "<form><fieldset><input name='first_name'><input name='phone'><button>Odbierz zysk</button></fieldset></form>"
            "<table><tbody><tr><td>Wpłata</td><td>250 PLN</td></tr></tbody></table></article></main></body></html>"
        )
        profiles = {
            "desktop_pl": {"status": 200, "final_url": "https://cloak.example/article", "html": white},
            "fb_mobile": {"status": 200, "final_url": "https://cloak.example/article", "html": scam},
        }
        res = capture.classify_cloaking(profiles)
        self.assertTrue(res["cloaking"])
        self.assertEqual(res["verdict"], "cloaking_suspected")

    def test_unreachable_all_errors(self):
        profiles = {
            "bot": {"status": 500, "final_url": "https://dead.example/", "html": "", "error": "HTTP 500"},
            "desktop_pl": {"status": None, "final_url": "https://dead.example/", "html": "", "error": "timeout"},
            "fb_mobile": {"status": 502, "final_url": "https://dead.example/", "html": "", "error": "Bad Gateway"},
        }
        res = capture.classify_cloaking(profiles)
        self.assertFalse(res["cloaking"])
        self.assertEqual(res["verdict"], "unreachable")


class TestIngestionSafetyAndClassification(unittest.TestCase):
    def test_dotfile_har_detected_in_subfolder(self):
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "nested"
            sub.mkdir()
            har_path = sub / ".har"
            har_path.write_text('{"log": {"entries": []}}', encoding="utf-8")
            m = ingest.load_folder(td, source="test")
            self.assertEqual(len(m.pages), 1)
            self.assertEqual(m.pages[0]["kind"], "har")
            self.assertEqual(Path(m.pages[0]["path"]).name, ".har")

    def test_files_dir_separates_real_png_from_js_pobrane_and_css(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "page.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
            files_dir = root / "page_files"
            files_dir.mkdir()
            (files_dir / "hero.png").write_bytes(_MINIMAL_PNG)
            (files_dir / "bundle.js.pobrane").write_text("console.log('a');", encoding="utf-8")
            (files_dir / "tracker.js.pobierz").write_text("fbq('init', '1071875908635809');", encoding="utf-8")
            (files_dir / "style.css").write_text("body { color: red; }", encoding="utf-8")
            (files_dir / "theme.css.pobrane").write_text("body { margin: 0; }", encoding="utf-8")

            m = ingest.load_folder(root, source="test")
            asset_names = [Path(p).name for p in m.assets]
            script_names = [Path(p).name for p in m.scripts]
            self.assertEqual(asset_names, ["hero.png"])
            self.assertEqual(sorted(script_names), ["bundle.js.pobrane", "tracker.js.pobierz"])

    def test_sibling_dom_html_and_mhtml_preserves_snapshot_url(self):
        snap_url = "https://ineptsolidoval.top/?pxl=1071875908635809&ad_id=120250558396250564"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dom.html").write_text("<html><head><title>Offer</title></head><body>Hi</body></html>", encoding="utf-8")
            (root / "page.mhtml").write_text(
                f"From: <Saved by Blink>\r\n"
                f"Snapshot-Content-Location: {snap_url}\r\n"
                f"Content-Type: text/html\r\n\r\n"
                f"<html><body>Hi</body></html>",
                encoding="utf-8",
            )
            m = ingest.load_folder(root, source="test")
            self.assertIn(snap_url, m.urls)
            html_pages = [pg for pg in m.pages if pg["kind"] == "html"]
            self.assertEqual(len(html_pages), 1)
            self.assertEqual(html_pages[0].get("url"), snap_url)
            self.assertEqual([pg for pg in m.pages if pg["kind"] == "mhtml"], [])

    def test_extract_zip_safely_blocks_zip_slip_and_oversized_member(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z_slip = root / "slip.zip"
            with zipfile.ZipFile(z_slip, "w") as zf:
                zf.writestr("../unzipped_evil/pwn.txt", "pwned")
                zf.writestr("safe/hello.txt", "ok")
            dest = root / "unzipped"
            ingest._extract_zip_safely(z_slip, dest)
            self.assertFalse((root / "unzipped_evil" / "pwn.txt").exists())
            self.assertTrue((dest / "safe" / "hello.txt").exists())

            z_big = root / "big.zip"
            with zipfile.ZipFile(z_big, "w") as zf:
                zf.writestr("huge.txt", "A" * 2048)
            with mock.patch.object(ingest, "MAX_FILE_BYTES", 1024):
                with self.assertRaises(ValueError):
                    ingest._extract_zip_safely(z_big, root / "dest_big")

    def test_from_text_strips_trailing_url_punctuation(self):
        m = ingest.from_text("Sprawdź link (https://evil.click/offer), pilne!")
        self.assertEqual(m.urls, ["https://evil.click/offer"])

    def test_read_meta_preserves_cloaking_fields(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "capture_manifest.json"
            manifest.write_text(
                json.dumps({
                    "tool": "ftf.capture",
                    "page_url": "https://cloak.example/",
                    "final_url": "https://scam.click/",
                    "title": "Oferta",
                    "cloaking": True,
                    "cloaking_verdict": "cloaking_suspected",
                    "cloaking_reasons": ["different final domain: desktop_pl -> cloak.example vs fb_mobile -> scam.click"],
                }),
                encoding="utf-8",
            )
            m = ingest.Material(id="t1", name="t1", source="url", source_ref="https://cloak.example/", meta=[str(manifest)])
            meta = ingest.read_meta(m)
            self.assertEqual(len(meta["capture"]), 1)
            cap = meta["capture"][0]
            self.assertTrue(cap["cloaking"])
            self.assertEqual(cap["cloaking_verdict"], "cloaking_suspected")
            self.assertEqual(len(cap["cloaking_reasons"]), 1)


class TestCanonicalWebParsing(unittest.TestCase):
    def test_psl_private_domains_are_distinct(self):
        self.assertEqual(web.registrable_domain("https://a.pages.dev/x"), "a.pages.dev")
        self.assertEqual(web.registrable_domain("https://b.pages.dev/x"), "b.pages.dev")
        self.assertNotEqual(web.registrable_domain("https://a.pages.dev/"), web.registrable_domain("https://b.pages.dev/"))

        self.assertEqual(web.registrable_domain("https://a.netlify.app/"), "a.netlify.app")
        self.assertEqual(web.registrable_domain("https://b.netlify.app/"), "b.netlify.app")
        self.assertNotEqual(web.registrable_domain("https://a.netlify.app/"), web.registrable_domain("https://b.netlify.app/"))

    def test_generic_and_decoy_domain_exclusion(self):
        for dom in ("google.pl", "images.unsplash.com", "translate.googleapis.com"):
            with self.subTest(generic=dom):
                self.assertTrue(web.is_generic(dom))
        for dom in ("amazon.com", "fb.me", "interia.pl"):
            with self.subTest(decoy=dom):
                self.assertTrue(web.is_decoy_or_generic_domain(dom))
        self.assertFalse(web.is_generic("novumfy.com"))
        self.assertFalse(web.is_decoy_or_generic_domain("novumfy.com"))

    def test_shared_hosting_customers_are_distinct_and_platform_is_generic(self):
        a = "xd-f1cf3d4fdb19408ea770fc6f80817dcb.ecs.us-east-1.on.aws"
        b = "dv-c3e594c6d429469e90b54478358619c3.ecs.us-east-1.on.aws"
        self.assertEqual(web.registrable_domain(f"https://{a}/api"), a)
        self.assertNotEqual(web.registrable_domain(a), web.registrable_domain(b))
        self.assertEqual(web.registrable_domain("890012.weebly.com"), "890012.weebly.com")
        self.assertFalse(web.is_generic(a))
        for platform in ("on.aws", "weebly.com", "base44.app"):
            with self.subTest(platform=platform):
                self.assertTrue(web.is_generic(platform))
        self.assertEqual(web.registrable_domain("www.dorquesio.click"), "dorquesio.click")

    def test_public_services_and_platform_endpoints_never_link(self):
        for dom in ("flagcdn.com", "ipapi.co", "api.frankfurter.dev", "example.com"):
            with self.subTest(public=dom):
                self.assertTrue(web.is_generic(web.registrable_domain(dom)))
        for endpoint in ("POST /cdn-cgi/rum", "POST /wp-admin/admin-ajax.php", "us.i.posthog.com/e/", "POST /api/collect"):
            with self.subTest(platform=endpoint):
                self.assertTrue(web.is_platform_endpoint(endpoint))
        for endpoint in ("POST /api/v1/trigger/field/{id}/", "dorquesio.click/api/v1/trigger/field/{id}/",
                         "POST /.events/v2/page_view"):
            with self.subTest(operator=endpoint):
                self.assertFalse(web.is_platform_endpoint(endpoint))

    def test_fb_pixel_canonical_equivalence_across_sources(self):
        html_ind = web.extract_html("<script>fbq('init', '1071875908635809');</script>")["indicators"]
        url_pxl = web.url_indicators("https://lander.click/go?pxl=1071875908635809")
        url_fbpx = web.url_indicators("https://lander.click/go?fbpx=1071875908635809")
        self.assertEqual(html_ind["fb_pixel"], {"1071875908635809"})
        self.assertEqual(url_pxl["fb_pixel"], {"1071875908635809"})
        self.assertEqual(url_fbpx["fb_pixel"], {"1071875908635809"})

    def test_har_parser_long_url_landing_selection_and_session_uuid_exclusion(self):
        visit_uuid = "01948b55-dea2-7123-8456-123456789abc"
        builder_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        pad = "X" * 620
        long_landing = (
            f"https://novumfy.com/article?utm_visit={visit_uuid}&fbclid={pad}"
            f"&pxl=1071875908635809&lpkey=abc123def456"
        )
        self.assertGreater(len(long_landing), 650)
        har = {
            "log": {
                "pages": [],
                "entries": [
                    {
                        "request": {"method": "POST", "url": f"https://novumfy.com/api/v1/trigger/field/{visit_uuid}/"},
                        "response": {"status": 404, "headers": [], "content": {"mimeType": "text/html", "text": "Not Found"}},
                    },
                    {
                        "request": {"method": "GET", "url": long_landing},
                        "response": {"status": 200, "headers": [], "content": {"mimeType": "text/html", "text": "<html><title>News</title></html>"}},
                    },
                    {
                        "request": {"method": "GET", "url": f"https://novumfy.com/assets/{visit_uuid}/ping.png"},
                        "response": {"status": 200, "headers": [], "content": {"mimeType": "image/png", "text": ""}},
                    },
                    {
                        "request": {"method": "GET", "url": f"https://novumfy.com/assets/{builder_uuid}/hero.jpg"},
                        "response": {"status": 200, "headers": [], "content": {"mimeType": "image/jpeg", "text": ""}},
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as td:
            hp = Path(td) / "sample.har"
            hp.write_text(json.dumps(har), encoding="utf-8")
            parsed = web.parse_har(hp)

        self.assertTrue(parsed["redirect_chain"][0].startswith("https://novumfy.com/article?"))
        ind = parsed["indicators"]
        self.assertIn("1071875908635809", ind.get("fb_pixel", set()))
        self.assertIn("lpkey=abc123def456", ind.get("affiliate", set()))
        self.assertNotIn(visit_uuid, ind.get("tenant_uuid", set()))
        self.assertIn(builder_uuid, ind.get("tenant_uuid", set()))
        self.assertIn("POST /api/v1/trigger/field/{id}/", ind.get("api_template", set()))

    def test_chrome_duplicate_suffix_stripped_and_removed_indicators_not_emitted(self):
        self.assertEqual(web._clean_asset_filename("scam_lander_kit(1).css"), "scam_lander_kit.css")
        self.assertEqual(web._clean_asset_filename("bundle.js.pobrane"), "bundle.js")
        html = (
            '<html><head><link rel="stylesheet" href="page_files/scam_lander_kit(1).css">'
            '<script src="https://op-one.click/lander_core.js"></script>'
            '<script>ym(12345678, "init"); var buildId = "abcdEFGH1234";</script></head>'
            '<body><form action="https://op-one.click/api/lead"><input name="phone"></form></body></html>'
        )
        ind = web.extract_html(html)["indicators"]
        for removed in ("css_name", "script_name", "form_fields", "ym", "build_id", "param_signature"):
            self.assertNotIn(removed, ind)
        self.assertEqual(ind.get("form_endpoint"), {"op-one.click/api/lead"})
        self.assertNotIn("param_signature", web.url_indicators("https://op-one.click/?acc=abc123&pxl=1071875908635809"))

    def test_parse_mhtml_handles_none_payload_without_crashing(self):
        raw = (
            b"From: <Saved by Blink>\r\n"
            b"Snapshot-Content-Location: https://example.com/page\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/related; boundary="B1"\r\n\r\n'
            b"--B1\r\n"
            b"Content-Type: text/html; charset=unknown-broken-charset\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n"
            b"--B1--\r\n"
        )
        with tempfile.TemporaryDirectory() as td:
            mp = Path(td) / "broken.mhtml"
            mp.write_bytes(raw)
            orig_get_payload = __import__("email.message", fromlist=["MIMEPart"]).MIMEPart.get_payload

            def _none_on_decode(self_part, i=None, decode=False):
                if decode:
                    return None
                return orig_get_payload(self_part, i=i, decode=decode)

            with mock.patch("email.message.MIMEPart.get_content", side_effect=LookupError("bad charset")), \
                    mock.patch("email.message.MIMEPart.get_payload", new=_none_on_decode):
                html, loc = web.parse_mhtml(mp)
        self.assertEqual(html, "")
        self.assertEqual(loc, "https://example.com/page")

    def test_phone_normalization_and_fictional_555_01xx_rejection(self):
        ind = web.regex_indicators("Zadzwoń: 0048 601 234 567 albo fikcyjny +48225550199")
        self.assertEqual(ind.get("phone"), {"+48601234567"})


class TestEnrichment(unittest.TestCase):
    def test_ftf_enrich_env_toggle_disables_enrichment(self):
        with mock.patch.dict(os.environ, {"FTF_ENRICH": "0"}):
            self.assertFalse(enrich.is_enabled())
            self.assertEqual(enrich.enrich_domain("example.com"), {})
            self.assertEqual(enrich.enrich_domains(["example.com"]), {})
        with mock.patch.dict(os.environ, {"FTF_ENRICH": "1"}):
            self.assertTrue(enrich.is_enabled())

    def test_crtsh_http_503_returns_error_not_zero_certs(self):
        resp = mock.MagicMock(status_code=503)
        with mock.patch("ftf.enrich.requests.get", return_value=resp):
            res = enrich.crtsh("example.com")
        self.assertIn("error", res)
        self.assertNotIn("n_certs", res)


class TestSourcesSchedulerAndStore(unittest.TestCase):
    def test_cert_pl_stem_matching_avoids_substring_false_positives(self):
        hits_pos = sources._match_domain_stems("orlen-akcje.click", sources.DOMAIN_STEMS)
        self.assertIn("orlen", hits_pos)
        self.assertIn("akcj", hits_pos)

        hits_neg = sources._match_domain_stems("allegro-transakcja.click", sources.DOMAIN_STEMS)
        self.assertEqual(hits_neg, [])

    def test_meta_ad_media_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            sources.meta_ad_media("../evil")

    def test_scheduler_suspicion_scoring(self):
        s_url, why_url = scheduler.suspicion({"url": "https://promo.click/offer?id=1"})
        self.assertIn("ryzykowna TLD", why_url)
        self.assertGreater(s_url, 0.0)

        s_plain, _ = scheduler.suspicion({"source": "cert_pl", "domain": "logowanie-klienta.pl"})
        self.assertLess(s_plain, 0.5)

        s_scam, _ = scheduler.suspicion({"source": "cert_pl", "domain": "orlen-inwestycja-zysk.click"})
        self.assertGreaterEqual(s_scam, 0.5)

    def test_scheduler_dedup_key_distinguishes_google_atc_advertisers(self):
        a1 = {"source": "google_atc", "kind": "advertiser", "advertiser_id": "AR001", "name": "Alpha Sp."}
        a2 = {"source": "google_atc", "kind": "advertiser", "advertiser_id": "AR002", "name": "Beta Sp."}
        self.assertNotEqual(scheduler._dedup_key(a1), scheduler._dedup_key(a2))

    def test_store_roundtrip_on_temp_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite"
            st = store.Store(db_path)
            try:
                m = ingest.Material(id="m001", name="case_a", source="test", source_ref="ref_a", label="A")
                feats = {"name": "case_a", "indicators": {"fb_pixel": ["1071875908635809"]}}
                vecs = {"text": np.array([[1.0, 0.0, 0.0]], dtype=np.float32)}

                self.assertFalse(st.has("m001"))
                self.assertEqual(st.count(), 0)

                st.upsert(m, feats, vecs)
                self.assertTrue(st.has("m001"))
                self.assertEqual(st.count(), 1)

                loaded_f, loaded_v = st.all()["m001"]
                self.assertEqual(loaded_f["name"], "case_a")
                self.assertEqual(loaded_f["_label"], "A")
                np.testing.assert_allclose(loaded_v["text"], vecs["text"])

                st.put("watermark", 42)
                self.assertEqual(st.get("watermark"), 42)
                self.assertEqual(st.get("missing", "default"), "default")

                st.log("scan", {"n": 3})
                evs = st.events(limit=5)
                self.assertEqual(len(evs), 1)
                self.assertEqual(evs[0]["kind"], "scan")
                self.assertEqual(evs[0]["payload"], {"n": 3})
            finally:
                st.db.close()


if __name__ == "__main__":
    unittest.main()
