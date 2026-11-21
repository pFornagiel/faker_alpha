"""Feature-extraction pipeline: Material -> (features: JSON-serialisable dict, vectors: dict of arrays).

Layers (see docs/METHODOLOGY.md §3):
  web      - landing URLs, redirect chain, trackers/IDs, contacts, forms, scripts, DOM template, IPs
  visual   - creative screenshots/keyframes: pHash, CLIP (look), DINOv2 (layout), OCR text + layout
  faces    - SCRFD + ArcFace, reference-gallery identity, unknown recurring faces
  text     - narrative MinHash (raw + entity-masked), e5 embedding, keywords, amounts, title template
  llm      - structured attributes (scam type, narrative template, persons, product, phrases...)
  meta     - ad-library IDs/advertiser (yt-dlp facebook:ads info.json), capture manifests, dates
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config, faces, gazetteer, llm, text, vision, web
from .ingest import Material, read_meta

log = logging.getLogger(__name__)
DATE_RX = [(re.compile(r"(20\d\d)-(\d\d)-(\d\d)"), (1, 2, 3)), (re.compile(r"(\d\d)-(\d\d)-(20\d\d)"), (3, 2, 1))]


def _dates(m: Material, meta: dict) -> list[str]:
    ds = set()
    for p in m.images + m.videos + [pg["path"] for pg in m.pages]:
        for rx, (y, mo, d) in DATE_RX:
            mm = rx.search(Path(p).name)
            if mm:
                ds.add(f"{mm.group(y)}-{mm.group(mo)}-{mm.group(d)}")
                break
    for c in meta.get("capture", []):
        if c.get("captured_at"):
            ds.add(str(c["captured_at"])[:10])
    for a in meta.get("ad_library", []):
        if a.get("timestamp"):
            ds.add(datetime.fromtimestamp(int(a["timestamp"]), timezone.utc).strftime("%Y-%m-%d"))
    return sorted(ds)


UI_MARKERS = ("szczegoly reklamy", "link do reklamy", "identyfikator biblioteki", "zostaw komentarz", "komentarze",
              "ad details", "library id", "about this ad", "informacje o reklamie", "zobacz szczegoly reklamy")


def is_ui_screenshot(ocr_text: str) -> bool:
    """Platform UI (ad-library details, comment threads) - identical chrome across unrelated cases; keep its OCR
    (advertiser, ad ID) but exclude it from visual similarity."""
    t = gazetteer.fold(ocr_text or "")
    return any(m in t for m in UI_MARKERS)


def _image_features(im, src: str, kind: str, want_faces: bool = True, want_ocr: bool = True) -> tuple[dict, dict]:
    crop = vision.crop_content(im)
    if kind in ("screenshot", "keyframe"):
        crop = vision.creative_crop(crop)
    f = {"src": src, "kind": kind, "size": list(im.size), **vision.hashes(crop)}
    vec = {}
    c = vision.clip_embed(crop)
    if c is not None:
        vec["clip"] = c
    d = vision.dino_embed(crop)
    if d is not None:
        vec["dino"] = d
    if want_ocr:
        o = vision.ocr(im)
        f["ocr_text"], f["ocr_lines"] = o["text"], o["lines"][:80]
        f["qr"] = vision.decode_qr(im)
    fl = []
    if want_faces:
        for fc in faces.faces_in_image(im):
            ident, sim = faces.identify(fc["embedding"])
            fl.append({"identity": ident, "sim": round(sim, 3), "quality": fc["quality"], "box_rel": fc["box_rel"],
                       "side": fc["side"], "src": src})
            vec.setdefault("faces", []).append(fc["embedding"])
    f["faces"] = fl
    if want_ocr:
        f["layout"] = vision.layout_signature(f.get("ocr_lines", []), fl).round(4).tolist()
    return f, vec


def analyze(m: Material, use_llm: bool = True, progress=None) -> tuple[dict, dict]:
    t0 = time.time()
    say = progress or (lambda s: log.info(s))
    meta = read_meta(m)
    feats: dict = {"material_id": m.id, "name": m.name, "source": m.source, "notes": list(m.notes),
                   "n_pages": len(m.pages), "n_images": len(m.images), "n_videos": len(m.videos)}
    vecs: dict[str, list] = {"clip": [], "dino": [], "faces": [], "text": [], "dom": []}
    ind: dict[str, set] = {}
    titles, page_texts, landing_urls, chains, ips, server_hdrs, dom_sigs, page_info = [], [], [], [], {}, {}, [], []
    file_shas, asset_hashes = set(), set()
    har_images = []

    # ---------------------------------------------------------------- web layer
    for pg in m.pages:
        p = Path(pg["path"])
        try:
            if pg["kind"] == "har":
                say(f"HAR: {p.name}")
                h = web.parse_har(p)
                web.merge_ind(ind, h["indicators"])
                chains.append(h["redirect_chain"])
                if h["redirect_chain"]:
                    landing_urls.append(h["redirect_chain"][0])
                for ip, n in h["ips"].items():
                    ips[ip] = ips.get(ip, 0) + n
                for k, n in h["server_headers"].items():
                    server_hdrs[k] = server_hdrs.get(k, 0) + n
                titles.extend(t for t in h["pages"] if t and not t.startswith(("http", "file:")))
                har_images.extend(h["images"])
                page_info.append({"kind": "har", "file": p.name, "requests": h["n_requests"],
                                  "hosts": sorted(h["hosts"], key=lambda k: -h["hosts"][k])[:15],
                                  "redirect_chain": h["redirect_chain"][:8], "posts": h["posts"][:8]})
            else:
                if pg["kind"] == "mhtml":
                    html, loc = web.parse_mhtml(p)
                else:
                    html, loc = p.read_text(encoding="utf-8", errors="replace"), pg.get("url", "")
                if not html:
                    continue
                say(f"HTML: {p.name[:60]}")
                file_shas.add(hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()[:20])
                e = web.extract_html(html, loc)
                web.merge_ind(ind, e["indicators"])
                if e["title"]:
                    titles.append(e["title"])
                page_texts.append(e["text"][:30000])
                for u in (e["saved_url"], e["canonical"], e["og_url"], loc):
                    if u and u.startswith("http"):
                        landing_urls.append(u)
                sh = web.tag_shingles(e["tags"])
                from datasketch import MinHash

                mh = MinHash(num_perm=128, seed=11)
                for s in sh:
                    mh.update(s.encode())
                dom_sigs.append(mh.hashvalues.tolist())
                page_info.append({"kind": pg["kind"], "file": p.name, "title": e["title"], "saved_url": e["saved_url"],
                                  "lang": e["lang"], "generator": e["generator"], "n_tags": len(e["tags"]),
                                  "forms": e["forms"][:5], "linked_domains": e["linked_domains"][:20],
                                  "comments": e["comments"][:5], "scripts": [s[:120] for s in e["scripts"][:25]]})
        except Exception as exc:
            log.warning("page %s failed: %s", p, exc)
            feats["notes"].append(f"unparseable page: {p.name}")
    for u in m.urls:
        web.merge_ind(ind, web.url_indicators(u))
        landing_urls.append(u)
    for c in meta["capture"]:
        for u in [c.get("url"), c.get("final_url")]:
            if u and str(u).startswith("http"):
                landing_urls.append(u)
                web.merge_ind(ind, web.url_indicators(u))
        if c.get("title"):
            titles.append(c["title"])
    for a in meta["ad_library"]:
        if a.get("ad_id"):
            ind.setdefault("ad_id", set()).add(f"library={a['ad_id']}")
        if a.get("advertiser_id"):
            ind.setdefault("advertiser_id", set()).add(str(a["advertiser_id"]))
        if a.get("advertiser"):
            ind.setdefault("advertiser_name", set()).add(gazetteer.fold(a["advertiser"]))
    # hosting: keep only non-CDN IPs (Cloudflare 104.16/12, 172.64/13, 188.114.96/20, Google, Akamai...)
    cdn_rx = re.compile(r"^(104\.(1[6-9]|2\d|3[01])\.|172\.(6[4-9]|7[01])\.|188\.114\.9[6-9]\.|162\.159\.|"
                        r"142\.25[01]\.|172\.217\.|216\.58\.|151\.101\.|2606:4700|2a06:98c1|157\.240\.|31\.13\.|"
                        r"13\.(3[2-5])\.|18\.(15[4-9]|16\d)\.|3\.16[0-9]\.|52\.(8[4-5])\.|23\.|57\.14[4-7]\.|179\.60\.|"
                        r"185\.60\.21[6-9]\.|69\.171\.|129\.134\.|2a03:2880)")
    for ip in ips:
        if not cdn_rx.match(ip):
            ind.setdefault("ip", set()).add(ip)
    feats["behind_cloudflare"] = any(cdn_rx.match(ip) for ip in ips)

    # ---------------------------------------------------------------- visual layer (creatives)
    img_feats = []
    sources = [(p, "screenshot") for p in m.images]
    for v in m.videos:
        vm = vision.video_meta(v)
        vsha = hashlib.sha1(f"{v}{Path(v).stat().st_size}".encode()).hexdigest()[:12]
        say(f"video keyframes: {Path(v).name[:50]}")
        kfs = vision.video_keyframes(v, config.ARTIFACTS / m.id / vsha)
        feats.setdefault("videos", []).append({"file": Path(v).name, **vm, "keyframes": len(kfs)})
        sources.extend((str(k), "keyframe") for k in kfs)
    for src, kind in sources[: config.MAX_IMAGES_PER_MATERIAL]:
        im = vision.load_rgb(src)
        if im is None:
            continue
        file_shas.add(vision.file_sha(src)[:20]) if kind == "screenshot" else None
        say(f"image ({kind}): {Path(src).name[:50]}")
        f, v = _image_features(im, str(src), kind)
        if is_ui_screenshot(f.get("ocr_text", "")):
            f["kind"] = "ui_screenshot"
        img_feats.append(f)
        for k in ("clip", "dino"):
            if k in v and f["kind"] != "ui_screenshot":
                vecs[k].append(v[k])
        for fv in v.get("faces", []):
            vecs["faces"].append(fv)
    # page assets (landing-page images): hash all, faces on the largest few
    asset_src = [(a, Path(a).stat().st_size) for a in m.assets] + [(f"har:{u}", len(b)) for u, b in har_images]
    asset_src = [a for a in asset_src if a[1] >= config.MIN_ASSET_BYTES]
    asset_src.sort(key=lambda t: -t[1])
    raw_by_src = {f"har:{u}": b for u, b in har_images}
    asset_faces = []
    for i, (a, _) in enumerate(asset_src[:60]):
        im = vision.load_rgb(raw_by_src[a] if a.startswith("har:") else a)
        if im is None or min(im.size) < config.MIN_ASSET_SIDE:
            continue
        asset_hashes.add(vision.hashes(im)["phash"])
        if i < 10:
            for fc in faces.faces_in_image(im, min_side=48):
                ident, sim = faces.identify(fc["embedding"])
                asset_faces.append({"identity": ident, "sim": round(sim, 3), "quality": fc["quality"],
                                    "src": "asset:" + Path(a).name[:60], "box_rel": fc["box_rel"], "side": fc["side"]})
                vecs["faces"].append(fc["embedding"])
    if asset_hashes:
        ind["asset_phash"] = {h for h in asset_hashes if h not in ("0000000000000000", "ffffffffffffffff", "8000000000000000")}

    # ---------------------------------------------------------------- ad-library facts read from screenshots
    for f in img_feats:
        lines = [l["text"] for l in f.get("ocr_lines", [])]
        for i, t in enumerate(lines):
            ft = gazetteer.fold(t)
            mm = re.search(r"identyfikator(?: biblioteki)?\W*(\d{10,20})", ft) or re.search(r"library id\W*(\d{10,20})", ft)
            if mm:
                ind.setdefault("ad_id", set()).add(f"library={mm.group(1)}")
            if ft.startswith("sponsorowan") and i > 0:
                adv = gazetteer.fold(lines[i - 1]).strip(" .·•")
                if 3 <= len(adv) <= 60 and not adv.startswith(("http", "www")):
                    ind.setdefault("advertiser_name", set()).add(adv)
    # ---------------------------------------------------------------- text layer
    ocr_text = " ".join(f.get("ocr_text", "") for f in img_feats)
    meta_text = " ".join(f"{a.get('title') or ''} {a.get('description') or ''} {a.get('advertiser') or ''}"
                         for a in meta["ad_library"])
    for f in img_feats:
        for q in f.get("qr", []):
            landing_urls.append(q)
            web.merge_ind(ind, web.url_indicators(q))
        for u in vision.urls_in_text(f.get("ocr_text", "")):
            d = web.registrable_domain(u)
            if d and not web.is_generic(d):
                ind.setdefault("ocr_domain", set()).add(d)
    all_text = "\n".join(dict.fromkeys(titles)) + "\n" + "\n".join(m.texts) + "\n" + meta_text + "\n" + ocr_text + "\n" + "\n".join(page_texts)
    all_text = all_text.strip()
    narrative_text = ("\n".join(dict.fromkeys(titles)) + "\n" + "\n".join(page_texts))[:40000] or all_text
    feats["text"] = {
        "titles": list(dict.fromkeys(titles))[:10],
        "title_templates": list(dict.fromkeys(text.title_template(t) for t in titles))[:10],
        "ocr_text": ocr_text[:4000],
        "excerpt": (" ".join(page_texts) or ocr_text or "\n".join(m.texts))[:1500],
        "n_chars": len(all_text),
        "keywords": text.keywords(narrative_text if len(narrative_text) > 200 else all_text),
        "amounts": text.amounts(all_text),
        "persons_text": gazetteer.find_persons(all_text),
        "brands_text": gazetteer.find_brands(all_text),
        "media_text": gazetteer.find_media(all_text),
        "minhash": text.minhash_sig(narrative_text),
        "minhash_masked": text.minhash_sig(narrative_text, masked=True),
        "minhash_ocr": text.minhash_sig(ocr_text) if len(ocr_text) > 80 else None,
    }
    say("text embedding")
    tv = text.embed_text(("\n".join(dict.fromkeys(titles)) + "\n" + (" ".join(page_texts) or all_text))[:6000])
    if tv is not None:
        vecs["text"].append(tv)
    if config.USE_GEMMA:      # opt-in second narrative embedding (EmbeddingGemma-2, research/05)
        from .text_gemma import embed_text_gemma

        say("text embedding (EmbeddingGemma-2)")
        gv = embed_text_gemma(("\n".join(dict.fromkeys(titles)) + "\n" + (" ".join(page_texts) or all_text))[:8000])
        if gv is not None:
            vecs["text_gemma"] = [gv]
    vecs["dom"] = dom_sigs

    # ---------------------------------------------------------------- LLM attributes
    llm_input = (f"TYTUŁY: {' | '.join(dict.fromkeys(titles))}\nURL: {' '.join(list(dict.fromkeys(landing_urls))[:3])[:600]}\n"
                 f"METADANE REKLAMY: {meta_text[:800]}\nTEKST Z OBRAZÓW (OCR): {ocr_text[:2500]}\n"
                 f"TEKST STRONY: {' '.join(page_texts)[:5000]}\nINNE: {' '.join(m.texts)[:1500]}")
    if use_llm:
        say("LLM attributes")
    attrs = llm.extract_attributes(llm_input, backend=None if use_llm else "none")
    vf = config.CACHE / "llm_extra_values.json"
    if vf.exists():
        try:
            import json as _json

            known = _json.loads(vf.read_text()).get(m.id, {})
            attrs["extra"] = {**known, **{k: v for k, v in (attrs.get("extra") or {}).items() if v}}
        except Exception:
            pass
    feats["llm"] = attrs
    prod = attrs.get("product_or_platform_name")
    if prod and len(prod) > 2:
        ind.setdefault("product", set()).add(gazetteer.fold(prod).strip())
    for ph in attrs.get("distinctive_phrases") or []:
        if len(ph) > 12:
            ind.setdefault("phrase", set()).add(text.normalize(ph))

    # ---------------------------------------------------------------- persons
    all_faces = [fc for f in img_feats for fc in f.get("faces", [])] + asset_faces
    feats["faces"] = all_faces
    feats["persons_visual"] = sorted({f["identity"] for f in all_faces if f["identity"]})
    feats["persons_named"] = sorted(set(feats["text"]["persons_text"]) | set(attrs.get("impersonated_persons") or []))

    # ---------------------------------------------------------------- summary of web layer
    landing_urls = [u for u in dict.fromkeys(landing_urls) if u.startswith("http")]
    # public domain metadata (RDAP / DNS / crt.sh / CERT Polska), cached; skipped offline
    from . import enrich

    infra = {}
    for d in sorted({web.registrable_domain(u) for u in landing_urls} - {""})[:6]:
        if web.is_generic(d):
            continue
        say(f"enrich: {d}")
        info = enrich.enrich_domain(d)
        if info:
            infra[d] = {"registrar": (info.get("rdap") or {}).get("registrar"), "created": (info.get("rdap") or {}).get("created"),
                        "nameservers": (info.get("rdap") or {}).get("nameservers"), "A": (info.get("dns") or {}).get("A"),
                        "n_certs": (info.get("crtsh") or {}).get("n_certs"), "first_cert": (info.get("crtsh") or {}).get("first_cert"),
                        "cert_pl_listed": info.get("cert_pl_listed")}
            web.merge_ind(ind, enrich.indicators(info))
    feats["infra"] = infra
    feats["web"] = {
        "landing_urls": landing_urls[:10],
        "landing_domains": sorted({web.registrable_domain(u) for u in landing_urls} - {""}),
        "redirect_chains": [c for c in chains if len(c) > 1][:5],
        "ips": sorted(ips, key=lambda k: -ips[k])[:15],
        "server_headers": sorted(server_hdrs, key=lambda k: -server_hdrs[k])[:10],
        "pages": page_info,
    }
    feats["images"] = [{k: v for k, v in f.items() if k != "ocr_lines"} for f in img_feats]
    feats["meta"] = meta
    feats["dates"] = _dates(m, meta)
    feats["file_shas"] = sorted(file_shas)
    feats["indicators"] = {k: sorted(v) for k, v in ind.items() if v}
    feats["elapsed_s"] = round(time.time() - t0, 1)
    vectors = {k: (np.stack(v) if len(v) and not isinstance(v[0], list) else v) for k, v in vecs.items()}
    return feats, vectors
