"""Central configuration: paths, model locations, evidence weights and thresholds.

All weights are *priors* (probability that two materials sharing this signal belong to the same
campaign when the shared value is rare). They are discounted by value rarity in `similarity.py`.
Rationale for each weight is documented in docs/METHODOLOGY.md (sections 4-5).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("FTF_ROOT", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"
MODELS = ROOT / "models"
CACHE = DATA / "cache"
STORE_PATH = Path(os.environ.get("FTF_STORE", DATA / "store" / "ftf.sqlite"))
ARTIFACTS = DATA / "artifacts"          # extracted frames, crops, captures
REFERENCE_FACES = DATA / "reference_faces"
EXPORTS = DATA / "exports"

for _p in (CACHE, ARTIFACTS, EXPORTS, STORE_PATH.parent):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- feature extraction limits
MAX_IMAGES_PER_MATERIAL = 40       # screenshots + keyframes + page assets considered for embeddings
MAX_VIDEO_KEYFRAMES = 8
MIN_ASSET_BYTES = 6_000            # ignore icons/spacers when hashing page assets
MIN_ASSET_SIDE = 120

# ---------------------------------------------------------------- LLM
LLM_BACKEND = os.environ.get("FTF_LLM", "auto")         # auto | claude_cli | gemini | none
LLM_MODEL = os.environ.get("FTF_LLM_MODEL", "haiku")
LLM_TIMEOUT = int(os.environ.get("FTF_LLM_TIMEOUT", "120"))
USE_GEMMA = os.environ.get("FTF_GEMMA", "0") == "1"   # EmbeddingGemma-2 as 2nd narrative embedding

# ---------------------------------------------------------------- similarity: evidence families
# tier S = operator-level (near-certain same operator), M = kit/creative level, W = weak/context
FAMILY_TIER = {
    "duplicate": "S",
    "infra_ids": "S",      # pixel / analytics / ad-account IDs, contacts, form endpoints, wallets
    "tracking": "S",       # TDS / landing-builder tenant IDs, campaign/affiliate IDs in URLs
    "domain": "S",         # same landing registrable domain
    "kit": "M",            # first-party script/css names, DOM template, favicon, URL param signature
    "assets": "M",         # identical images re-used on landing pages
    "visual": "M",         # creative look (CLIP / DINOv2 / pHash)
    "narrative": "M",      # text near-duplicate / semantic narrative / title template
    "persons": "W",        # same recognised person (celebrity alone is weak)
    "concept": "W",        # LLM-derived scam type, narrative template, product
    "advertiser": "S",     # same ad-library advertiser / page ID
    "hosting": "W",        # same non-CDN IP / ASN
}

# prior weight of a single shared *indicator* value (before rarity discount)
INDICATOR_WEIGHT = {
    "fb_pixel": 0.92, "tiktok_pixel": 0.9, "ga": 0.9, "gtm": 0.88, "gads": 0.88, "ym": 0.9,
    "clarity": 0.88, "hotjar": 0.85, "sentry_key": 0.85, "recaptcha": 0.8, "adsense": 0.85,
    "phone": 0.9, "email": 0.85, "telegram": 0.9, "whatsapp": 0.9, "wallet": 0.95,
    "form_endpoint": 0.9, "ad_id": 0.95, "adset": 0.85, "affiliate": 0.85, "tds_host": 0.8,
    "tenant_uuid": 0.9, "campaign_param": 0.6, "build_id": 0.75,
    "landing_domain": 0.9, "redirect_domain": 0.75, "page_host": 0.6,
    "script_name": 0.55, "script_hash": 0.65, "css_name": 0.45, "favicon": 0.5,
    "param_signature": 0.45, "path_template": 0.5, "api_template": 0.65, "ocr_domain": 0.85,
    "asset_phash": 0.7, "advertiser_id": 0.95, "advertiser_name": 0.8,
    "ip": 0.45, "ns_pair": 0.35, "reg_burst": 0.75, "product": 0.75, "platform_name": 0.85, "phrase": 0.55,
}
INDICATOR_FAMILY = {
    "fb_pixel": "infra_ids", "tiktok_pixel": "infra_ids", "ga": "infra_ids", "gtm": "infra_ids",
    "gads": "infra_ids", "ym": "infra_ids", "clarity": "infra_ids", "hotjar": "infra_ids",
    "sentry_key": "infra_ids", "recaptcha": "infra_ids", "adsense": "infra_ids",
    "phone": "infra_ids", "email": "infra_ids", "telegram": "infra_ids", "whatsapp": "infra_ids",
    "wallet": "infra_ids", "form_endpoint": "infra_ids",
    "ad_id": "tracking", "adset": "tracking", "affiliate": "tracking", "tds_host": "tracking",
    "tenant_uuid": "tracking", "campaign_param": "tracking", "build_id": "kit",
    "landing_domain": "domain", "redirect_domain": "domain", "page_host": "domain",
    "script_name": "kit", "script_hash": "kit", "css_name": "kit", "favicon": "kit",
    "param_signature": "kit", "path_template": "kit", "api_template": "kit", "ocr_domain": "domain",
    "asset_phash": "assets", "advertiser_id": "advertiser", "advertiser_name": "advertiser",
    "ip": "hosting", "ns_pair": "hosting", "reg_burst": "domain", "product": "concept", "platform_name": "concept", "phrase": "narrative",
}

# values shared by more than this fraction of materials are treated as hubs (ignored)
HUB_FRACTION = 0.5
HUB_MIN_COUNT = 6

# continuous similarity -> evidence (piecewise linear between lo and hi, scaled by max weight)
CONTINUOUS = {
    #  name              (lo,   hi,   max_weight, family)
    "text_minhash":      (0.30, 0.80, 0.85, "narrative"),
    "masked_minhash":    (0.35, 0.80, 0.75, "narrative"),
    "title_template":    (0.80, 0.97, 0.70, "narrative"),
    "text_embedding":    (0.45, 0.85, 0.55, "narrative"),   # centred cosine
    "clip":              (0.55, 0.85, 0.60, "visual"),      # centred cosine
    "dinov2":            (0.55, 0.85, 0.55, "visual"),      # centred cosine
    "phash":             (0.80, 0.97, 0.80, "visual"),   # 1 - hamming/64
    "dom_template":      (0.45, 0.90, 0.60, "kit"),
    "face_unknown":      (0.45, 0.65, 0.60, "persons"),   # same non-reference face (recurring persona)
}
PERSON_REF_WEIGHT = 0.30      # same *famous* person: weak alone (celebrities are hubs by nature)
CONCEPT_WEIGHTS = {"scam_type": 0.15, "narrative_template": 0.30, "creative_format": 0.15}

WEAK_ONLY_CAP = 0.45          # link probability cap when no S/M family contributed
LINK_THRESHOLD = 0.55         # edge counts as "same campaign"
SIMILAR_THRESHOLD = 0.30      # edge counts as "similar / same playbook"
DUPLICATE_THRESHOLD = 0.97
ASSIGN_THRESHOLD = 0.55       # new material -> existing campaign
CANDIDATE_THRESHOLD = 0.40    # below this (or weak-only evidence) -> new campaign (open-set)
FACE_MATCH_THRESHOLD = 0.42   # ArcFace cosine vs reference gallery
FACE_DET_THRESHOLD = 0.6
