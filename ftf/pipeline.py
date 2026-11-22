"""Feature-extraction pipeline: Material -> (features: JSON-serialisable dict, vectors: dict of arrays).

Executed as 6 explicit, typed stages:
  Stage 1 (_stage_web)              - HTML/MHTML/HAR/URLs/capture-meta/ad-library-meta/saved scripts, DOM MinHash, non-CDN IPs
  Stage 2 (_stage_visual_and_faces) - keyframes, screenshots, UI filter, deduplicated page assets (pHash), SCRFD+ArcFace, OCR ad facts
  Stage 3 (_stage_text)             - text aggregation, gazetteer, keywords/amounts, entity-masked MinHash (page / creative), e5
  Stage 4 (_stage_llm)              - structured LLM attributes (or deterministic rules when use_llm=False)
  Stage 5 (_stage_enrich)           - optional concurrent public OSINT enrichment (RDAP / DNS / crt.sh / CERT Polska)
  Stage 6 (_assemble_features)      - merge indicators, vectors and JSON-serialisable feature summary
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from datasketch import MinHash

from . import config, enrich, faces, gazetteer, lang, llm, net, text, vision, web
from .ingest import Material, read_meta

log = logging.getLogger(__name__)
DATE_RX = [(re.compile(r"(20\d\d)-(\d\d)-(\d\d)"), (1, 2, 3)), (re.compile(r"(\d\d)-(\d\d)-(20\d\d)"), (3, 2, 1))]

# Platform ad-library / ad-details UI chrome (identical across unrelated ads -> keep OCR, skip the images view).
# Note: intentionally excludes "komentarze" / "zostaw komentarz" which appear on normal fake-news landing pages.
UI_MARKERS = (
    "szczegoly reklamy", "link do reklamy", "identyfikator biblioteki",
    "ad details", "library id", "about this ad", "informacje o reklamie", "zobacz szczegoly reklamy",
)
_SPONSORED_LABEL_RX = re.compile(r"sponsorowan[ea]|sponsored")
_SENTENCE_PUNCT_RX = re.compile(r"[.!?]")


# -------------------------------------------------------------------------------------- stage outputs
@dataclass
class WebStage:
    indicators: dict[str, set[str]] = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)
    landing_urls: list[str] = field(default_factory=list)
    chains: list[list[str]] = field(default_factory=list)
    ips: dict[str, int] = field(default_factory=dict)
    landing_ips: set[str] = field(default_factory=set)
    server_hdrs: dict[str, int] = field(default_factory=dict)
    dom_sigs: list[list[int]] = field(default_factory=list)
    css_sigs: list[list[int]] = field(default_factory=list)
    js_sigs: list[list[int]] = field(default_factory=list)
    page_info: list[dict] = field(default_factory=list)
    file_shas: set[str] = field(default_factory=set)
    har_images: list[tuple[str, bytes]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    behind_cloudflare: bool = False


@dataclass
class VisualStage:
    img_feats: list[dict] = field(default_factory=list)
    asset_faces: list[dict] = field(default_factory=list)
    videos: list[dict] = field(default_factory=list)
    face_vecs: list[np.ndarray] = field(default_factory=list)
    local_rows: list[np.ndarray] = field(default_factory=list)
    file_shas: set[str] = field(default_factory=set)
    qr_urls: list[str] = field(default_factory=list)
    indicators: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class TextStage:
    text_summary: dict = field(default_factory=dict)
    ocr_text: str = ""
    meta_text: str = ""
    text_vecs: list[np.ndarray] = field(default_factory=list)


@dataclass
class LlmStage:
    attrs: dict = field(default_factory=dict)
    indicators: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class EnrichStage:
    infra: dict = field(default_factory=dict)
    behind_cloudflare: bool = False


# -------------------------------------------------------------------------------------- helpers
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


def is_ui_screenshot(ocr_text: str) -> bool:
    """Platform UI (ad-library details) - identical chrome across unrelated cases; keep OCR, exclude from the images view."""
    t = gazetteer.fold(ocr_text or "")
    return any(m in t for m in UI_MARKERS)


def _image_features(im, src: str, kind: str, want_faces: bool = True, want_ocr: bool = True) -> tuple[dict, dict]:
    crop = vision.creative_view(im, kind)
    f = {"src": src, "kind": kind, "size": list(im.size), **vision.hashes(crop)}
    vec: dict = {}
    loc = vision.local_descriptors(crop)
    if len(loc[1]):
        vec["local"] = vision.pack_local(loc)
        f["local"] = [0, len(loc[1]), *loc[2]]      # [first row in the "local" vectors, keypoints, scaled width, height]
    if want_ocr:
        o = vision.ocr(im)
        f["ocr_text"], f["ocr_lines"] = o["text"], o["lines"][:80]
        f["qr"] = vision.decode_qr(im)
    fl = []
    if want_faces:
        for fc in faces.faces_in_image(im):
            ident, sim = faces.identify(fc["embedding"])
            fl.append({
                "identity": ident, "sim": round(sim, 3), "det_score": fc["det_score"],
                "box_rel": fc["box_rel"], "side": fc["side"], "src": src,
            })
            vec.setdefault("faces", []).append(fc["embedding"])
    f["faces"] = fl
    return f, vec


# -------------------------------------------------------------------------------------- Stage 1: Web
def _stage_web(m: Material, meta: dict, say: Callable[[str], None]) -> WebStage:
    st = WebStage()
    har_req_ips: list[tuple[str, str]] = []  # (registrable_domain, ip)

    for pg in m.pages:
        p = Path(pg["path"])
        try:
            if pg["kind"] == "har":
                say(f"HAR: {p.name}")
                h = web.parse_har(p)
                web.merge_ind(st.indicators, h["indicators"])
                st.chains.append(h["redirect_chain"])
                if h["redirect_chain"]:
                    st.landing_urls.append(h["redirect_chain"][0])
                for ip, n in h["ips"].items():
                    st.ips[ip] = st.ips.get(ip, 0) + n
                for req in h.get("requests", []):
                    rip = (req.get("ip") or "").strip("[]")
                    rdom = web.registrable_domain(req.get("url", ""))
                    if rip and rdom:
                        har_req_ips.append((rdom, rip))
                for k, n in h["server_headers"].items():
                    st.server_hdrs[k] = st.server_hdrs.get(k, 0) + n
                st.titles.extend(t for t in h["pages"] if t and not t.startswith(("http", "file:")))
                st.har_images.extend(h["images"])
                st.page_info.append({
                    "kind": "har", "file": p.name, "requests": h["n_requests"],
                    "hosts": sorted(h["hosts"], key=lambda k: -h["hosts"][k])[:15],
                    "redirect_chain": h["redirect_chain"][:8], "posts": h["posts"][:8],
                })
            else:
                if pg["kind"] == "mhtml":
                    html, loc = web.parse_mhtml(p)
                else:
                    html, loc = p.read_text(encoding="utf-8", errors="replace"), pg.get("url", "")
                if not html:
                    continue
                say(f"HTML: {p.name[:60]}")
                st.file_shas.add(hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()[:20])
                e = web.extract_html(html, loc)
                web.merge_ind(st.indicators, e["indicators"])
                if e["title"]:
                    st.titles.append(e["title"])
                st.page_texts.append(e["text"][:30000])
                for u in (e["saved_url"], e["canonical"], e["og_url"], loc):
                    if u and u.startswith("http"):
                        st.landing_urls.append(u)
                sh = web.tag_shingles(e["tags"])
                mh = MinHash(num_perm=128, seed=11)
                for s in sh:
                    mh.update(s.encode())
                st.dom_sigs.append(mh.hashvalues.tolist())
                for sigs, toks, seed, need in ((st.css_sigs, e["class_vocabulary"], 13, config.MIN_CLASS_NAMES),
                                               (st.js_sigs, e["script_shingles"], 17, config.MIN_SCRIPT_SHINGLES)):
                    sig = text.set_sig(toks, seed, need)
                    if sig:
                        sigs.append(sig)
                st.page_info.append({
                    "kind": pg["kind"], "file": p.name, "title": e["title"], "saved_url": e["saved_url"],
                    "lang": e["lang"], "generator": e["generator"], "n_tags": len(e["tags"]),
                    "n_classes": len(e["class_vocabulary"]), "n_script_shingles": len(e["script_shingles"]),
                    "forms": e["forms"][:5], "linked_domains": e["linked_domains"][:20],
                    "comments": e["comments"][:5], "scripts": [s[:120] for s in e["scripts"][:25]],
                })
        except Exception as exc:
            log.warning("page %s failed: %s", p, exc)
            st.notes.append(f"unparseable page: {p.name}")

    # Saved local scripts (optional field on Material)
    for sp in getattr(m, "scripts", []) or []:
        web.merge_ind(st.indicators, web.extract_script_indicators(Path(sp)))

    # Input URLs & capture / ad-library metadata
    for u in m.urls:
        web.merge_ind(st.indicators, web.url_indicators(u))
        st.landing_urls.append(u)
    for c in meta.get("capture", []):
        for u in (c.get("url"), c.get("final_url")):
            if u and str(u).startswith("http"):
                st.landing_urls.append(str(u))
                web.merge_ind(st.indicators, web.url_indicators(str(u)))
        if c.get("title"):
            st.titles.append(c["title"])
    for a in meta.get("ad_library", []):
        if a.get("ad_id"):
            st.indicators.setdefault("ad_id", set()).add(str(a["ad_id"]).strip())  # canonical bare ID
        if a.get("advertiser_id"):
            st.indicators.setdefault("advertiser_id", set()).add(str(a["advertiser_id"]).strip())
        if a.get("advertiser"):
            st.indicators.setdefault("advertiser_name", set()).add(gazetteer.fold(a["advertiser"]))
    for d in meta.get("dns", []):
        batch = web.cert_batch(d)
        if batch:
            st.indicators.setdefault("cert_batch", set()).add(batch)

    # Non-CDN IPs (exact CIDR filtering) & accurate Cloudflare detection on landing host IPs
    landing_domains = {
        web.registrable_domain(u) for u in st.landing_urls
        if u and u.startswith("http") and not web.is_generic(web.registrable_domain(u))
    }
    for rdom, rip in har_req_ips:
        if rdom in landing_domains:
            st.landing_ips.add(rip)
    for ip in st.ips:
        if not net.is_cdn_ip(ip):
            st.indicators.setdefault("ip", set()).add(ip)
    cf_check_ips = st.landing_ips if st.landing_ips else set(st.ips)
    st.behind_cloudflare = any(net.is_cloudflare_ip(ip) for ip in cf_check_ips)
    return st


# -------------------------------------------------------------------------------------- Stage 2: Visual & Faces
def _extract_ocr_ad_facts(img_feats: list[dict], ind: dict[str, set[str]], qr_urls: list[str]) -> None:
    """Extract ad-library IDs, advertiser names (tight vertical proximity), QR URLs, and decoy-filtered OCR domains."""
    for f in img_feats:
        lines = f.get("ocr_lines", [])
        for i, line in enumerate(lines):
            ft = gazetteer.fold(line.get("text", "")).strip()
            mm = re.search(r"identyfikator(?: biblioteki)?\W*(\d{10,20})", ft) or re.search(r"library id\W*(\d{10,20})", ft)
            if mm:
                ind.setdefault("ad_id", set()).add(mm.group(1))  # canonical bare ID
            # Tightened advertiser heuristic: standalone "Sponsorowane"/"Sponsored" directly below a short non-sentence name
            if _SPONSORED_LABEL_RX.fullmatch(ft) and i > 0:
                prev = lines[i - 1]
                cur_box = line.get("box") or [0, 0, 0, 0]
                prev_box = prev.get("box") or [0, 0, 0, 0]
                v_gap = cur_box[1] - prev_box[3]
                h_diff = abs(prev_box[0] - cur_box[0])
                raw_adv = (prev.get("text") or "").strip(" .·•")
                adv = gazetteer.fold(raw_adv).strip(" .·•")
                if (
                    -0.01 <= v_gap <= 0.035
                    and h_diff <= 0.10
                    and 3 <= len(adv) <= 35
                    and len(adv.split()) <= 4
                    and not adv.startswith(("http", "www"))
                    and not _SENTENCE_PUNCT_RX.search(raw_adv)
                ):
                    ind.setdefault("advertiser_name", set()).add(adv)

        for q in f.get("qr", []):
            qr_urls.append(q)
            if not web.is_decoy_or_generic_domain(web.registrable_domain(q)):
                web.merge_ind(ind, web.url_indicators(q))
        for u in vision.urls_in_text(f.get("ocr_text", "")):
            d = web.registrable_domain(u)
            if d and not web.is_decoy_or_generic_domain(d):
                ind.setdefault("ocr_domain", set()).add(d)


def _stage_visual_and_faces(m: Material, har_images: list[tuple[str, bytes]], say: Callable[[str], None]) -> VisualStage:
    st = VisualStage()
    sources: list[tuple[str, str]] = [(p, "screenshot") for p in m.images]
    for v in m.videos:
        vsha = hashlib.sha1(f"{v}{Path(v).stat().st_size}".encode()).hexdigest()[:12]
        say(f"video keyframes: {Path(v).name[:50]}")
        kfs = vision.video_keyframes(v, config.ARTIFACTS / m.id / vsha)
        st.videos.append({"file": Path(v).name, "keyframes": len(kfs)})
        sources.extend((str(k), "keyframe") for k in kfs)

    for src, kind in sources[: config.MAX_IMAGES_PER_MATERIAL]:
        im = vision.load_rgb(src)
        if im is None:
            continue
        if kind == "screenshot":
            st.file_shas.add(vision.file_sha(src)[:20])
        say(f"image ({kind}): {Path(src).name[:50]}")
        f, v = _image_features(im, str(src), kind)
        if is_ui_screenshot(f.get("ocr_text", "")):
            f["kind"] = "ui_screenshot"
        if "local" in v:
            f["local"][0] = sum(len(r) for r in st.local_rows)
            st.local_rows.append(v["local"])
        st.img_feats.append(f)
        st.face_vecs.extend(v.get("faces", []))

    # Deduplicate landing-page assets by SHA-256 BEFORE hashing and face detection
    raw_candidates: list[tuple[str, int, bytes | None]] = []
    for a in m.assets:
        try:
            sz = Path(a).stat().st_size
            if sz >= config.MIN_ASSET_BYTES:
                raw_candidates.append((a, sz, None))
        except OSError:
            continue
    for u, b in har_images:
        if len(b) >= config.MIN_ASSET_BYTES:
            raw_candidates.append((f"har:{u}", len(b), b))
    raw_candidates.sort(key=lambda t: -t[1])

    seen_asset_sha: set[str] = set()
    unique_assets: list[tuple[str, bytes | None]] = []
    for src, _, blob in raw_candidates:
        try:
            sha = vision.file_sha(blob if blob is not None else src)
        except OSError:
            continue
        if sha in seen_asset_sha:
            continue
        seen_asset_sha.add(sha)
        unique_assets.append((src, blob))
        if len(unique_assets) >= 60:
            break

    asset_hashes: set[str] = set()
    for i, (src, blob) in enumerate(unique_assets):
        im = vision.load_rgb(blob if blob is not None else src)
        if im is None or min(im.size) < config.MIN_ASSET_SIDE:
            continue
        asset_hashes.add(vision.hashes(im)["phash"])
        if i < 10:
            for fc in faces.faces_in_image(im):
                ident, sim = faces.identify(fc["embedding"])
                st.asset_faces.append({
                    "identity": ident, "sim": round(sim, 3), "det_score": fc["det_score"],
                    "src": "asset:" + Path(src).name[:60], "box_rel": fc["box_rel"], "side": fc["side"],
                })
                st.face_vecs.append(fc["embedding"])

    clean_hashes = {h for h in asset_hashes if h not in ("0000000000000000", "ffffffffffffffff", "8000000000000000")}
    if clean_hashes:
        st.indicators["asset_phash"] = clean_hashes

    _extract_ocr_ad_facts(st.img_feats, st.indicators, st.qr_urls)
    return st


# -------------------------------------------------------------------------------------- Stage 3: Text
def _stage_text(m: Material, web_s: WebStage, vis_s: VisualStage, meta: dict, say: Callable[[str], None]) -> TextStage:
    st = TextStage()
    st.ocr_text = " ".join(f.get("ocr_text", "") for f in vis_s.img_feats)
    st.meta_text = " ".join(
        f"{a.get('title') or ''} {a.get('description') or ''} {a.get('advertiser') or ''}"
        for a in meta.get("ad_library", [])
    )
    uniq_titles = list(dict.fromkeys(web_s.titles))
    all_text = (
        "\n".join(uniq_titles) + "\n" + "\n".join(m.texts) + "\n"
        + st.meta_text + "\n" + st.ocr_text + "\n" + "\n".join(web_s.page_texts)
    ).strip()
    page_text = ("\n".join(uniq_titles) + "\n" + "\n".join(web_s.page_texts)).strip()[:40000]
    narrative_text = page_text or all_text
    creative_text = (st.ocr_text + "\n" + "\n".join(m.texts) + "\n" + st.meta_text).strip()  # what the ad itself says

    st.text_summary = {
        "titles": uniq_titles[:10],
        "ocr_text": st.ocr_text[:4000],
        "excerpt": (" ".join(web_s.page_texts) or st.ocr_text or "\n".join(m.texts))[:1500],
        "n_chars": len(all_text),
        "keywords": text.keywords(narrative_text if len(narrative_text) > 200 else all_text),
        "amounts": text.amounts(all_text),
        "persons_text": gazetteer.find_persons(all_text),
        "brands_text": gazetteer.find_brands(all_text),
        "media_text": gazetteer.find_media(all_text),
        # entity-masked word 4-gram MinHash: landing-page text (view "text") and creative text (view "ocr")
        "minhash_masked": text.minhash_sig(page_text, masked=True) if page_text else None,
        "minhash_ocr_masked": text.minhash_sig(creative_text, masked=True) if creative_text else None,
        # language of each text; a pair in two different known languages is not compared word by word
        "lang": lang.language(page_text), "lang_ocr": lang.language(creative_text),
    }

    say("text embedding")
    embed_src = ("\n".join(uniq_titles) + "\n" + (" ".join(web_s.page_texts) or all_text))[:6000]
    tv = text.embed_text(embed_src)
    if tv is not None:
        st.text_vecs.append(tv)
    return st


# -------------------------------------------------------------------------------------- Stage 4: LLM
def _stage_llm(
    m: Material, web_s: WebStage, vis_s: VisualStage, meta: dict, use_llm: bool, say: Callable[[str], None],
) -> LlmStage:
    st = LlmStage()
    ocr_text = " ".join(f.get("ocr_text", "") for f in vis_s.img_feats)
    meta_text = " ".join(
        f"{a.get('title') or ''} {a.get('description') or ''} {a.get('advertiser') or ''}"
        for a in meta.get("ad_library", [])
    )
    landing_urls = list(dict.fromkeys(web_s.landing_urls + vis_s.qr_urls))
    llm_input = (
        f"TYTUŁY: {' | '.join(dict.fromkeys(web_s.titles))}\n"
        f"URL: {' '.join(landing_urls[:3])[:600]}\n"
        f"METADANE REKLAMY: {meta_text[:800]}\n"
        f"TEKST Z OBRAZÓW (OCR): {ocr_text[:2500]}\n"
        f"TEKST STRONY: {' '.join(web_s.page_texts)[:5000]}\n"
        f"INNE: {' '.join(m.texts)[:1500]}"
    )
    if use_llm:
        say("LLM attributes")
    attrs = llm.extract_attributes(llm_input, backend=None if use_llm else "none")
    st.attrs = attrs
    prod = attrs.get("product_or_platform_name")
    if prod and len(prod) > 2:
        st.indicators.setdefault("product", set()).add(gazetteer.fold(prod).strip())
    return st


# -------------------------------------------------------------------------------------- Stage 5: Enrich
def _stage_enrich(landing_urls: list[str], say: Callable[[str], None], enabled: bool) -> EnrichStage:
    st = EnrichStage()
    if not enabled:
        return st
    domains = [
        d for d in sorted({web.registrable_domain(u) for u in landing_urls if u.startswith("http")} - {""})[:6]
        if not web.is_generic(d)
    ]
    if not domains:
        return st
    say(f"enrich: {', '.join(domains)}")
    infos = enrich.enrich_domains(domains)
    for d in domains:
        info = infos.get(d)
        if not info:
            continue
        rdap_info = info.get("rdap") or {}
        dns_info = info.get("dns") or {}
        crt_info = info.get("crtsh") or {}
        ns_list = rdap_info.get("nameservers") or dns_info.get("NS") or []
        a_recs = dns_info.get("A") or []
        st.infra[d] = {
            "registrar": rdap_info.get("registrar"),
            "created": rdap_info.get("created"),
            "nameservers": ns_list or None,
            "A": a_recs or None,
            "n_certs": crt_info.get("n_certs"),
            "first_cert": crt_info.get("first_cert"),
            "cert_pl_listed": info.get("cert_pl_listed"),
        }
        if any(net.is_cloudflare_ip(ip) for ip in a_recs) or any(str(ns).lower().endswith(".cloudflare.com") for ns in ns_list):
            st.behind_cloudflare = True
    return st


# -------------------------------------------------------------------------------------- Stage 6: Assemble
def _assemble_features(
    m: Material,
    meta: dict,
    web_s: WebStage,
    vis_s: VisualStage,
    text_s: TextStage,
    llm_s: LlmStage,
    enr_s: EnrichStage,
    elapsed_s: float,
) -> tuple[dict, dict]:
    ind: dict[str, set[str]] = {}
    for part in (web_s.indicators, vis_s.indicators, llm_s.indicators):
        web.merge_ind(ind, part)

    all_faces = [fc for f in vis_s.img_feats for fc in f.get("faces", [])] + vis_s.asset_faces
    landing_urls = [u for u in dict.fromkeys(web_s.landing_urls + vis_s.qr_urls) if u.startswith("http")]
    landing_domains = sorted({
        web.registrable_domain(u) for u in landing_urls
        if web.registrable_domain(u) and not web.is_generic(web.registrable_domain(u))
    })

    feats: dict = {
        "material_id": m.id,
        "name": m.name,
        "source": m.source,
        "notes": list(m.notes) + web_s.notes,
        "n_pages": len(m.pages),
        "n_images": len(m.images),
        "n_videos": len(m.videos),
        "behind_cloudflare": web_s.behind_cloudflare or enr_s.behind_cloudflare,
        "text": text_s.text_summary,
        "llm": llm_s.attrs,
        "faces": all_faces,
        "persons_visual": sorted({f["identity"] for f in all_faces if f["identity"]}),
        "persons_named": sorted(
            set(text_s.text_summary.get("persons_text", [])) | set(llm_s.attrs.get("impersonated_persons") or [])
        ),
        "infra": enr_s.infra,
        "web": {
            "landing_urls": landing_urls[:10],
            "landing_domains": landing_domains,
            "redirect_chains": [c for c in web_s.chains if len(c) > 1][:5],
            "ips": sorted(web_s.ips, key=lambda k: -web_s.ips[k])[:15],
            "server_headers": sorted(web_s.server_hdrs, key=lambda k: -web_s.server_hdrs[k])[:10],
            "pages": web_s.page_info,
        },
        "images": [{k: v for k, v in f.items() if k != "ocr_lines"} for f in vis_s.img_feats],
        "meta": meta,
        "dates": _dates(m, meta),
        "file_shas": sorted(web_s.file_shas | vis_s.file_shas),
        "indicators": {k: sorted(v) for k, v in ind.items() if v},
        "elapsed_s": round(elapsed_s, 1),
    }
    if vis_s.videos:
        feats["videos"] = vis_s.videos

    raw_vecs: dict[str, list] = {"faces": vis_s.face_vecs, "text": text_s.text_vecs, "dom": web_s.dom_sigs,
                                 "css": web_s.css_sigs, "js": web_s.js_sigs}
    vectors = {k: (np.stack(v) if len(v) and not isinstance(v[0], list) else v) for k, v in raw_vecs.items()}
    if vis_s.local_rows:
        vectors["local"] = np.concatenate(vis_s.local_rows)      # ORB keypoints of the creatives, rows indexed by images[].local
    return feats, vectors


# -------------------------------------------------------------------------------------- Entrypoint
def analyze(
    m: Material,
    use_llm: bool = True,
    progress=None,
    enrich_online: bool | None = None,
) -> tuple[dict, dict]:
    """Run the 6-stage feature-extraction pipeline on one Material."""
    t0 = time.time()
    say = progress or (lambda s: log.info(s))
    meta = read_meta(m)

    web_s = _stage_web(m, meta, say)
    vis_s = _stage_visual_and_faces(m, web_s.har_images, say)
    text_s = _stage_text(m, web_s, vis_s, meta, say)
    llm_s = _stage_llm(m, web_s, vis_s, meta, use_llm, say)
    do_enrich = enrich.is_enabled() if enrich_online is None else bool(enrich_online)
    enr_s = _stage_enrich(web_s.landing_urls + vis_s.qr_urls, say, enabled=do_enrich)

    return _assemble_features(m, meta, web_s, vis_s, text_s, llm_s, enr_s, time.time() - t0)
