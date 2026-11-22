# FakerAlpha — Features, Similarity & Clustering

> How FakerAlpha turns a material (ad, landing page, screenshot, video, HAR, text lead) into features, compares two
> materials, groups them into campaigns and families, and assigns a new material (open set).
> Code: `ftf/config.py`, `ftf/pipeline.py`, `ftf/web.py`, `ftf/vision.py`, `ftf/faces.py`, `ftf/text.py`,
> `ftf/gazetteer.py`, `ftf/llm.py`, `ftf/similarity.py`, `ftf/cluster.py`.
>
> See also: [`PIPELINE_WALKTHROUGH.md`](PIPELINE_WALKTHROUGH.md) · [`WEB_FETCHING_METHODOLOGY.md`](WEB_FETCHING_METHODOLOGY.md) · [`METHODOLOGY.md`](METHODOLOGY.md) (PL)

**Principle.** Two kinds of evidence, nothing else:

* **identifiers** — exact values an operator reuses (a tracking pixel, a domain, a backend API path). One shared,
  non-trivial identifier links two materials (deterministic record linkage [1]);
* **content views** — seven graded similarities in [0, 1], each a standard, citable measure, averaged with equal
  weight over the views available on both sides (Gower [12]).

Everything else we extract (persons, scam type, registrar, keywords, …) is shown to the analyst but **never used for
linking**, because on our labelled data it is shared across different campaigns. The whole method has five tuned
constants (`MAX_DF`, `PHASH_HAMMING`, `DUPLICATE_CUT`, `CAMPAIGN_CUT`, `FAMILY_CUT`) plus face-detection and
extraction limits. All models run on CPU via ONNX Runtime.

---

## 1. Features

### 1.1 Identifiers (exact match → must-link)

Raw indicator types are mapped to groups by `config.IDENTIFIER_GROUP`:

| Group | Raw indicator types | Where it comes from |
|---|---|---|
| `ad_library` | `ad_id`, `advertiser_id` | yt-dlp `.info.json`, ad-library URL, OCR of "Identyfikator biblioteki" |
| `domains` | `landing_domain`, `redirect_domain`, `page_host`, `ocr_domain`, `tds_host` | URLs, redirect chain in HAR, `saved from url=`, domains read from the creative (OCR/QR). Reduced to the registrable domain (PSL); OCR/QR domains must pass `web.is_decoy_or_generic_domain` |
| `certificates` | `cert_batch` | issuance minute of the host's TLS certificate (`dns_ssl.json`: `tls_valid_from`), emitted only when every name on the certificate (`tls_san`) lies under the host's registrable domain. Certificates requested in one batch start in the same minute; shared certificates of hosting platforms (`*.pages.dev`) are excluded by the name rule |
| `tracking_ids` | `fb_pixel`, `tiktok_pixel`, `ga`, `gtm`, `gads`, `tenant_uuid`, `affiliate`, `adset`, `campaign_param` | HTML, HAR bodies, saved scripts, URL parameters. Canonicalised to bare IDs; per-visit session UUIDs are removed from `tenant_uuid` |
| `contacts` | `phone`, `email`, `telegram`, `whatsapp`, `wallet` | page text and HTML |
| `kit_files` | `script_hash`, `api_template`, `form_endpoint`, `path_template` | first-party script SHA-1 (generic libraries filtered); POST/form paths with IDs templated, e.g. `POST /api/v1/trigger/field/{id}/` |
| `product` | `product` | `product_or_platform_name` from the LLM (or rule fallback), normalised (e.g. "Orzeł Fundaris") |

Plus `file_sha` (SHA-256 of a saved page or screenshot) → **duplicate**; an identical file is also treated as a
must-link (`p = 1`), since one file cannot belong to two campaigns.

Values are compared within a group, so e.g. a domain read from a creative (`ocr_domain`) matches the
`landing_domain` of another material.

**Too-common values.** A shared value counts only if its document frequency satisfies `df/N ≤ config.MAX_DF`
(= 0.5) or it is held by just the two compared materials (`df ≤ 2`) — the IDF intuition that a term present in most documents does not discriminate [3]. Ignored values stay in the
explanation ("w X z N materiałów, zbyt popularne"), so the analyst sees what was skipped.

