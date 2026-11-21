"""Central configuration: paths, model locations, extraction limits and the five linking constants.

Method (docs/METHODOLOGY.md): exact shared identifiers -> must-link (Christen 2012), filtered by document
frequency (Spärck Jones 1972); four content views -> Gower (1971) distance; average-linkage clustering
(Müllner 2011) cut at CAMPAIGN_CUT (campaigns) and FAMILY_CUT (families); open-set assignment by nearest
campaign mean with a rejection threshold (Bendale & Boult 2015).
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
MAX_IMAGES_PER_MATERIAL = 40       # screenshots + keyframes considered per material
MAX_VIDEO_KEYFRAMES = 8
MIN_ASSET_BYTES = 6_000            # ignore icons/spacers when hashing page assets
MIN_ASSET_SIDE = 120

# ---------------------------------------------------------------- LLM
LLM_BACKEND = os.environ.get("FTF_LLM", "auto")         # auto | claude_cli | gemini | none
LLM_MODEL = os.environ.get("FTF_LLM_MODEL", "haiku")
LLM_TIMEOUT = int(os.environ.get("FTF_LLM_TIMEOUT", "120"))

# ---------------------------------------------------------------- linking (docs/METHODOLOGY.md)
# A. Identifiers: a shared exact value is a must-link (deterministic record linkage, Christen 2012;
#    shared analytics IDs reveal campaigns, Starov et al. 2018). Raw indicator type -> group.
IDENTIFIER_GROUP = {
    "ad_id": "ad_library", "advertiser_id": "ad_library",
    "landing_domain": "domains", "redirect_domain": "domains", "page_host": "domains", "ocr_domain": "domains",
    "tds_host": "domains",
    "fb_pixel": "tracking_ids", "tiktok_pixel": "tracking_ids", "ga": "tracking_ids", "gtm": "tracking_ids",
    "gads": "tracking_ids", "tenant_uuid": "tracking_ids", "affiliate": "tracking_ids", "adset": "tracking_ids",
    "campaign_param": "tracking_ids",
    "phone": "contacts", "email": "contacts", "telegram": "contacts", "whatsapp": "contacts", "wallet": "contacts",
    "script_hash": "kit_files", "api_template": "kit_files", "form_endpoint": "kit_files", "path_template": "kit_files",
    "product": "product",
}
MAX_DF = 0.5            # a shared value counts only if held by <= 50 % of materials (IDF idea, Spärck Jones 1972)

# B. Content views -> Gower (1971) distance d = 1 - mean(available view similarities).
PHASH_HAMMING = 4       # two images match when their 64-bit pHashes differ in <= 4 bits (Zauner 2010)

# C. Clustering: average linkage (UPGMA) on D (0 inside a must-link component, else d); fcluster cuts.
DUPLICATE_CUT = 0.05    # d <= this -> duplicate
CAMPAIGN_CUT = 0.6      # dendrogram cut -> campaigns; also the open-set rejection threshold (assign)
FAMILY_CUT = 0.93       # dendrogram cut -> families (groups of content-similar campaigns)

# ---------------------------------------------------------------- faces (SCRFD detection + ArcFace gallery match)
FACE_DET_THRESHOLD = 0.6      # SCRFD detector score
FACE_MIN_SIDE = 48            # px; smaller faces are not embedded
FACE_MATCH_THRESHOLD = 0.42   # ArcFace cosine vs reference gallery (top-1)
