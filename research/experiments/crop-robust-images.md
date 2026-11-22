# Crop-robust image match (`exp/crop-robust-images`)

**Verdict: ADOPT the keypoint match, with a candidate gate before it is used on more than a few hundred materials.**
The "recompressed" variant test goes from 1/7 to 6/7, nothing else in the variant suite changes, and no pair of
different pictures was accepted in 16,914 negative pairs. Character n-grams for the `ocr` view are PROMISING and left
switched off.

This branch changes product code (`ftf/`). Numbers: `research/experiments/crop-robust-images.json`.

## Problem

The `images` view compares 64-bit pHashes (match at Hamming ≤ 4). A pHash describes the whole picture, so a crop
changes it completely. `docs/RESULTS.md` records the result: a screenshot cropped 8 % on each side, scaled ×0.6 and
saved as JPEG q=55 is recognised as its own campaign in 1 of 7 cases. A scammer who re-uploads a creative with a
different crop gets a new campaign.

## Method

Two images match when their pHashes match **or**, failing that, when a keypoint test passes:

1. ORB keypoints (up to 1,000) on the image scaled to 640 px on the long side.
2. Nearest-neighbour matching with the ratio test (0.75).
3. RANSAC fit of one affine transform (4 px tolerance); mirrored fits and scales outside 0.2–5 are rejected.
4. Match if the fit has **≥ 40 inliers** and the inliers' bounding box (middle 90 % in x and y) covers **≥ 3 %** of
   the area of one of the two images.

The view is still the overlap coefficient: matched images of the smaller set / size of the smaller set. The keypoint
test runs only for images with no pHash match. The link explanation and the pair API say how many images were
matched by keypoints. `FTF_LOCAL_MATCH=0` restores the old behaviour.

Keypoints are stored per creative image (vector kind `local`, 36 bytes per keypoint, 33 KB per image on average). For
materials stored earlier they are computed from the image file on first use. Landing-page assets (`asset_phash`) are
still compared by pHash only.

## Matcher study

### Organiser creatives: 36 images (23 keyframes, 13 screenshots) from 9 cases

Each image against a transformed copy of itself (36 true pairs per transform) and against transformed copies of
images from other labelled campaigns (6,986 different pairs in total).

| Transform | pHash ≤ 4 | centre-crop pHash | ORB inliers, median / min | **chosen rule** |
|---|---|---|---|---|
| crop 8 %, ×0.6, JPEG 55 (the variant test) | 0.00 | 0.56 | 238 / 49 | **1.00** |
| crop 20 %, ×0.4, JPEG 35 | 0.00 | 0.19 | 48 / 0 | 0.53 |
| uneven crop, ×0.7, JPEG 60 | 0.00 | 0.00 | 190 / 19 | 0.86 |
| added band, text and logo | 0.08 | 0.61 | 364 / 247 | 0.94 |
| aspect change 0.8 × 0.6 | 0.81 | 0.92 | 148 / 80 | 1.00 |
| pasted into a larger frame | 0.00 | 0.00 | 172 / 6 | 0.89 |
| tone change, blur, JPEG 45 | 0.81 | 0.83 | 520 / 240 | 0.97 |

Values are recall on true pairs. "Centre-crop pHash" (hashes of four concentric crops) is cheap but fails on any
uneven crop. SIFT recalls slightly more (0.94 on the harshest transform) but at the same threshold accepted 4.9 % of
different pairs, and its descriptors are 16 times larger; not pursued.

Different pictures:

- Without transforms, 499 different-campaign pairs: at most 14 inliers.
- With transforms, 6,986 pairs: 12 pairs reach 25 or more inliers. Eleven of them (26–51 inliers) have an extent
  ≤ 0.018; the highest are keyframes of cases 47 and 14, two screen recordings of a social feed, where the matched
  points lie on the feed's button row and call-to-action band, not on the creative. True pairs of the variant-test
  transform have extent ≥ 0.048.
- The twelfth pair has 28 inliers at extent 0.13. It is the highest different pair once the extent condition applies.

### Threshold and margin

| | inliers | extent |
|---|---|---|
| true pairs, variant-test transform (worst of 36) | 49 | 0.048 |
| **threshold** | **40** | **0.03** |
| different pairs (best of 6,986 + 9,928) | 28 (51 on platform buttons) | 0.018 for the platform-button matches |

The chosen rule accepts 0 of 6,986 different creative pairs.

### Corpus screenshots: 270 pages (at most 8 per kit family), 36,315 pairs

| Group | pairs | accepted by the chosen rule |
|---|---|---|
| NEG (presumed unrelated) | 9,928 | **0** (highest: 26 inliers) |
| no reference at all | 35,172 | 2 |
| same kit family, pHash differs | 441 | 18.6 % |

With 0 of 9,928 the 95 % upper bound of the false-match rate is 0.03 %. The two accepted pairs without a reference
are two fake news pages with the same headline on different domains (86 inliers) and two landing pages from the
same "AI trading platform" template (42 inliers): they look like links the references missed, not false matches.

Product grouping on these 270 pages, with the `images` view set to 1 for every screenshot pair that passes (an
upper bound of the effect):

| | same-campaign pairs | of them in NEG | REF2 recall |
|---|---|---|---|
| product | 635 | 3 | 0.553 |
| + keypoint match | 679 | 4 | 0.603 |

76 pairs are new (75 in POS, 1 in NEG). 32 pairs that were together are no longer together: average linkage
regroups when some distances drop. The change is not purely additive.

## Variant suite, before and after

