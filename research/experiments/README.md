# Feature experiments (November 2026)

One branch and worktree per experiment (`exp/<name>`, forked from `exp/base`). Each adds `tools/exp_<name>.py`,
a write-up `research/experiments/<name>.md` and its numbers `research/experiments/<name>.json`. Nothing in an
experiment branch changes the product pipeline unless its write-up says so.

## Protocol

Data: 1,503 pages from the CERT Polska warning list with a full urlscan.io scan (`data/harvest/urlscan`, not in the
repo) and the 10 organiser cases. The corpus has no campaign labels, so `tools/exp_harness.py` scores a feature
against evidence the feature does not use:

| Reference | Meaning |
|---|---|
| `title` | same brand-masked page-title template |
| `ip` | same dedicated server IP (outside CDNs and large clouds) |
| `tls` | TLS certificates issued in the same minute |
| `vis` | near-identical screenshots (pHash, Hamming ≤ 6) |
| `kit` | kit fingerprint ≥ 0.6 (IDF-weighted Jaccard over path templates, JS globals, cookie names, third-party hosts, script / stylesheet / favicon hashes, input names) |

`POS` = at least one reference holds, `REF2` = at least two different references hold, `NEG` = both pages are well
described and nothing connects them (presumed unrelated).

| Column | Definition |
|---|---|
| `prec` | linked pairs in `POS` / linked pairs in `POS ∪ NEG` |
| `fpr` | linked `NEG` pairs / all `NEG` pairs |
| `R_ref2` | share of `REF2` pairs linked |
| `new`, `new_prec` | linked pairs the product does not already put into one campaign, and their `prec` |
| `R_miss` | share of the `REF2` pairs the product misses that the feature links |
| `P_ip`, `P_tls` | share of linked pairs with the same dedicated IP / certificate minute: operator-level evidence, not only the same kit |

`Bench.product_with()` re-runs the product grouping (must-link + Gower mean over views + average linkage, cut 0.6)
with the feature added as a sixth view or as must-links.

## When a feature counts as working

1. An operating point with `prec` ≥ 0.9 and `fpr` ≤ 0.001.
2. It finds pairs the product misses (`R_miss` clearly above 0) and those pairs hold up (`new_prec`).
3. Added to the product grouping it does not merge unrelated campaigns (largest campaign, `prec`).
4. It can be computed from what the product receives (saved HTML, HAR, screenshots, video), not only from urlscan JSON.

A reference built from kit tokens cannot confirm another kit-level feature on its own: check `P_ip`, `P_tls`, `P_title`.
Most references are kit-level; a kit can be sold to several operators.

    FTF_ROOT=<checkout with data/> .venv/bin/python tools/exp_harness.py      # builds the cache, prints baselines
