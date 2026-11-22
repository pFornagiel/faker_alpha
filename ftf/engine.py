"""High-level API used by the UI, CLI and scheduler."""
from __future__ import annotations

import logging
from pathlib import Path

from . import config, ingest
from .cluster import assign, build, profile
from .graph import build_graph, to_cypher, to_pyvis_html
from .pipeline import analyze
from .store import Store

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()
        self._clustering = None

    # ------------------------------------------------------------------ ingest
    def add(self, m: ingest.Material, use_llm: bool = True, progress=None, force: bool = False,
            enrich_online: bool | None = None) -> tuple[dict, dict]:
        if self.store.has(m.id) and not force:
            f, v = self.store.all()[m.id]
            return f, v
        f, v = analyze(m, use_llm=use_llm, progress=progress, enrich_online=enrich_online)
        self.store.upsert(m, f, v)
        self._clustering = None
        return f, v

    def add_dataset(self, root: str | Path, use_llm: bool = True, progress=None, force: bool = False,
                    enrich_online: bool | None = None) -> int:
        """`enrich_online`: None = follow FTF_ENRICH, False = no RDAP / DNS / crt.sh lookups (the demo dataset)."""
        ms = ingest.load_dataset(root)
        for i, m in enumerate(ms):
            if progress:
                progress(f"[{i + 1}/{len(ms)}] {m.name}")
            self.add(m, use_llm=use_llm, progress=None, force=force, enrich_online=enrich_online)
        return len(ms)

    # ------------------------------------------------------------------ analysis
    def clustering(self, refresh: bool = False) -> dict:
        if self._clustering is None or refresh:
            items = self.store.all()
            cl = build(items)
            cl["profiles"] = [profile(c, items, cl["links"]) for c in cl["campaigns"]]
            self._clustering = cl
        return self._clustering

    def analyse_new(self, m: ingest.Material, use_llm: bool = True, progress=None, keep: bool = True) -> dict:
        """Full flow for one new material: features -> compare with the set -> decision (+ optional storage)."""
        items = dict(self.store.all())
        cl = self.clustering() if items else {"campaign_of": {}, "campaigns": [], "profiles": []}
        f, v = analyze(m, use_llm=use_llm, progress=progress)
        res = assign(m.id, f, v, {k: x for k, x in items.items() if k != m.id}, cl) if items else \
            {"decision": "new_campaign", "campaign": None, "links": [], "campaign_scores": [], "duplicates": [],
             "similar_family": None, "nearest": None}
        if keep:
            self.store.upsert(m, f, v)
            self.store.log("analysed", {"id": m.id, "name": m.name, "decision": res["decision"], "campaign": res["campaign"]})
            self._clustering = None
        res["features"], res["vectors"] = f, v
        res["material"] = m
        return res

    def graph_html(self, path: Path | None = None, with_entities: bool = True) -> Path:
        cl = self.clustering()
        G = build_graph(self.store.all(), cl, cl["profiles"], with_entities=with_entities)
        return to_pyvis_html(G, path or config.EXPORTS / "graph.html")

    def export_cypher(self, path: Path | None = None) -> Path:
        cl = self.clustering()
        G = build_graph(self.store.all(), cl, cl["profiles"])
        p = path or config.EXPORTS / "graph.cypher"
        to_cypher(G, p)
        return p