`tools/evaluate.py --labels data/labels_dane.csv --no-llm`, same store and code, run on the compute server.

| | recompressed | creative_only | landing_only | domain_swap | person_swap | LOO | ARI |
|---|---|---|---|---|---|---|---|
| pHash only | 1/7 | 7/8 | 8/8 | 9/9 | 5/5 | 10/10 | 1.00 |
| **keypoint match (branch default)** | **6/7** | 7/8 | 8/8 | 9/9 | 5/5 | 10/10 | 1.00 |
| keypoint match + character 5-grams | 7/7 | 7/8 | 8/8 | 9/9 | 5/5 | 10/10 | 1.00 |
| pHash only + character 5-grams | 2/7 | 7/8 | 8/8 | 9/9 | 5/5 | 10/10 | 1.00 |

Recompressed, per case (distance to the source material; the campaign cut is 0.60):

| Case | pHash only | keypoint match | + character 5-grams |
|---|---|---|---|
| 1 | 0.93 | 0.596 | 0.557 |
| 3 | 1.00 | **0.667 (miss)** | 0.589 |
| 10 | 0.70 (linked by product name) | 0.448 | 0.396 |
| 14 | 0.68 | 0.457 | 0.363 |
| 36 | 1.00 | 0.500 | 0.500 |
| 48 | 1.00 | 0.500 | 0.500 |
| 61 | 0.92 | 0.589 | 0.401 |

Unit tests: base 78 tests, 1 failure, 4 skipped; branch 80 tests (2 new), the same 1 failure, 4 skipped. The failure
is `test_03_clustering_ari_loo_and_small_subset_regression`, which expects 10 materials in the store; the store copy
holds 11.

Side effect: for cases 3 and 61 the identical screenshot did not match its stored pHash even before this change
(`creative_only` distance 0.667, linked only by file hash). With keypoints the image matches (0.333).

## OCR text: character 5-grams instead of word 4-grams

The recompressed images are small (about 250 × 350 px) and OCR misreads most words. Scaling ×2 before OCR did not
help. Character 5-gram shingles give partial credit for misread words.

| | word 4-grams | character 5-grams |
|---|---|---|
| true pairs (7 recompressed variants), Jaccard | 0.00–0.41 | 0.12–0.73 |
| organiser, different campaigns (30 pairs), max / mean | 0.03 / 0.001 | 0.15 / 0.036 |
| corpus NEG (438,032 pairs), mean | 0.0008 | 0.024 |
| corpus NEG, share ≥ 0.2 | 0.025 % | 0.25 % |
| corpus NEG, share ≥ 0.5 | 0.001 % | 0.002 % |
| corpus product grouping: pairs / precision / fpr | 49,419 / 0.987 / 0.0022 | 49,486 / 0.987 / 0.0022 |

On the corpus the change adds 73 same-campaign pairs, none of them a presumed-unrelated pair, and the largest
campaign stays at 240 pages. Both checks support the change. It is still **off by default** (`FTF_OCR_CHARS=5`): the gain in the variant
suite is one case with a margin of 0.011, unrelated texts get a similarity floor of about 0.02–0.04 instead of 0,
and the switch computes the signature from stored OCR text only, without the ad copy that the stored word signature
includes.

## Cost

- Keypoints: 24 ms per image, 33 KB per image.
- One image pair: 5.6 ms (server, one thread), 8.5 ms (laptop).
- Organiser store, all 45 material pairs: 505 image pairs tested, 8.2 s the first time (includes computing keypoints
  for 36 stored images from their files), 0.06 s afterwards (results are memoised per image pair). pHash only: 0.07 s.
  No link between stored materials changes.
- Corpus scale: 1,128,753 page pairs, 1,049,624 of them with images on both sides and no pHash match. Testing all
  takes about 98 minutes on one thread. Testing only pairs where a full image match could bring the pair within the
  campaign cut, and that are not linked already, leaves 38,248 pairs (3.6 %), about 3.5 minutes.

## Limits

- Evidence is 10 organiser cases, 7 recompressed variants and synthetic transforms. The thresholds were chosen on
  the same 36 images they are reported on.
- An image match is one view of up to five. With a match and nothing else the distance is 0.50; with a match and
  two views at zero it is 0.667, a miss (case 3). Cases 1 and 61 pass at 0.596 and 0.589, just under the cut.
- Redrawn creatives (same message, new artwork) do not match. Pictures with little texture give few keypoints:
  recall on the harshest transform is 0.53.
- The extent condition was derived from one pair of cases (47 and 14). Keyframes of screen recordings still contain
  platform controls; cropping keyframes to the creative, as is done for screenshots, would remove the cause.
- The "after" numbers were measured on the server (Python 3.13). The recompressed baseline is identical on the
  laptop and the server. `47~creative_only` (a video-only case) fails on the server in every run, including pHash
  only, and passes in the laptop report; that is why `creative_only` reads 7/8 here and 8/8 in `data/eval/report.json`.
- `Store.all()` loads the keypoints into memory: about 33 KB per creative image.

## Before merging

1. Candidate gate for the keypoint test (see Cost), or an index of visual words, so cost does not grow with the
   square of the store.
2. Re-run the variant suite on the laptop and refresh `data/eval/report.json` and `docs/RESULTS.md`.
3. Show the keypoint note in the web panel (the pair API returns it as `note`; the panel does not render it yet).
4. Check on real re-uploads of one creative (ad-library copies of the same ad), not only synthetic transforms.
5. Decide on character 5-grams separately; if adopted, store a character signature of the full creative text.
