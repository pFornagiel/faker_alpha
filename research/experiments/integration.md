# Integration of the promising signals into the product (`feature/promising-signals`)

**Result.** On the research corpus the product now puts 72 % of the well-evidenced page pairs into one campaign,
up from 38 %, with the same rate of presumed-false links (0.0022). On the ten organiser cases the grouping is
unchanged and the "recompressed" variant test goes from 2/7 to 6/7.

Numbers: `research/experiments/integration.json` (corpus), produced by `tools/exp_integration.py`. Protocol and
column definitions: `research/experiments/README.md`.

## What was integrated

| Change | Where | From experiment |
|---|---|---|
| view `css`: MinHash Jaccard of the page's CSS class names, generated parts masked | `web.class_vocabulary`, vector kind `css` | `exp/css-class-vocab` |
| view `js`: MinHash Jaccard of token 5-grams of own inline scripts, literals masked | `web.script_shingles`, vector kind `js` | `exp/script-skeleton` |
| language rule: `text` and `ocr` are unavailable for a pair of texts in two different known languages | `ftf/lang.py`, `similarity.views` | `exp/lang-invariant-copy` |
| identifier `cert_batch` (group `certificates`): issuance minute of the host's own TLS certificate | `web.cert_batch`, `tools/harvest_urlscan.py` (`tls_san`) | `exp/scan-metadata` |
| keypoint image match where pHash fails, gated in stores above 300 materials | `vision.local_match`, `similarity.views` | `exp/crop-robust-images` |
| fix: `extract_html` failed on a canonical link or `og:url` inside `<noscript>` | `ftf/web.py` | found during the corpus run: 87 of 1,503 pages had lost their HTML features |

Materials analysed earlier keep working: a missing signature or language means the view or the rule does not apply.
`tools/backfill_page_signals.py` adds the page signals to an existing store without re-running OCR and the models.

## Research corpus: 1,503 pages, 1,128,749 cross-domain pairs

The corpus was re-analysed with the new code. Each change is applied on its own to the same pairwise matrices; the
last row is the product code path itself, and it gives the same grouping as the sum of the changes (0 pairs differ).
`new` counts pairs the grouping before the integration did not have.

| Grouping | same-campaign pairs | singletons | largest | prec | fpr | fpr_l | R_ref2 | new | new_prec |
|---|---|---|---|---|---|---|---|---|---|
| before (old code, old store) | 49,419 | 350 | 240 | 0.99 | 0.0022 | 0.0022 | 0.38 | – | – |
| re-analysed, five views (parse fix only) | 49,438 | 325 | 240 | 0.99 | 0.0022 | 0.0022 | 0.38 | 33 | 1.00 |
| + `css` view | 49,902 | 280 | 240 | 0.99 | 0.0022 | 0.0022 | 0.43 | 766 | 0.99 |
| + `js` view | 50,248 | 289 | 240 | 0.99 | 0.0022 | 0.0022 | 0.43 | 839 | 1.00 |
| + `css` and `js` views | 52,474 | 256 | 240 | 0.99 | 0.0022 | 0.0022 | 0.48 | 3,078 | 1.00 |
| + language rule | 52,233 | 271 | 240 | 0.99 | 0.0022 | 0.0023 | 0.46 | 2,826 | 1.00 |
| + certificate batch | 50,698 | 311 | 243 | 0.99 | 0.0022 | 0.0022 | 0.43 | 1,517 | 1.00 |
| + keypoint image match | 51,207 | 288 | 240 | 0.99 | 0.0022 | 0.0022 | 0.42 | 1,843 | 1.00 |
| all changes except certificate batch | 55,765 | 217 | 240 | 0.99 | 0.0022 | 0.0025 | 0.69 | 6,351 | 1.00 |
| **all changes (product code path)** | **56,889** | **209** | 243 | 0.99 | 0.0022 | 0.0025 | **0.72** | 7,600 | 1.00 |

Reading the table:

- The changes reinforce each other: together they add 7,600 pairs, more than any single one, because a pair that one
  change moves just under the cut pulls its neighbours with it under average linkage.
