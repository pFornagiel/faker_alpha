#!/usr/bin/env python
"""Shared evaluation harness for feature experiments on the harvested urlscan corpus (tools/exp_*.py).

The corpus has no campaign labels, so a candidate feature is scored against evidence it does not use itself:

  title   same brand-masked page-title template            (content-side reference)
  ip      same dedicated server IP (outside CDNs / clouds) (infrastructure-side reference)
  tls     TLS certificates issued in the same minute       (infrastructure-side reference, sparse, strong)
  vis     near-identical screenshots (pHash)               (visual reference)
  kit     kit fingerprint >= 0.6: IDF-weighted Jaccard over path templates, JS globals, cookie names,
          third-party hosts, first-party script / stylesheet hashes, favicon hash, input names

From these:  POS  = any reference holds;  REF2 = at least two different references hold (high confidence);
             NEG  = both pages are well described (>= 5 kit tokens, templated title) and no reference holds,
                    kit similarity < 0.1, different ASN -> presumed unrelated.

For every pair set a feature proposes we report
  prec   |M & POS| / |M & (POS | NEG)|   precision among decidable pairs
  fpr    |M & NEG| / |NEG|               false-link rate on presumed-unrelated pairs
  fpr_l  the same on NEG_L, which drops the "kit similarity < 0.1" condition. NEG is defined through kit tokens,
         so it flatters any kit-level feature; NEG_L contains some truly related pairs, so it is pessimistic.
         The true false-link rate lies between the two.
  R_ref2 |M & REF2| / |REF2|             recall of high-confidence pairs
  new    pairs the product does not already put into one campaign (must-link + 5 content views, cut 0.6)
  R_miss recall of the REF2 pairs the product misses
  R_hard recall of the REF2 pairs that both the product and the kit fingerprint (>= 0.6) miss

`Bench.product_with()` re-runs the product clustering with an extra content view and / or extra must-links,
so an experiment can show the effect on campaigns, not only on pairs.

Paths: FTF_ROOT (repo checkout holding data/), FTF_CORPUS, FTF_HARVEST_STORE, FTF_EXP_CACHE override the defaults.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import research_corpus as rc  # noqa: E402

DATA_ROOT = Path(os.environ.get("FTF_ROOT", ROOT))
CORPUS = Path(os.environ.get("FTF_CORPUS", DATA_ROOT / "data" / "harvest" / "urlscan"))
STORE = Path(os.environ.get("FTF_HARVEST_STORE", DATA_ROOT / "data" / "store" / "ftf_harvest.sqlite"))
CACHE = Path(os.environ.get("FTF_EXP_CACHE", DATA_ROOT / "data" / "harvest" / "exp_cache"))
RESULTS = ROOT / "research" / "experiments"
VIEWS = ("text", "ocr", "semantic", "html", "images")
CAMPAIGN_CUT = 0.6


def _pair_rows(args):
    """Worker: product pair comparison for a block of rows (fork-shared globals)."""
    rows, = args
    from ftf import similarity

    ids, items, corpus = _G["ids"], _G["items"], _G["corpus"]
    n = len(ids)
    d = np.ones((len(rows), n), np.float32)
    ml = np.zeros((len(rows), n), bool)
    vs = np.full((len(VIEWS), len(rows), n), np.nan, np.float32)
    for r, i in enumerate(rows):
        a = ids[i]
        for j in range(i + 1, n):
            b = ids[j]
            link = similarity.pair(a, *items[a], b, *items[b], corpus)
            d[r, j] = link.distance
            ml[r, j] = link.must_link
            for k, v in enumerate(VIEWS):
                if v in link.views:
                    vs[k, r, j] = link.views[v]
    return rows, d, ml, vs


_G: dict = {}


class Bench:
    def __init__(self, rebuild: bool = False, workers: int = 6, verbose: bool = True):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        cp = CACHE / "cases.pkl"
        if cp.exists() and not rebuild:
            self.cases = pickle.loads(cp.read_bytes())
        else:
            self.cases = [c for c in (rc.load_case(p) for p in sorted(CORPUS.iterdir()) if p.is_dir()) if c]
            for c in self.cases:
                c["shot"] = str(c["shot"])
            cp.write_bytes(pickle.dumps(self.cases))
        self.N = N = len(self.cases)
        self.names = [c["name"] for c in self.cases]
        self.apex = np.array([c["apex"] for c in self.cases])
        self.iu = np.triu(np.ones((N, N), bool), 1) & (self.apex[:, None] != self.apex[None, :])
        self.n_pairs = int(self.iu.sum())
        self._refs(rebuild)
        self._product(rebuild, workers)
        r = self
        kinds = r.TTL.astype(np.int8) + r.DIP + r.TLS + r.VIS + r.KITFAM
        self.POS = kinds >= 1
        self.REF2 = kinds >= 2
        asn = np.array([c["asn"] for c in self.cases])
        described = (self.kit_ok & (np.array([c["title_tpl"] for c in self.cases]) != ""))
        self.NEG_L = described[:, None] & described[None, :] & ~self.POS & (asn[:, None] != asn[None, :]) & self.iu
        self.NEG = self.NEG_L & (self.KIT < 0.1)
        self.KIT6 = (self.KIT >= 0.6) & self.kit_ok[:, None] & self.kit_ok[None, :] & self.iu
        self.HARD = self.REF2 & ~self.CAMP & ~self.KIT6
        if verbose:
            print(f"corpus: {N} pages, {self.n_pairs} cross-domain pairs | POS {int(self.POS.sum())} REF2 {int(self.REF2.sum())} "
                  f"NEG {int(self.NEG.sum())} NEG_L {int(self.NEG_L.sum())} | product campaigns: same-campaign pairs {int(self.CAMP.sum())}, "
                  f"REF2 pairs it misses {int((self.REF2 & ~self.CAMP).sum())}, of which the kit fingerprint also misses {int(self.HARD.sum())}")

    # ------------------------------------------------------------------ raw material
    def folder(self, i: int) -> Path:
        return CORPUS / self.names[i]

    def html(self, i: int) -> str:
        p = self.folder(i) / "page.html"
        return p.read_text(errors="replace") if p.exists() else ""

    def result(self, i: int) -> dict:
        return json.loads((self.folder(i) / "urlscan_result.json").read_text())

    # ------------------------------------------------------------------ references
    def _refs(self, rebuild: bool) -> None:
        N, cases, iu = self.N, self.cases, self.iu
        p = CACHE / "refs.npz"
        if p.exists() and not rebuild:
            z = np.load(p)
            self.TTL, self.DIP, self.TLS, self.VIS, self.KIT, self.kit_ok, self.kitfam = (
                z["TTL"], z["DIP"], z["TLS"], z["VIS"], z["KIT"], z["kit_ok"], z["kitfam"])
        else:
            ttl = np.array([c["title_tpl"] for c in cases])
            has_t = ttl != ""
            self.TTL = (ttl[:, None] == ttl[None, :]) & has_t[:, None] & has_t[None, :] & iu
            ips = np.array([next(iter(c["fam"].get("ip", {""}))) for c in cases])
            ded = np.array([bool(ip) and c["asn"] not in rc.SHARED_ASN for ip, c in zip(ips, cases)])
            self.DIP = (ips[:, None] == ips[None, :]) & ded[:, None] & ded[None, :] & iu
            tls = [c["fam"].get("tls_issued_min", set()) for c in cases]
            inv = defaultdict(list)
            for i, s in enumerate(tls):
                for v in s:
                    inv[v].append(i)
            self.TLS = np.zeros((N, N), bool)
            for hs in inv.values():
                if len(hs) >= 2:
                    self.TLS[np.ix_(hs, hs)] = True
            self.TLS = (self.TLS | self.TLS.T) & iu
            bits, okv = [], []
            for c in cases:
                b, blank = rc.phash(Path(c["shot"])) if Path(c["shot"]).exists() else (None, True)
                okv.append(b is not None and not blank)
                bits.append(b if b is not None else np.zeros(64, bool))
            B, okv = np.array(bits), np.array(okv)
            self.VIS = np.zeros((N, N), bool)
            for s in range(0, N, 256):
                self.VIS[s:s + 256] = (B[s:s + 256, None, :] != B[None, :, :]).sum(-1) <= 6
            self.VIS &= okv[:, None] & okv[None, :] & iu
            toks = [{f"{f}:{v}" for f in rc.KIT_FAMILIES for v in c["fam"].get(f, ())} for c in cases]
            self.KIT, self.kit_ok = self.idf_jaccard(toks, min_tokens=5)
            uf = rc.UF(N)
            M = (self.KIT >= 0.6) & self.kit_ok[:, None] & self.kit_ok[None, :] & iu
            for i, j in zip(*np.nonzero(M)):
                uf.union(int(i), int(j))
            self.kitfam = np.full(N, -1)
            for k, g in enumerate(uf.groups()):
                for i in g:
                    self.kitfam[i] = k if len(g) >= 2 else -1 - i
            np.savez_compressed(p, TTL=self.TTL, DIP=self.DIP, TLS=self.TLS, VIS=self.VIS, KIT=self.KIT,
                                kit_ok=self.kit_ok, kitfam=self.kitfam)
        self.KITFAM = (self.kitfam[:, None] == self.kitfam[None, :]) & (self.kitfam >= 0)[:, None] & iu

    # ------------------------------------------------------------------ the product on the same pages
    def _product(self, rebuild: bool, workers: int) -> None:
        N = self.N
        p = CACHE / "product.npz"
        if p.exists() and not rebuild:
            z = np.load(p)
            self.d, self.ML, self.views, self.in_store = z["d"], z["ML"], z["views"], z["in_store"]
        else:
            from multiprocessing import get_context

            from ftf import similarity
            from ftf.store import Store

            t0 = time.time()
            items = Store(STORE).all()
            by_name = {n: i for i, n in enumerate(self.names)}
            pick = {m: fv for m, fv in items.items() if fv[0].get("name") in by_name}
            ids = sorted(pick, key=lambda m: by_name[pick[m][0]["name"]])
            row = np.array([by_name[pick[m][0]["name"]] for m in ids])
            _G.update(ids=ids, items=pick, corpus=similarity.Corpus(pick))
            n = len(ids)
            blocks = [list(range(s, min(s + 24, n))) for s in range(0, n, 24)]
            d = np.ones((n, n), np.float32)
            ml = np.zeros((n, n), bool)
            vs = np.full((len(VIEWS), n, n), np.nan, np.float32)
            with get_context("fork").Pool(workers) as pool:
                for k, (rows, dd, mm, vv) in enumerate(pool.imap_unordered(_pair_rows, [(b,) for b in blocks])):
                    d[rows], ml[rows], vs[:, rows] = dd, mm, vv
                    if self.verbose and k % 10 == 0:
                        print(f"  product pairs: block {k}/{len(blocks)} {time.time() - t0:.0f}s", flush=True)
            self.d = np.ones((N, N), np.float32)
            self.ML = np.zeros((N, N), bool)
            self.views = np.full((len(VIEWS), N, N), np.nan, np.float32)
            ix = np.ix_(row, row)
            self.d[ix] = np.minimum(np.triu(d, 1) + np.triu(d, 1).T + np.eye(n), 1.0)
            self.ML[ix] = ml | ml.T
            for k in range(len(VIEWS)):
                up = np.triu(vs[k], 1)
                self.views[k][ix] = np.where(np.isnan(up), up.T, up)
            self.in_store = np.zeros(N, bool)
            self.in_store[row] = True
            np.savez_compressed(p, d=self.d, ML=self.ML, views=self.views, in_store=self.in_store)
        np.fill_diagonal(self.d, 0.0)
        self.camp = self.cluster(self.d, self.ML)
        self.CAMP = (self.camp[:, None] == self.camp[None, :]) & self.iu

    @staticmethod
    def cluster(d: np.ndarray, must: np.ndarray, cut: float = CAMPAIGN_CUT) -> np.ndarray:
        """The product's grouping: must-link components at distance 0, average linkage, cut. Returns labels."""
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial.distance import squareform

        n = len(d)
        _, comp = connected_components(must | must.T, directed=False)
        D = np.where(comp[:, None] == comp[None, :], 0.0, d).astype(np.float64)
        D = np.minimum(D, D.T)
        np.fill_diagonal(D, 0.0)
        lab = fcluster(linkage(squareform(D, checks=False), method="average"), t=cut, criterion="distance")
        uf = rc.UF(n)
        first: dict = {}
        for i in range(n):
            for key in (("l", lab[i]), ("c", comp[i])):
                if key in first:
                    uf.union(i, first[key])
                else:
                    first[key] = i
        return np.array([uf.find(i) for i in range(n)])

    def product_with(self, extra_views: dict[str, np.ndarray] | None = None, extra_must: np.ndarray | None = None,
                     label: str = "", replace: dict[str, np.ndarray] | None = None) -> dict:
        """Re-run the product grouping with extra content views (N x N, NaN = unavailable) and / or must-links."""
        stack = [self.views[k] for k in range(len(VIEWS))]
        for name, S in (replace or {}).items():
            stack[VIEWS.index(name)] = S
        for S in (extra_views or {}).values():
            S = np.where(np.isnan(S), S.T, S).astype(np.float32)
            stack.append(S)
        V = np.stack(stack)
        k = (~np.isnan(V)).sum(0)
        d = np.where(k > 0, 1.0 - np.nansum(V, 0) / np.maximum(k, 1), 1.0)
        must = self.ML if extra_must is None else (self.ML | extra_must | extra_must.T)
        lab = self.cluster(d, must)
        M = (lab[:, None] == lab[None, :]) & self.iu
        sizes = sorted(Counter(lab).values(), reverse=True)
        out = {"label": label or "product", "largest": sizes[0], "groups": sum(1 for s in sizes if s >= 2),
               "singletons": sum(1 for s in sizes if s == 1), **self.score(M)}
        return out

    # ------------------------------------------------------------------ scoring
    def score(self, M: np.ndarray) -> dict:
        M = (M | M.T) & self.iu
        n = int(M.sum())
        dec = int((M & (self.POS | self.NEG)).sum())
        new = M & ~self.CAMP
        miss = self.REF2 & ~self.CAMP
        f = lambda x, y: round(float(x) / max(float(y), 1.0), 4)  # noqa: E731
        return {"pairs": n, "pages": int((M | M.T).any(1).sum()),
                "prec": f((M & self.POS).sum(), dec), "fpr": f((M & self.NEG).sum(), self.NEG.sum()),
                "fpr_l": f((M & self.NEG_L).sum(), self.NEG_L.sum()),
                "R_ref2": f((M & self.REF2).sum(), self.REF2.sum()), "R_kit": f((M & self.KITFAM).sum(), self.KITFAM.sum()),
                "P_title": f((M & self.TTL).sum(), n), "P_ip": f((M & self.DIP).sum(), n), "P_tls": f((M & self.TLS).sum(), n),
                "P_vis": f((M & self.VIS).sum(), n), "P_kit": f((M & self.KITFAM).sum(), n),
                "new": int(new.sum()), "new_prec": f((new & self.POS).sum(), (new & (self.POS | self.NEG)).sum()),
                "R_miss": f((M & miss).sum(), miss.sum()), "R_hard": f((M & self.HARD).sum(), self.HARD.sum())}

    def shared_value(self, values: list[set], lo: int = 2, cap: int | None = None) -> np.ndarray:
        """Pairs sharing a value held by lo..cap registrable domains (default cap: 2 % of the corpus)."""
        cap = cap or max(10, self.N // 50)
        inv = defaultdict(list)
        for i, s in enumerate(values):
            for v in s:
                inv[v].append(i)
        M = np.zeros((self.N, self.N), bool)
        for hs in inv.values():
            if lo <= len({self.apex[h] for h in hs}) <= cap:
                idx = np.array(hs)
                M[np.ix_(idx, idx)] = True
        return (M | M.T) & self.iu

    def idf_jaccard(self, token_sets: list[set], min_tokens: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """IDF-weighted Jaccard between token sets (tokens held by >= 2 pages). Returns (S, enough_tokens)."""
        N = len(token_sets)
        df = Counter(t for s in token_sets for t in s)
        vocab = {t: i for i, t in enumerate(sorted(t for t, d in df.items() if d >= 2))}
        idf = np.array([np.log(N / df[t]) for t in vocab], dtype=np.float32)
        X = np.zeros((N, len(vocab)), dtype=np.float32)
        for i, s in enumerate(token_sets):
            for t in s:
                if t in vocab:
                    X[i, vocab[t]] = 1.0
        W = X * idf
        inter = W @ X.T
        tot = W.sum(1)
        S = inter / np.maximum(tot[:, None] + tot[None, :] - inter, 1e-9)
        return S.astype(np.float32), X.sum(1) >= min_tokens

    def sweep(self, S: np.ndarray, thresholds=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9), ok: np.ndarray | None = None) -> list[dict]:
        """Graded similarity (higher = more alike, NaN = unavailable) -> one score row per threshold."""
        S = np.where(np.isnan(S), -1.0, S)
        okm = self.iu if ok is None else (ok[:, None] & ok[None, :] & self.iu)
        return [{"thr": t, **self.score((S >= t) & okm)} for t in thresholds]

    def auc(self, S: np.ndarray, ok: np.ndarray | None = None) -> dict:
        """Ranking quality: P(sim of a REF2 pair > sim of a NEG pair), and of a product-missed REF2 pair."""
        S = np.where(np.isnan(S), -1.0, np.maximum(S, S.T))
        okm = self.iu if ok is None else (ok[:, None] & ok[None, :] & self.iu)
        rng = np.random.default_rng(0)

        def one(P):
            a, b = S[P & okm], S[self.NEG & okm]
            if not len(a) or not len(b):
                return None
            a, b = rng.choice(a, min(len(a), 4000)), rng.choice(b, min(len(b), 4000))
            return round(float((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean()), 3)
        return {"auc_ref2": one(self.REF2), "auc_missed": one(self.REF2 & ~self.CAMP), "auc_ip_or_tls": one(self.DIP | self.TLS),
                "coverage": round(float(ok.mean()), 3) if ok is not None else 1.0}

    # ------------------------------------------------------------------ output
    COLS = ("pairs", "pages", "prec", "fpr", "fpr_l", "R_ref2", "R_kit", "P_title", "P_ip", "P_tls", "P_vis", "P_kit", "new", "new_prec", "R_miss", "R_hard")

    def table(self, rows: list[dict], key: str = "label", width: int = 34) -> str:
        lead = [c for c in ("largest", "groups", "singletons") if c in rows[0]]
        cols = lead + list(self.COLS)
        out = [f"{key:<{width}}" + "".join(f"{c:>9}" for c in cols)]
        for r in rows:
            out.append(f"{str(r.get(key, ''))[:width - 1]:<{width}}" + "".join(
                f"{r[c]:>9.4f}" if c in ("fpr", "fpr_l") else f"{r[c]:>9.2f}" if isinstance(r[c], float) else f"{r[c]:>9}" for c in cols))
        return "\n".join(out)

    def baselines(self) -> list[dict]:
        """What already exists: the product's campaigns, its must-links alone, each content view, the kit fingerprint."""
        rows = [{"label": "product: same campaign", **self.score(self.CAMP)},
                {"label": "product: must-link only", **self.score(self.ML)}]
        for k, v in enumerate(VIEWS):
            rows.append({"label": f"view {v} >= 0.5", **self.score(np.nan_to_num(self.views[k], nan=-1) >= 0.5)})
        rows.append({"label": "kit fingerprint >= 0.6", **self.score(self.KIT6)})
        return rows

    def examples(self, M: np.ndarray, n: int = 15, seed: int = 0, only_new: bool = True) -> list[str]:
        """Random linked pairs (by default only those the product does not group) with hosts and titles, for reading."""
        M = (M | M.T) & self.iu & (~self.CAMP if only_new else True)
        ii, jj = np.nonzero(M)
        if not len(ii):
            return []
        pick = np.random.default_rng(seed).choice(len(ii), min(n, len(ii)), replace=False)
        out = []
        for k in pick:
            i, j = int(ii[k]), int(jj[k])
            tag = "+".join(t for t, R in (("title", self.TTL), ("ip", self.DIP), ("tls", self.TLS), ("vis", self.VIS), ("kit", self.KITFAM)) if R[i, j]) or (
                "NEG" if self.NEG[i, j] else "negL" if self.NEG_L[i, j] else "?")
            out.append(f"[{tag:<14}] kit {self.KIT[i, j]:.2f} d {self.d[i, j]:.2f} | {self.names[i][:34]:<34} {self.cases[i]['title'][:38]!r:<40} | "
                       f"{self.names[j][:34]:<34} {self.cases[j]['title'][:38]!r}")
        return out

    @staticmethod
    def save(name: str, obj: dict) -> Path:
        RESULTS.mkdir(parents=True, exist_ok=True)
        p = RESULTS / f"{name}.json"
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
        return p


if __name__ == "__main__":
    b = Bench(rebuild="--rebuild" in sys.argv)
    rows = b.baselines()
    print(b.table(rows))
    print(b.table([b.product_with(label="product (recomputed from views)")]))
    for k, v in enumerate(VIEWS):
        print(f"view {v:<9}", b.auc(b.views[k], ok=None), f"available on {float((~np.isnan(b.views[k]))[b.iu].mean()):.2f} of pairs")
    print("kit fingerprint", b.auc(b.KIT, ok=b.kit_ok))
    Bench.save("baseline", {"rows": rows})