Why these: shared analytics/pixel IDs reveal common operators across otherwise unrelated sites [2]; phishing kits are
reused and identifiable by their files and endpoints [4]. On our 10 labelled materials no identifier value is shared
between different campaigns.

### 1.2 Content views (graded similarity, `similarity.VIEWS = ("text", "ocr", "semantic", "html", "css", "js", "images")`)

| View | Representation | Similarity `sim_v(a,b)` |
|---|---|---|
| `text` | MinHash signature (word 4-gram shingles) of the **landing-page text** (titles + HTML text), **entity-masked** (`gazetteer.mask_entities` replaces person names with `<per>`); field `text.minhash_masked` | estimated Jaccard of the shingle sets [5, 6] |
| `ocr` | the same signature of the **creative text**: OCR of screenshots / video keyframes (+ ad copy supplied as text and ad-library metadata), entity-masked; field `text.minhash_ocr_masked`. For materials stored before this field existed it is computed from the stored `text.ocr_text` (no re-ingest) | estimated Jaccard [5, 6] |
| `semantic` | multilingual-e5-small embedding [7] of the material text (stored vector kind `"text"`) | cosine after subtracting the plain corpus mean (Mu & Viswanath [8]), clipped to [0, 1]; raw cosine if the corpus has < 3 materials |
| `html` | MinHash of HTML tag-sequence 5-gram shingles (vector kind `"dom"`), one per page | estimated Jaccard [6, 9]; max over page pairs |
| `css` | MinHash of the page's set of CSS class names (`web.class_vocabulary`, vector kind `"css"`): generated parts (numbers, hex digests, CSS-in-JS suffixes) are masked; a page needs ≥ `MIN_CLASS_NAMES` (= 10) names | estimated Jaccard [6]; max over page pairs |
| `js` | MinHash of token 5-grams of the page's own inline scripts (`web.script_shingles`, vector kind `"js"`): comments dropped, strings → `S`, numbers → `0`, identifiers kept; snippets of public services (analytics, consent, CDN) skipped; ≥ `MIN_SCRIPT_SHINGLES` (= 30) 5-grams | estimated Jaccard [6]; max over page pairs |
| `images` | set of 64-bit pHashes [10] of the material's images: non-UI creatives (screenshots, video keyframes) + landing-page images (`asset_phash`) | overlap = number of images of the smaller set that have a match at Hamming ≤ `config.PHASH_HAMMING` (= 4) in the other set, divided by `min(|A|, |B|)` (containment of the smaller set [6]) |

A view is **available** for a pair only if both materials have that representation (missing page, no text, no
images → view skipped, never scored as 0). Keeping `text` and `ocr` apart means a creative-only variant (dead page)
is compared OCR-to-OCR, never OCR-to-page-text.

**Language rule.** `text` and `ocr` compare words, so a translated copy of a page scores 0 on them by construction.
When both texts have a known and different language (`ftf/lang.py`: stop words of 21 languages plus non-Latin
scripts; short text → unknown), the two views are unavailable for the pair. Without the rule a kit translated for
several markets split into one campaign per language.

**Cropped and rescaled images.** A pHash describes the whole picture, so a crop changes it completely. Creative
images without a pHash match are compared by ORB keypoints (ratio test, RANSAC affine fit): a match needs
≥ `LOCAL_MIN_INLIERS` (= 40) inliers spanning ≥ `LOCAL_MIN_EXTENT` (= 3 %) of one image. In stores larger than
`LOCAL_GATE_ABOVE` (= 300) materials the test runs only for pairs that a full image match could bring within
`CAMPAIGN_CUT`. Measurements: `research/experiments/`.

Why masking: "same article, celebrity swapped" variants share the masked text. Why centring: raw e5 cosines between
unrelated Polish scam pages are very high (embedding anisotropy [8]); subtracting the corpus mean restores range.

### 1.3 Descriptive only (displayed, never used for linking)

