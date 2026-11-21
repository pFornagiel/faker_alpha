"""Campaigns and families from pairwise links + open-set assignment of a new material.

  1. must-link   : union-find over pairs sharing a counted identifier or an identical file (Christen 2012)
  2. distance    : D(a, b) = 0 inside a must-link component, else the content (Gower) distance d(a, b)
  3. campaigns   : average-linkage (UPGMA) dendrogram on D (scipy, Müllner 2011) cut at config.CAMPAIGN_CUT;
     families    : the same dendrogram cut at config.FAMILY_CUT (groups of content-similar campaigns)
  4. duplicates  : union-find over `duplicate` links (same file / same ad ID / d <= DUPLICATE_CUT)
  5. baseline    : HDBSCAN (Campello et al. 2013) on the same D, for comparison
  6. assign()    : nearest known material (1-NN, Cover & Hart 1967), rejected above CAMPAIGN_CUT (Bendale & Boult 2015)
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from . import config
from .similarity import Corpus, Link, all_links, pair


class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def groups(self) -> list[list]:
        g = defaultdict(list)
        for i in self.p:
            g[self.find(i)].append(i)
        return list(g.values())


def _sorted_groups(labels: dict) -> list[list[str]]:
    g = defaultdict(list)
    for m, lab in labels.items():
        g[lab].append(m)
    return sorted(g.values(), key=lambda c: (-len(c), min(c)))


def distance_matrix(ids: list[str], links: list[Link]) -> tuple[np.ndarray, UF]:
    """D: 0 inside must-link components, else the Gower content distance (1.0 when incomparable)."""
    comp = UF(ids)
    for l in links:
        if l.must_link:
            comp.union(l.a, l.b)
    idx = {m: i for i, m in enumerate(ids)}
    D = np.ones((len(ids), len(ids)))
    np.fill_diagonal(D, 0.0)
    for l in links:
        D[idx[l.a], idx[l.b]] = D[idx[l.b], idx[l.a]] = 0.0 if comp.find(l.a) == comp.find(l.b) else l.distance
    return D, comp


def cut(ids: list[str], D: np.ndarray, comp: UF, threshold: float) -> dict[str, int]:
    """Average-linkage dendrogram cut at `threshold`; must-link components are never split."""
    if len(ids) < 2:
        return {m: 0 for m in ids}
    lab = fcluster(linkage(squareform(D, checks=False), method="average"), t=threshold, criterion="distance")
    uf = UF(ids)
    by_lab = defaultdict(list)
    for m, x in zip(ids, lab):
        by_lab[x].append(m)
        uf.union(m, comp.find(m))
    for ms in by_lab.values():
        for m in ms[1:]:
            uf.union(ms[0], m)
    return {m: uf.find(m) for m in ids}


def build(items: dict[str, tuple[dict, dict]], links: list[Link] | None = None) -> dict:
    ids = list(items)
    links = links if links is not None else all_links(items)
    D, comp = distance_matrix(ids, links)
    campaigns = _sorted_groups(cut(ids, D, comp, config.CAMPAIGN_CUT))
    families = _sorted_groups(cut(ids, D, comp, config.FAMILY_CUT))
    dup = UF(ids)
    for l in links:
        if l.relation == "duplicate":
            dup.union(l.a, l.b)
    return {"links": links, "duplicates": [g for g in dup.groups() if len(g) > 1],
            "campaigns": campaigns, "campaign_of": {m: i for i, c in enumerate(campaigns) for m in c},
            "families": families, "family_of": {m: i for i, c in enumerate(families) for m in c},
            "hdbscan": hdbscan_baseline(ids, D)}


def hdbscan_baseline(ids: list[str], D: np.ndarray) -> dict:
    if len(ids) < 3:
        return {}
    try:
        from sklearn.cluster import HDBSCAN

        lab = HDBSCAN(min_cluster_size=2, metric="precomputed", allow_single_cluster=True, copy=True).fit_predict(D)
        return {m: int(x) for m, x in zip(ids, lab)}
    except Exception:
        return {}


# ------------------------------------------------------------------------------ campaign profiles
def profile(members: list[str], items: dict, links: list[Link]) -> dict:
    feats = [items[m][0] for m in members]
    cnt = defaultdict(Counter)
    for f in feats:
        for t, vals in f.get("indicators", {}).items():
            if t in config.IDENTIFIER_GROUP:
                for v in set(vals):
                    cnt[t][v] += 1
    shared = sorted(({"type": t, "group": config.IDENTIFIER_GROUP[t], "value": v, "count": n}
                     for t, c in cnt.items() for v, n in c.items() if n >= 2), key=lambda d: (-d["count"], d["type"], d["value"]))
    mem = set(members)
    inner = [l for l in links if l.a in mem and l.b in mem]
    persons = Counter(p for f in feats for p in set(f.get("persons_visual", [])) | set(f.get("persons_named", [])))
    llm = [f.get("llm") or {} for f in feats]
    products = Counter(x.get("product_or_platform_name") for x in llm if x.get("product_or_platform_name"))
    stypes = Counter(x.get("scam_type") for x in llm if x.get("scam_type") and x.get("scam_type") != "other")
    domains = Counter(d for f in feats for d in f.get("web", {}).get("landing_domains", []))
    titles = Counter(t for f in feats for t in f.get("text", {}).get("titles", []))
    dates = sorted(d for f in feats for d in f.get("dates", []))
    main = (products.most_common(1) or stypes.most_common(1) or [("?", 0)])[0][0]
    who = (persons.most_common(1) or [("", 0)])[0][0]
    return {
        "members": members, "size": len(members), "name": " · ".join(x for x in [str(main), who] if x),
        "scam_types": dict(stypes), "products": dict(products), "persons": dict(persons.most_common(8)),
        "domains": dict(domains), "titles": [t for t, _ in titles.most_common(5)],
        "date_range": [dates[0], dates[-1]] if dates else [], "shared_indicators": shared[:25],
        "shared_groups": dict(Counter(s["group"] for s in shared)), "internal_links": len(inner),
        "mean_internal_p": round(float(np.mean([l.p for l in inner])), 3) if inner else None,
    }


# ------------------------------------------------------------------------------ open-set assignment
def assign(new_id: str, new_f: dict, new_v: dict, items: dict, clustering: dict) -> dict:
    """New material vs the analysed set: duplicate / known_campaign / merge_proposal / new_campaign.

    Batch clustering groups materials (average linkage); assignment answers a different question — "is this a
    variant of a material we already know?" — so it uses the nearest neighbour with a rejection threshold
    (1-NN, Cover & Hart 1967; open-set rejection, Bendale & Boult 2015): shared counted identifiers decide
    first (one campaign -> known_campaign, >= 2 -> merge_proposal); otherwise the nearest known material m* by
    content distance d: d <= CAMPAIGN_CUT -> its campaign, else new_campaign (+ similar_family if d <= FAMILY_CUT).
    """
    corpus = Corpus({**items, new_id: (new_f, new_v)})
    links = [pair(new_id, new_f, new_v, mid, f, v, corpus) for mid, (f, v) in items.items() if mid != new_id]
    links.sort(key=lambda l: (-l.p, l.distance))
    camp_of = clustering["campaign_of"]
    known = [l for l in links if camp_of.get(l.b) is not None]
    id_camps = sorted({camp_of[l.b] for l in known if l.must_link})
    per_c: dict[int, float] = {}                   # 1-NN content distance per campaign
    for l in known:
        per_c[camp_of[l.b]] = min(per_c.get(camp_of[l.b], 1.0), l.distance)
    nn = min(known, key=lambda l: (l.distance, l.b), default=None)
    nearest = ({"campaign": camp_of[nn.b], "distance": round(nn.distance, 3), "material": nn.b,
                "name": str(items[nn.b][0].get("name") or nn.b)} if nn else None)
    decision, camp, similar = "new_campaign", None, None
    if len(id_camps) == 1:
        decision, camp = "known_campaign", id_camps[0]
    elif len(id_camps) >= 2:
        decision, camp = "merge_proposal", min(id_camps, key=lambda c: per_c.get(c, 1.0))
    elif nn and nn.distance <= config.CAMPAIGN_CUT:
        decision, camp = "known_campaign", camp_of[nn.b]
    elif nn and nn.distance <= config.FAMILY_CUT:
        similar = camp_of[nn.b]
    dups = [l for l in links if l.relation == "duplicate"]
    if dups and decision != "merge_proposal":
        decision, camp = "duplicate", camp_of.get(dups[0].b, camp)
    scores = sorted(((round(1.0 - d, 3), c) for c, d in per_c.items()), key=lambda t: (-t[0], t[1]))
    return {"decision": decision, "campaign": camp, "duplicates": [l.b for l in dups], "similar_family": similar,
            "nearest": nearest, "campaign_scores": scores[:5], "links": links}
