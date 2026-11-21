"""Three-level grouping + incremental (open-set) assignment.

  L0 duplicates  : union-find on `duplicate` links (deduplicates repeated reports of one creative)
  L1 campaigns   : cores = union-find on operator-level links (S-tier family >= 0.6), then
                   average-linkage agglomeration of cores; the average is taken only over *comparable*
                   pairs (pairs that share at least one modality), so incomplete materials (dead page,
                   deleted video) are not penalised; a single very strong link (p >= 0.85) also merges.
  L2 families    : campaigns merged by "playbook" similarity only (narrative/concept/visual/persons):
                   same scam recipe, possibly different operators — reported separately on purpose.
  baseline       : HDBSCAN on the fused distance (1 - p) for comparison (ablation).
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

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

    def groups(self):
        g = defaultdict(list)
        for i in self.p:
            g[self.find(i)].append(i)
        return list(g.values())


def _avg_link(c1, c2, P, C):
    vals = [P.get((a, b), P.get((b, a), 0.0)) for a in c1 for b in c2 if C.get((a, b), C.get((b, a), False))]
    mx = max([P.get((a, b), P.get((b, a), 0.0)) for a in c1 for b in c2] or [0])
    return (float(np.mean(vals)) if vals else 0.0), mx


def agglomerate(clusters: list[list[str]], P: dict, C: dict, thr: float, strong: float = 0.85) -> list[list[str]]:
    clusters = [list(c) for c in clusters]
    while True:
        best, bi, bj = 0.0, -1, -1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                avg, mx = _avg_link(clusters[i], clusters[j], P, C)
                score = max(avg, mx if mx >= strong else 0)
                if score > best:
                    best, bi, bj = score, i, j
        if best < thr or bi < 0:
            return clusters
        clusters[bi].extend(clusters[bj])
        del clusters[bj]


def build(items: dict[str, tuple[dict, dict]], links: list[Link] | None = None) -> dict:
    ids = list(items)
    links = links if links is not None else all_links(items)
    P = {(l.a, l.b): l.p for l in links}
    C = {(l.a, l.b): l.comparable for l in links}
    PB = {(l.a, l.b): l.playbook for l in links}
    # L0 duplicates
    uf0 = UF(ids)
    for l in links:
        if l.relation == "duplicate":
            uf0.union(l.a, l.b)
    dup_groups = [g for g in uf0.groups() if len(g) > 1]
    # L1 cores on operator-level evidence
    uf1 = UF(ids)
    for l in links:
        s_tier = max([v for f, v in l.families.items() if config.FAMILY_TIER.get(f) == "S"] or [0])
        if l.relation == "duplicate" or (s_tier >= 0.6 and l.p >= config.LINK_THRESHOLD):
            uf1.union(l.a, l.b)
    cores = uf1.groups()
    campaigns = agglomerate(cores, P, C, config.LINK_THRESHOLD)
    campaigns.sort(key=lambda c: (-len(c), min(c)))
    camp_of = {m: i for i, c in enumerate(campaigns) for m in c}
    # L1.5 message variants inside a campaign: same narrative (near-duplicate text / template / same creative)
    ufv = UF(ids)
    for l in links:
        same_msg = any(e.signal in ("text_minhash", "masked_minhash", "title_template", "phash") and e.weight >= 0.45
                       for e in l.evidence)
        if camp_of.get(l.a) == camp_of.get(l.b) and (l.relation == "duplicate" or same_msg):
            ufv.union(l.a, l.b)
    variants = {}
    for g in ufv.groups():
        variants.setdefault(camp_of[g[0]], []).append(sorted(g))
    # L2 families (playbooks)
    fams = agglomerate([list(c) for c in campaigns], PB, C, 0.40, strong=0.75)
    fams.sort(key=lambda c: (-len(c), min(c)))
    fam_of = {m: i for i, c in enumerate(fams) for m in c}
    return {"links": links, "duplicates": dup_groups, "campaigns": campaigns, "campaign_of": camp_of, "variants": variants,
            "families": fams, "family_of": fam_of, "hdbscan": hdbscan_baseline(ids, P)}


def hdbscan_baseline(ids, P) -> dict:
    if len(ids) < 3:
        return {}
    try:
        from sklearn.cluster import HDBSCAN

        idx = {m: i for i, m in enumerate(ids)}
        D = np.ones((len(ids), len(ids)))
        np.fill_diagonal(D, 0)
        for (a, b), p in P.items():
            D[idx[a], idx[b]] = D[idx[b], idx[a]] = 1 - p
        lab = HDBSCAN(min_cluster_size=2, metric="precomputed", allow_single_cluster=True, copy=True).fit_predict(D)
        return {m: int(lab[idx[m]]) for m in ids}
    except Exception:
        return {}


# ------------------------------------------------------------------------------ campaign profiles
def profile(members: list[str], items: dict, links: list[Link]) -> dict:
    feats = [items[m][0] for m in members]
    cnt = defaultdict(Counter)
    for f in feats:
        for t, vals in f.get("indicators", {}).items():
            for v in set(vals):
                cnt[t][v] += 1
    shared = []
    for t, c in cnt.items():
        for v, n in c.items():
            if n >= 2 and t in config.INDICATOR_WEIGHT:
                shared.append({"type": t, "value": v, "count": n, "score": n * config.INDICATOR_WEIGHT[t]})
    shared.sort(key=lambda d: -d["score"])
    mem = set(members)
    inner = [l for l in links if l.a in mem and l.b in mem]
    fam_c = Counter()
    for l in inner:
        for f, v in l.families.items():
            if v >= 0.3:
                fam_c[f] += 1
    persons = Counter(p for f in feats for p in set(f.get("persons_visual", [])) | set(f.get("persons_named", [])))
    llm = [f.get("llm", {}) for f in feats]
    products = Counter(x.get("product_or_platform_name") for x in llm if x.get("product_or_platform_name"))
    stypes = Counter(x.get("scam_type") for x in llm if x.get("scam_type") and x.get("scam_type") != "other")
    narr = Counter(x.get("narrative_template") for x in llm if x.get("narrative_template") and x.get("narrative_template") != "other")
    domains = Counter(d for f in feats for d in f.get("web", {}).get("landing_domains", []))
    titles = Counter(t for f in feats for t in f.get("text", {}).get("titles", []))
    dates = sorted(d for f in feats for d in f.get("dates", []))
    main = (products.most_common(1) or narr.most_common(1) or [("?", 0)])[0][0]
    who = (persons.most_common(1) or [("", 0)])[0][0]
    return {
        "members": members, "size": len(members),
        "name": " · ".join(x for x in [str(main), who] if x),
        "scam_types": dict(stypes), "narratives": dict(narr), "products": dict(products),
        "persons": dict(persons.most_common(8)), "domains": dict(domains), "titles": [t for t, _ in titles.most_common(5)],
        "date_range": [dates[0], dates[-1]] if dates else [], "shared_indicators": shared[:25],
        "link_families": dict(fam_c), "internal_links": len(inner),
        "mean_internal_p": round(float(np.mean([l.p for l in inner])), 3) if inner else None,
    }


# ------------------------------------------------------------------------------ incremental assignment
def assign(new_id: str, new_f: dict, new_v: dict, items: dict, clustering: dict) -> dict:
    """Compare a new material with the analysed set and decide: duplicate / known campaign / candidate / NEW."""
    corpus = Corpus({**items, new_id: (new_f, new_v)})
    links = [pair(new_id, new_f, new_v, mid, f, v, corpus) for mid, (f, v) in items.items() if mid != new_id]
    links.sort(key=lambda l: -l.p)
    per_c = defaultdict(list)
    for l in links:
        c = clustering["campaign_of"].get(l.b)
        if c is not None:
            per_c[c].append(l)
    scores = []
    for c, ls in per_c.items():
        comp = sorted([l.p for l in ls if l.comparable], reverse=True)
        top = comp[:2] if comp else [0.0]
        mx = max(l.p for l in ls)
        # strong single link (>= 0.75) = variant of that member -> known campaign;
        # a single moderate link (0.55-0.75) to one member of a multi-narrative campaign -> at least 'candidate'
        score = max(float(np.mean(top)), mx if mx >= 0.75 else 0,
                    min(mx, config.ASSIGN_THRESHOLD - 0.01) if mx >= config.ASSIGN_THRESHOLD else 0)
        scores.append((score, c, ls))
    scores.sort(key=lambda t: -t[0])
    dups = [l for l in links if l.relation == "duplicate"]
    decision, camp = "new_campaign", None
    if scores and scores[0][0] >= config.ASSIGN_THRESHOLD:
        decision, camp = "known_campaign", scores[0][1]
        if len(scores) > 1 and scores[1][0] >= config.ASSIGN_THRESHOLD:
            decision = "merge_proposal"
    elif scores and scores[0][0] >= config.CANDIDATE_THRESHOLD:
        # a 'possible variant' needs at least some operator / kit / creative / narrative evidence;
        # sharing only the playbook (scam type, narrative template, famous face) => new campaign of a known type
        best_links = scores[0][2]
        non_weak = max((v for l in best_links for f, v in l.families.items()
                        if config.FAMILY_TIER.get(f) in ("S", "M") and f != "concept"), default=0)
        if non_weak >= 0.30:
            decision, camp = "candidate_review", scores[0][1]
        else:
            decision, camp = "new_campaign", None
            playbook_of = scores[0][1]
    if dups:
        decision = "duplicate" if decision != "merge_proposal" else decision
    similar_playbook = None
    if decision == "new_campaign" and scores and scores[0][0] >= config.SIMILAR_THRESHOLD:
        similar_playbook = scores[0][1]
    return {"decision": decision, "campaign": camp, "duplicates": [l.b for l in dups], "similar_playbook": similar_playbook,
            "campaign_scores": [(round(s, 3), c) for s, c, _ in scores[:5]], "links": links}