| Feature | Source | Why not a linking signal |
|---|---|---|
| persons | ArcFace [11] match against a 29-person reference gallery (SCRFD detection [11]; a face is used if detector score ≥ `FACE_DET_THRESHOLD` and face side ≥ `FACE_MIN_SIDE`, identity if cosine ≥ `FACE_MATCH_THRESHOLD`) + gazetteer names in text | the same celebrities appear in many independent campaigns (hubs) |
| `scam_type` | LLM / rules (closed enum) | shared across campaigns in the labelled data |
| keywords | most frequent words and two-word phrases (`text.keywords`) | topical, not operator-specific |
| amounts | regex (`zł`, `PLN`, `EUR`) | context |
| registrar, creation date, nameservers, IP, CERT Polska listing | RDAP, DNS, crt.sh, CERT PL list | registrar shared across campaigns; useful context for the analyst |
| `advertiser_name`, spoofed media outlet, brands | OCR, LLM, gazetteer | context; names are not unique |

**Extraction notes** (robustness to format differences): video keyframes skip black padding frames; portrait feed
screenshots are cropped to the creative; ad-library UI screenshots are recognised by OCR and excluded from `images`
(they still give OCR, `ad_id`, advertiser); text is NFKC-folded with diacritics and zero-width characters removed;
e5 embeds up to three windows (lead / middle / end) of long pages; CDN IPs are filtered. Details per stage:
[`PIPELINE_WALKTHROUGH.md`](PIPELINE_WALKTHROUGH.md).

The LLM schema is reduced to `scam_type`, `impersonated_persons`, `impersonated_brands`, `spoofed_media_outlet`,
`product_or_platform_name` (plus `summary_pl` for the UI). Only `product_or_platform_name` feeds linking.

---

## 2. Similarity

1. **Must-link.** Two materials are linked if they share ≥ 1 counted identifier (§ 1.1). Links are closed
   transitively with union-find → must-link components [1, 2].
