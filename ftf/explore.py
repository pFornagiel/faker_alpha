"""Feature space: 2D projections of the content distance and alternative clusterings of the same materials.

What the map shows (position): the content (Gower) distance d between every pair of materials, embedded in 2D by
  mds   classical multidimensional scaling (Torgerson 1952): deterministic, keeps large distances faithful
  tsne  t-SNE (van der Maaten & Hinton 2008) on the precomputed d: keeps neighbourhoods, distorts global distances
Shared identifiers are not distances, so they do not move points; pairs that share one are returned as edges.

What the colours show (grouping), every method on the same matrices (D = 0 inside a must-link component, else d):
  faketrace  must-link + average linkage (UPGMA) on D cut at CAMPAIGN_CUT: the method used everywhere else
  content    average linkage on d alone, same cut: what the identifiers add
  single     single linkage on D, same cut: "close to anyone" -> chains
  complete   complete linkage on D, same cut: "close to everyone" -> strict
  hdbscan    HDBSCAN (Campello et al. 2013) on D, min_cluster_size = 2: density; sparse points are noise
  louvain    Louvain modularity communities (Blondel et al. 2008) on the graph of linked pairs weighted by p
Quality: silhouette (Rousseeuw 1987) on D, ARI (Hubert & Arabie 1985) vs FakeTrace and vs reference labels if present.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from . import config
from .cluster import distance_matrix

LABELS_CSV = config.DATA / "labels_dane.csv"

PROJECTIONS = {
    "mds": ("MDS", "Klasyczne skalowanie wielowymiarowe: punkty ułożone tak, by odległości na płaszczyźnie jak najwierniej "
                   "oddawały odległości treści d. Wynik jest deterministyczny; duże odległości są zachowane najlepiej."),
    "tsne": ("t-SNE", "Rzut, który zachowuje przede wszystkim sąsiedztwo: bliskie materiały lądują obok siebie, ale odległości "
                      "między odległymi grupami nie mają znaczenia. Ziarno losowe jest stałe, więc układ się nie zmienia."),
}

METHODS = {
    "faketrace": ("FakeTrace", "Wspólny identyfikator łączy zawsze; resztę grupuje średnie wiązanie (UPGMA) odległości D, "
                               "cięte na wysokości {cut}. Tej metody używa cały panel."),
    "content": ("Sama treść", "To samo średnie wiązanie i ten sam próg {cut}, ale tylko na odległości treści d — bez identyfikatorów. "
                              "Różnica względem FakeTrace pokazuje, co wnoszą domeny, piksele i kontakty."),
    "single": ("Pojedyncze wiązanie", "Grupy łączą się, gdy choć jedna para jest bliżej niż {cut}. Jeden materiał-łącznik "
                                      "potrafi skleić odległe grupy (efekt łańcucha)."),
    "complete": ("Pełne wiązanie", "Grupy łączą się dopiero, gdy każda para jest bliżej niż {cut}. Kampanie są ciaśniejsze, "
                                   "a materiały-łączniki zostają osobno."),
    "hdbscan": ("HDBSCAN", "Szuka gęstych skupisk bez progu odległości (najmniejsze skupisko: 2 materiały). Materiały, które "
                           "nie należą do żadnego gęstego skupiska, są szumem."),
    "louvain": ("Louvain", "Wykrywa społeczności w grafie powiązań (pary o relacji innej niż brak powiązania, waga = bliskość p): "
                           "grupy gęsto połączone w środku i słabo z resztą."),
}


def _cut(D: np.ndarray, method: str, t: float) -> np.ndarray:
    if len(D) < 2:
        return np.zeros(len(D), dtype=int)
    return fcluster(linkage(squareform(D, checks=False), method=method), t=t, criterion="distance")


def _louvain(ids: list[str], links) -> np.ndarray:
    import networkx as nx

    G = nx.Graph()
    G.add_nodes_from(ids)
    for l in links:
        if l.relation != "none":
            G.add_edge(l.a, l.b, weight=max(1e-3, l.p))
    comms = nx.community.louvain_communities(G, weight="weight", seed=0) if G.number_of_edges() else [{m} for m in ids]
    lab = {m: i for i, c in enumerate(sorted(comms, key=lambda c: (-len(c), min(c)))) for m in c}
    return np.array([lab[m] for m in ids])


def mds(d: np.ndarray) -> tuple[np.ndarray, float]:
    """Classical (Torgerson) MDS to 2D; returns coordinates and the share of variance the two axes keep."""
    n = len(d)
    if n < 3:
        return np.array([[float(i), 0.0] for i in range(n)]), 1.0
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ (d ** 2) @ J
    w, V = np.linalg.eigh(B)
    order = np.argsort(w)[::-1]
    w, V = w[order], V[:, order]
    pos = np.clip(w, 0, None)
    X = V[:, :2] * np.sqrt(pos[:2])
    for k in range(2):                                    # eigenvector sign is arbitrary; pin it for a stable layout
        j = int(np.argmax(np.abs(X[:, k])))
        if X[j, k] < 0:
            X[:, k] *= -1
    return X, float(pos[:2].sum() / pos.sum()) if pos.sum() > 0 else 1.0


def tsne(d: np.ndarray) -> np.ndarray | None:
    n = len(d)
    if n < 5:
        return None
    from sklearn.manifold import TSNE

    perplexity = float(max(2.0, min(30.0, (n - 1) / 3)))
    return TSNE(n_components=2, metric="precomputed", init="random", perplexity=perplexity, random_state=0).fit_transform(d)


def _normalise(X: np.ndarray) -> list[list[float]]:
    """Scale into [0, 1] keeping the aspect ratio; points that coincide are spread on a small circle."""
    X = np.asarray(X, dtype=float).copy()
    X -= X.min(0)
    X /= max(float(X.max()), 1e-9)
    groups = defaultdict(list)
    for i, (x, y) in enumerate(X):
        groups[(round(x, 3), round(y, 3))].append(i)
    for g in groups.values():
        if len(g) > 1:
            for k, i in enumerate(g):
                a = 2 * np.pi * k / len(g)
                X[i] += 0.025 * np.array([np.cos(a), np.sin(a)])
    return [[round(float(x), 4), round(float(y), 4)] for x, y in X]


def reference_labels(items: dict, path: Path = LABELS_CSV) -> dict[str, str]:
    """material id -> manual label from `case,label` rows (case = material id or name); empty when absent."""
    if not path.exists():
        return {}
    name2id = {str(f.get("name")): mid for mid, (f, _) in items.items()}
    out = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                key = row[0].strip()
                mid = key if key in items else name2id.get(key)
                if mid:
                    out[mid] = row[1].strip()
    return out


def _singletons_apart(lab: np.ndarray, noise: np.ndarray) -> np.ndarray:
    """Noise points become their own clusters for the scores (otherwise all noise would count as one group)."""
    lab = lab.astype(int).copy()
    nxt = int(lab.max(initial=0)) + 1
    for i in np.where(noise)[0]:
        lab[i] = nxt
        nxt += 1
    return lab


def _silhouette(D: np.ndarray, lab: np.ndarray) -> float | None:
    k = len(set(lab.tolist()))
    if not 2 <= k <= len(lab) - 1:
        return None
    from sklearn.metrics import silhouette_score

    return round(float(silhouette_score(D, lab, metric="precomputed")), 3)


def _ari(a: list, b: list) -> float | None:
    if len(a) < 2:
        return None
    from sklearn.metrics import adjusted_rand_score

    return round(float(adjusted_rand_score(a, b)), 3)


def _colour(lab: np.ndarray, noise: np.ndarray, ref: np.ndarray, ref_slot: dict[int, int]) -> list[int | None]:
    """Give each multi-material cluster the colour of the FakeTrace campaign it overlaps most, so the same group
    keeps its colour when the method changes; clusters without a counterpart take the next free colour."""
    members = defaultdict(list)
    for i, x in enumerate(lab):
        if not noise[i]:
            members[int(x)].append(i)
    used: set[int] = set()
    slot_of: dict[int, int] = {}
    for c, ms in sorted(members.items(), key=lambda kv: (-len(kv[1]), kv[1][0])):
        if len(ms) < 2:
            continue
        overlap = defaultdict(int)
        for i in ms:
            if int(ref[i]) in ref_slot and ref_slot[int(ref[i])] not in used:
                overlap[ref_slot[int(ref[i])]] += 1
        if overlap:
            slot = max(overlap, key=lambda s: (overlap[s], -s))
        else:
            free = [s for s in range(8) if s not in used and s not in ref_slot.values()] or [s for s in range(8) if s not in used]
            if not free:
                continue
            slot = free[0]
        used.add(slot)
        slot_of[c] = slot
    return [None if noise[i] else slot_of.get(int(x)) for i, x in enumerate(lab)]


def feature_space(items: dict, cl: dict, ids: list[str], slot_of_campaign) -> dict:
    """Projections + every clustering method with its scores, for the ids in display order."""
    n = len(ids)
    idx = {m: i for i, m in enumerate(ids)}
    links = cl["links"]
    d = np.ones((n, n))
    np.fill_diagonal(d, 0.0)
    for l in links:
        d[idx[l.a], idx[l.b]] = d[idx[l.b], idx[l.a]] = l.distance
    D, _ = distance_matrix(ids, links)
    cut = config.CAMPAIGN_CUT

    X, fit = mds(d)
    projections = {"mds": {"xy": _normalise(X), "fit": round(fit, 3)}}
    try:
        T = tsne(d)
    except Exception:
        T = None
    if T is not None:
        projections["tsne"] = {"xy": _normalise(T), "fit": None}
    for k, v in projections.items():
        v["key"], v["label"], v["hint"] = k, *PROJECTIONS[k]

    no_noise = np.zeros(n, dtype=bool)
    ft = np.array([cl["campaign_of"][m] for m in ids])
    raw: dict[str, tuple[np.ndarray, np.ndarray]] = {"faketrace": (ft, no_noise)}
    raw["content"] = (_cut(d, "average", cut), no_noise)
    raw["single"] = (_cut(D, "single", cut), no_noise)
    raw["complete"] = (_cut(D, "complete", cut), no_noise)
    hd = cl.get("hdbscan") or {}
    if hd:
        h = np.array([hd.get(m, -1) for m in ids])
        raw["hdbscan"] = (np.where(h < 0, 0, h), h < 0)
    try:
        raw["louvain"] = (_louvain(ids, links), no_noise)
    except Exception:
        pass

    gold = reference_labels(items)
    gold_idx = [i for i, m in enumerate(ids) if m in gold]
    ref_slot = {ci: s for ci in set(ft.tolist()) if (s := slot_of_campaign(ci)) is not None}
    ft_scored = _singletons_apart(ft, no_noise)

    methods = []
    for key, (lab, noise) in raw.items():
        scored = _singletons_apart(lab, noise)
        sizes = defaultdict(int)
        for i, x in enumerate(lab):
            if not noise[i]:
                sizes[int(x)] += 1
        label, hint = METHODS[key]
        methods.append({
            "key": key, "label": label, "hint": hint.format(cut=cut),
            "cluster": [int(x) for x in scored], "color": _colour(lab, noise, ft, ref_slot), "noise": [bool(x) for x in noise],
            "n_clusters": sum(1 for s in sizes.values() if s >= 2), "n_singletons": sum(1 for s in sizes.values() if s == 1),
            "n_noise": int(noise.sum()), "silhouette": _silhouette(D, scored),
            "ari_faketrace": _ari(ft_scored.tolist(), scored.tolist()),
            "ari_labels": _ari([gold[ids[i]] for i in gold_idx], [int(scored[i]) for i in gold_idx]) if len(gold_idx) >= 2 else None,
        })

    edges = sorted({(min(idx[l.a], idx[l.b]), max(idx[l.a], idx[l.b])) for l in links if l.must_link})
    return {"projections": projections, "methods": methods, "identifier_edges": [list(e) for e in edges],
            "labels": {"file": str(LABELS_CSV.relative_to(config.ROOT)), "n": len(gold_idx)} if gold_idx else None,
            "campaign_cut": cut}
