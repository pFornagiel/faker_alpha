"""Graph representation: NetworkX (analysis), pyvis (interactive HTML in the UI) and Neo4j export.

Node labels : Material, Campaign, Family, Domain, Indicator (pixel/TDS/endpoint/...), Person, Product
Relations   : (Material)-[:LINKED {p, distance, relation, explanation}]-(Material)
              (Material)-[:IN_CAMPAIGN]->(Campaign)-[:IN_FAMILY]->(Family)
              (Material)-[:USES_DOMAIN]->(Domain), (Material)-[:HAS_INDICATOR {type}]->(Indicator)
              (Material)-[:DEPICTS {source: face|text}]->(Person), (Material)-[:PROMOTES]->(Product)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import networkx as nx

from . import config

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
           "#469990", "#dcbeff", "#9a6324", "#800000", "#aaffc3", "#808000", "#000075", "#a9a9a9"]
IND_TYPES_IN_GRAPH = set(config.IDENTIFIER_GROUP) - {"landing_domain", "page_host", "redirect_domain", "ocr_domain", "product"}


def build_graph(items: dict, clustering: dict, profiles: list[dict], with_entities: bool = True) -> nx.Graph:
    G = nx.Graph()
    for ci, prof in enumerate(profiles):
        G.add_node(f"C{ci + 1}", kind="Campaign", label=f"C{ci + 1}: {prof['name'][:40]}", size=prof["size"])
    multi = {fi for fi, fam in enumerate(clustering["families"])          # families spanning >= 2 campaigns
             if len({clustering["campaign_of"][m] for m in fam}) > 1}
    for fi in multi:
        G.add_node(f"F{fi + 1}", kind="Family", label=f"Rodzina F{fi + 1}", size=len(clustering["families"][fi]))
    for mid, (f, _) in items.items():
        ci = clustering["campaign_of"].get(mid, -1)
        title = (f.get("text", {}).get("titles") or [f.get("name")])[0]
        G.add_node(mid, kind="Material", label=str(f.get("name"))[:30], title=title, campaign=ci + 1,
                   domains=", ".join(f.get("web", {}).get("landing_domains", [])[:3]))
        if ci >= 0:
            G.add_edge(mid, f"C{ci + 1}", kind="IN_CAMPAIGN")
            fi = clustering["family_of"].get(mid)
            if fi in multi:
                G.add_edge(f"C{ci + 1}", f"F{fi + 1}", kind="IN_FAMILY")
        if with_entities:
            for d in f.get("web", {}).get("landing_domains", []):
                G.add_node(f"dom:{d}", kind="Domain", label=d)
                G.add_edge(mid, f"dom:{d}", kind="USES_DOMAIN")
            for t, vals in f.get("indicators", {}).items():
                if t in IND_TYPES_IN_GRAPH:
                    for v in vals[:6]:
                        G.add_node(f"{t}:{v}", kind="Indicator", label=f"{t}: {v[:28]}", itype=t)
                        G.add_edge(mid, f"{t}:{v}", kind="HAS_INDICATOR", itype=t)
            for p in set(f.get("persons_visual", [])):
                G.add_node(f"person:{p}", kind="Person", label=p)
                G.add_edge(mid, f"person:{p}", kind="DEPICTS", source="face")
            for p in set(f.get("persons_named", [])) - set(f.get("persons_visual", [])):
                G.add_node(f"person:{p}", kind="Person", label=p)
                G.add_edge(mid, f"person:{p}", kind="DEPICTS", source="text")
            prod = f.get("llm", {}).get("product_or_platform_name")
            if prod:
                G.add_node(f"product:{prod.lower()}", kind="Product", label=prod)
                G.add_edge(mid, f"product:{prod.lower()}", kind="PROMOTES")
    for l in clustering["links"]:
        if l.relation != "none":
            G.add_edge(l.a, l.b, kind="LINKED", p=round(l.p, 3), distance=round(l.distance, 3), relation=l.relation,
                       explanation=l.explain())
    if with_entities:   # drop indicator/entity nodes connected to a single material (no linking value)
        G.remove_nodes_from([n for n, d in list(G.nodes(data=True))
                             if d.get("kind") in ("Indicator", "Domain", "Product", "Person") and G.degree(n) < 2])
    return G


def to_pyvis_html(G: nx.Graph, path: Path, height: str = "720px") -> Path:
    from pyvis.network import Network

    net = Network(height=height, width="100%", bgcolor="#ffffff", font_color="#222", notebook=False, cdn_resources="in_line")
    net.set_options(json.dumps({
        "physics": {"barnesHut": {"gravitationalConstant": -9000, "centralGravity": 0.35, "springLength": 130},
                    "stabilization": {"enabled": True, "iterations": 600, "fit": True}, "minVelocity": 1.5},
        "interaction": {"hover": True, "tooltipDelay": 120, "navigationButtons": True},
        "edges": {"smooth": {"type": "continuous"}}}))
    shapes = {"Material": "dot", "Campaign": "star", "Family": "triangle", "Domain": "square", "Indicator": "diamond",
              "Person": "ellipse", "Product": "box"}
    for n, d in G.nodes(data=True):
        kind = d.get("kind")
        color = "#cccccc"
        if kind == "Material":
            c = d.get("campaign", 0)
            color = PALETTE[(c - 1) % len(PALETTE)] if c else "#999"
        elif kind == "Campaign":
            color = PALETTE[(int(n[1:]) - 1) % len(PALETTE)]
        elif kind == "Person":
            color = "#ffd166"
        elif kind == "Indicator":
            color = "#ef476f"
        elif kind == "Domain":
            color = "#118ab2"
        elif kind == "Product":
            color = "#06d6a0"
        title = f"{kind}: {d.get('label')}"
        if kind == "Material":
            title += f"\n{d.get('title', '')}\n{d.get('domains', '')}"
        net.add_node(n, label=d.get("label", n), title=title, shape=shapes.get(kind, "dot"), color=color,
                     size=28 if kind == "Campaign" else 16 if kind == "Material" else 10)
    for a, b, d in G.edges(data=True):
        if d.get("kind") == "LINKED":
            rel = d.get("relation")
            col = {"duplicate": "#000000", "same_campaign": "#d62828", "similar": "#f4a261"}.get(rel, "#bbbbbb")
            net.add_edge(a, b, value=max(0.5, d["p"] * 6), color=col, title=f"{rel} p={d['p']}\n{d.get('explanation', '')}",
                         dashes=rel == "similar")
        else:
            net.add_edge(a, b, color="#dddddd", title=d.get("kind"), width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(path), notebook=False)
    html = path.read_text(encoding="utf-8")
    hook = ("network.once('stabilizationIterationsDone', function(){ network.setOptions({physics:false}); network.fit(); });"
            "setTimeout(function(){ network.fit(); }, 2500);")
    i = html.rfind("return network;")
    if i > 0:
        html = html[:i] + hook + "\n" + html[i:]
        path.write_text(html, encoding="utf-8")
    return path


def _q(s) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def to_cypher(G: nx.Graph, path: Path | None = None) -> str:
    lines = ["// FakeTrace export — load with: cat graph.cypher | cypher-shell -u neo4j -p <pwd>",
             "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Node) REQUIRE n.uid IS UNIQUE;"]
    for n, d in G.nodes(data=True):
        props = ", ".join(f"{k}: {_q(v)}" for k, v in d.items() if k != "kind")
        lines.append(f"MERGE (n:Node:{d.get('kind', 'Node')} {{uid: {_q(n)}}}) SET n += {{{props}}};")
    for a, b, d in G.edges(data=True):
        rel = d.get("kind", "REL")
        props = ", ".join(f"{k}: {_q(v)}" for k, v in d.items() if k != "kind")
        lines.append(f"MATCH (a:Node {{uid: {_q(a)}}}), (b:Node {{uid: {_q(b)}}}) MERGE (a)-[r:{rel}]->(b) SET r += {{{props}}};")
    txt = "\n".join(lines)
    if path:
        path.write_text(txt, encoding="utf-8")
    return txt


def push_neo4j(G: nx.Graph) -> str:
    """Push to a running Neo4j (docker compose --profile neo4j up). Env: NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD."""
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return "NEO4J_URI not set — use the Cypher export instead"
    from neo4j import GraphDatabase

    drv = GraphDatabase.driver(uri, auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "neo4j")))
    with drv.session() as s:
        s.run("MATCH (n:Node) DETACH DELETE n")
        for stmt in to_cypher(G).split("\n")[1:]:
            if stmt.strip() and not stmt.startswith("//"):
                s.run(stmt)
    drv.close()
    return f"pushed {G.number_of_nodes()} nodes / {G.number_of_edges()} edges to {uri}"