- The share of pairs that are kit-similar but have no other evidence of a link (`fpr_l`) rises from 0.0022 to
  0.0025. That is the price of two more structure views.
- 1,052 pages have a `css` signature and 970 a `js` signature; 878 pages get a language. The keypoint test matched
  4,233 screenshot pairs that pHash did not.
- 411 pairs share a certificate-batch value.

Limits of this evidence:

- The corpus has no operator labels. `prec`, `fpr` and `R_ref2` are measured against indirect references (same title
  template, dedicated IP, certificate minute, near-identical screenshot, kit fingerprint).
- The certificate-batch identifier is the same fact as the `tls` reference, so its own row confirms itself. The row
  "all changes except certificate batch" (R_ref2 0.69) is the one free of that. Independent evidence for the
  identifier comes from the experiment: pairs of own certificates issued in the same second share the page-title
  template in 95 % of cases and a dedicated IP in 46 %.
- The `kit` reference and the `css` / `js` views all describe the page template, and presumed-unrelated pairs are
  defined with the kit fingerprint. Kit-level signals are therefore judged favourably. A shared kit is evidence of a
  shared supplier, not always of one operator.
- MinHash on plain class-name sets ranks pairs slightly worse than the IDF-weighted Jaccard of the experiment
  (AUC 0.96 against 0.99 on the well-evidenced pairs). It was kept because it stores 128 numbers per page and needs
  no corpus statistics.

## Organiser cases (10 materials, labels in `data/labels_dane.csv`)

`tools/evaluate.py --no-llm --labels data/labels_dane.csv`, old and new code on the same machine with a fresh
analysis each.

| | before | after |
|---|---|---|
| campaigns, duplicates, families | 6 campaigns | identical |
| labels: pairwise precision / recall, ARI | 1.00 / 1.00, 1.00 | 1.00 / 1.00, 1.00 |
| leave-one-out | 9/10 | 9/10 |
| variants: creative only | 7/8 | 7/8 |
| variants: landing page only | 8/8 | 8/8 |
| variants: domain swapped | 9/9 | 9/9 |
| variants: person swapped | 5/5 | 5/5 |
| variants: recompressed screenshot | 2/7 | **6/7** |

The recompressed gain comes from the keypoint image match alone; the page signals changed no decision here. The
leave-one-out miss (case 2, answered with a merge proposal) and the creative-only miss (case 47, a video-only case)
occur before and after. These runs are without the LLM, so they differ from `docs/RESULTS.md`, which was measured
with it on the stored analysis.

## Examined for integration and left out

- **Structure-group fusion** (`exp/fusion-two-groups`: distance = the smaller of the mean over all views and the
  mean over the structure views). With the product's MinHash signatures it is not stable: `html`+`css` gives
  prec 0.90 and fpr 0.0228; `html`+`css`+`js` with at least two of them gives prec 0.99, fpr 0.0033, fpr_l 0.0081
  and R_ref2 0.94; moving the structure cut from 0.6 to 0.5 drops the same variant to prec 0.92. The experiment had
  measured fpr 0.0027 with IDF-weighted class similarity. A rule whose outcome flips with the representation and the
  cut is not shipped; the views inside the plain mean already bring most of the gain at an unchanged fpr.
- **Compression distance (LZJD)**: adds 0.02–0.05 recall of missed pairs beyond the `html` view and the kit
  signals.
- **Kit fingerprint** as a view: it needs corpus-wide IDF statistics and the full scan record, which an uploaded
  page does not have. `css` and `js` carry the part of it that can be computed from one HTML file.
- **Character 5-grams for the `ocr` view**: stays behind `FTF_OCR_CHARS=5` (one case gained, margin 0.011).

## Reproduce

```
FTF_STORE=<new store> python tools/ingest_parallel.py data/harvest/urlscan --source urlscan --require page.html
FTF_HARVEST_STORE=<new store> FTF_EXP_BASE_CACHE=<cache of the old product> FTF_EXP_CACHE=<new dir> \
    python tools/exp_integration.py
python tools/evaluate.py --no-llm --labels data/labels_dane.csv
```