2. **Content distance** (Gower's general coefficient over the available views [12]):

   ```
   d(a,b) = 1 − (1/k) · Σ_{v ∈ V(a,b)} sim_v(a,b),     V(a,b) = views available on both, k = |V(a,b)|
   ```
   If `k = 0`: `d = 1.0` and `comparable = False` (incomplete data never creates a link).
3. **Clustering distance**: `D(a,b) = 0` if `a` and `b` are in the same must-link component, else `d(a,b)`.

No weights, no priors: each available view contributes exactly `sim_v / k`.

## 3. Clustering

* **Algorithm**: agglomerative clustering with **average linkage** (UPGMA) on `D`, `scipy.cluster.hierarchy` [13].
  The distance between two clusters is the mean `D` over all cross pairs, so one accidental high similarity does not
  chain clusters together (unlike single linkage). Must-link components merge first (at height 0) and are never split by a cut.
* **Campaigns** = `fcluster` of the dendrogram at `config.CAMPAIGN_CUT` (= 0.6).
* **Families** (groups of similar campaigns) = `fcluster` of the **same dendrogram** at `config.FAMILY_CUT` (= 0.93).
  Families are reported separately: "similar content, no shared operator trace".
* **Duplicates**: shared `file_sha` or `ad_id`, or `d ≤ config.DUPLICATE_CUT` (= 0.05); grouped with union-find.
* **Pair relation** (`Link.relation`): `duplicate` | `same_campaign` (shared identifier or `d ≤ CAMPAIGN_CUT`) |
  `similar` (`d ≤ FAMILY_CUT`) | `none`. Campaign membership comes from the dendrogram, so two members of one campaign
  may be connected only through other members.
* **Baseline**: HDBSCAN [14] on the same `D` (`metric="precomputed"`), shown in the UI for comparison.

`cluster.build()` returns `links`, `duplicates`, `campaigns`, `campaign_of`, `families`, `family_of`, `hdbscan`
(+ campaign profiles).

## 4. Open-set assignment of a new material (`cluster.assign`)

Batch clustering answers "which materials form a group" (average linkage). Assignment answers a different
question — "is this a variant of a material we already know?" — so it uses the **nearest neighbour** (1-NN, Cover &
Hart [18]) with a rejection threshold (open set [15]). A campaign mean would penalise a variant of a campaign that is
held together only by identifiers while its members' content differs.

1. shares a counted identifier with members of exactly one campaign → `known_campaign`; with ≥ 2 campaigns →
   `merge_proposal`;
2. otherwise take the nearest known material `m*` by content distance `d`:
   * `d ≤ CAMPAIGN_CUT` → `known_campaign` (campaign of `m*`);
   * else → `new_campaign`, reporting `nearest` = campaign, distance and material (id, name); if `d ≤ FAMILY_CUT`,
     also `similar_family` (campaign of `m*`);
3. any duplicate link (shared file, shared `ad_id`, or `d ≤ DUPLICATE_CUT`) turns the decision into `duplicate`,
   except for a `merge_proposal`.

The result includes the most similar materials with their `Link` explanations.

## 5. Explaining a link

Every pair is a `Link` (`ftf/similarity.py`):

| Field | Meaning |
|---|---|
| `a`, `b` | material IDs |
| `distance` | content (Gower) distance `d(a,b)` |
| `p` | clustering similarity `1 − D(a,b)` for the direct pair: 1.0 if a counted identifier is shared, else `1 − distance` |
| `relation` | `duplicate` / `same_campaign` / `similar` / `none` |
| `shared_ids` | list of `SharedId(group, type, value, df, ignored)` |
| `views` | available view similarities, e.g. `{"text": …, "html": …}` |
| `comparable` | at least one view available on both sides |
| `same_file` | identical input file (SHA-256) in both materials |

`Link.explain()` renders a short Polish text: the shared identifier values with `df/N` (and the ignored, too-common
ones), then the per-view similarities. Because `d` is a plain mean, the analyst can recompute it by hand.

---

## 6. What was removed and why

The previous version had ~50 signals and 92 hand-set constants. Checked against 10 own-labelled materials
(`data/labels_dane.csv`, campaigns A–F):

| Removed | Evidence / reason |
|---|---|
| CLIP and DINOv2 creative embeddings; graded creative pHash similarity | no separation: different-campaign pairs scored ≥ same-campaign pairs. Only exact image reuse (pHash at Hamming ≤ 4) is kept, in `images` |
| persons as evidence (gallery identity, unknown-face matching, same-face-image), LLM categories (`scam_type`, narrative template, creative format), registrar / NS / IP / registration-burst signals | shared across different campaigns (hubs) → descriptive only |
| LLM phrases and extra LLM fields; iterative LLM attribute refinement (`tools/llm_refine.py`, `llm_extra_*`) | refinement proposed attributes from the very clusters it was meant to separate (circular, transductive); phrases duplicate the `text` view |
| second text embedding (EmbeddingGemma-2) | redundant with the `semantic` view; ~4–6× slower on CPU |
| separate raw / masked / OCR MinHash fused by max; title template | two masked signatures kept as separate views (`text` = page, `ocr` = creative), no max-fusion |
| TDS parameter-shape signature, build ID, favicon, script/CSS names, form-field lists, minor trackers (Sentry, reCAPTCHA, Clarity, Hotjar, Yandex Metrika, AdSense) | redundant with stronger identifiers in the same material or of unclear operator specificity |
| scoring machinery: S/M/W tiers, per-type prior weights, ramps, rarity formula, hub predicate, noisy-OR fusion, weak-only cap, conflict penalty, playbook score, message-variant sub-level, inverse-density centring, candidate blocking, `candidate_review` decision, face-quality product formula and gallery margin guard | hand-set constants that were never fitted to data. Replaced by must-link + Gower mean + average linkage, 1-NN assignment with a threshold, `MAX_DF` (one IDF threshold) and plain mean centring |

On the same labels the simplified method reproduces the reference grouping: ARI = 1.00 for any `CAMPAIGN_CUT` in
[0.05, 0.90] (see [`RESULTS.md`](RESULTS.md)).

## 7. Evaluation protocol and limitations

```bash
.venv/bin/python -m unittest discover tests                      # unit + real-data regression tests (or pytest)
.venv/bin/python tools/evaluate.py --labels data/labels_dane.csv --no-llm # leave-one-out + synthetic variants + metrics
.venv/bin/python -m ftf.cli eval data/labels_dane.csv            # metrics only
```

1. **Leave-one-out**: remove each material, rebuild, `cluster.assign` it back → returns to its campaign, or is
   recognised as `new_campaign` if it was a singleton.
2. **Synthetic variants** ("new variants of known campaigns"): creative only (dead page), landing page only, cropped
   and recompressed screenshot, swapped domain with URL IDs removed, swapped celebrity name → expected
   `known_campaign`.
3. **Unrelated materials** → expected `new_campaign`.
4. **With labels**: ARI [16] and B-cubed precision/recall [17] against the labels, and against the HDBSCAN baseline;
   pairwise precision/recall/F1 from the same pair-counting table as ARI.

**Limitations (honest caveats)**

* 10 materials with **our own** labels — results are a sanity check, not a benchmark.
* **Must-link chaining**: one wrong or shared-by-accident identifier merges two campaigns. Mitigated by `MAX_DF`
  and by always showing the identifier value and its `df/N` to the analyst.
* `product` depends on LLM extraction (normalised name; rule fallback without LLM).
* No visual embeddings any more: a **redrawn** creative (same campaign, new graphics) is not matched visually; only
  exact image reuse, text, HTML and identifiers link it.
* Equal view weights and the cuts are design choices, not fitted values; the cuts are checked for stability on the
  labelled data (`RESULTS.md`).
* Missing views reduce `k`; a material with no comparable view and no identifier stays a singleton (`d = 1.0`).

---

## 8. References

1. Christen, P. *Data Matching*. Springer, 2012. <https://doi.org/10.1007/978-3-642-31164-2>
2. Starov, O. et al. *Betrayed by Your Dashboard: Discovering Malicious Campaigns via Web Analytics*. WWW 2018. <https://doi.org/10.1145/3178876.3186089>
3. Spärck Jones, K. *A statistical interpretation of term specificity and its application in retrieval*. J. Documentation, 1972. <https://doi.org/10.1108/eb026526>
4. Bijmans, H. et al. *Catching Phishers By Their Bait: Investigating the Dutch Phishing Landscape through Phishing Kit Detection*. USENIX Security 2021. <https://www.usenix.org/conference/usenixsecurity21/presentation/bijmans>
5. Jaccard, P. *The distribution of the flora in the alpine zone*. New Phytologist, 1912. <https://doi.org/10.1111/j.1469-8137.1912.tb05611.x>
6. Broder, A. Z. *On the resemblance and containment of documents*. SEQUENCES 1997. <https://doi.org/10.1109/SEQUEN.1997.666900>
7. Wang, L. et al. *Multilingual E5 Text Embeddings: A Technical Report*. 2024. <https://arxiv.org/abs/2402.05672>
8. Mu, J., Viswanath, P. *All-but-the-Top: Simple and Effective Postprocessing for Word Representations*. ICLR 2018. <https://arxiv.org/abs/1702.01417>
9. Cui, Q. et al. *Tracking Phishing Attacks Over Time*. WWW 2017. <https://doi.org/10.1145/3038912.3052654>
10. Zauner, C. *Implementation and Benchmarking of Perceptual Image Hash Functions*. 2010. <https://phash.org/docs/pubs/thesis_zauner.pdf>
11. Deng, J. et al. *ArcFace: Additive Angular Margin Loss for Deep Face Recognition*. CVPR 2019. <https://arxiv.org/abs/1801.07698> · Guo, J. et al. *Sample and Computation Redistribution for Efficient Face Detection* (SCRFD). <https://arxiv.org/abs/2105.04714>
12. Gower, J. C. *A general coefficient of similarity and some of its properties*. Biometrics, 1971. <https://doi.org/10.2307/2528823>
13. Müllner, D. *Modern hierarchical, agglomerative clustering algorithms*. 2011. <https://arxiv.org/abs/1109.2378>
14. Campello, R. J. G. B. et al. *Density-Based Clustering Based on Hierarchical Density Estimates* (HDBSCAN). PAKDD 2013. <https://doi.org/10.1007/978-3-642-37456-2_14>
15. Bendale, A., Boult, T. *Towards Open World Recognition*. CVPR 2015. <https://arxiv.org/abs/1412.5687>
16. Hubert, L., Arabie, P. *Comparing partitions* (ARI). J. Classification, 1985. <https://doi.org/10.1007/BF01908075>
17. Amigó, E. et al. *A comparison of extrinsic clustering evaluation metrics based on formal constraints* (B-cubed). Information Retrieval, 2009. <https://doi.org/10.1007/s10791-008-9066-8>
18. Cover, T., Hart, P. *Nearest neighbor pattern classification*. IEEE Trans. Inf. Theory 13(1):21–27, 1967. <https://doi.org/10.1109/TIT.1967.1053964>
