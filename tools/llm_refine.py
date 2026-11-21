"""Iterative LLM feature discovery ("from the car model infer the body type", done in a loop).

1. Build campaigns; find *ambiguous* groups: playbook families spanning several campaigns and
   borderline links (0.30 <= p < 0.55).
2. Show the LLM compact profiles of those materials and ask it to PROPOSE new discriminative
   attributes (name, description, allowed values) and FILL them for every material.
3. Accepted attributes are appended to data/cache/llm_extra_schema.json -> `ftf/llm.py` adds them to
   the extraction schema for every future material; filled values are stored per material in
   data/cache/llm_extra_values.json and compared in `similarity.py` (concept family, weak-medium).

    .venv/bin/python tools/llm_refine.py [--max-groups 4]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftf import config  # noqa: E402
from ftf.cluster import build  # noqa: E402
from ftf.store import Store  # noqa: E402

SCHEMA_F = config.CACHE / "llm_extra_schema.json"
VALUES_F = config.CACHE / "llm_extra_values.json"
EXISTING = ["scam_type", "narrative_template", "creative_format", "impersonated_persons", "impersonated_brands",
            "spoofed_media_outlet", "product_or_platform_name", "promised_benefit", "call_to_action", "urgency_cues"]

PROMPT = """Jesteś analitykiem CERT. Poniżej profile materiałów (reklamy/strony oszustw), które system
uznał za NIEJEDNOZNACZNE: mają podobny playbook, ale nie wiadomo, czy pochodzą od tego samego operatora.
Istniejące atrybuty: {existing}.
Zaproponuj od 2 do 4 NOWYCH atrybutów (krótkie nazwy snake_case, po angielsku), które najlepiej
pozwolą ROZRÓŻNIĆ lub POŁĄCZYĆ te materiały (np. styl nazw fikcyjnych platform, motyw przewodni
historii, rola celebryty, sposób przejścia do formularza, waluta/kwota wejścia, język/kalki językowe).
Każdy atrybut: name, description, values = mapa NAZWA_MATERIAŁU -> krótka znormalizowana wartość
(małe litery, maks. 4 słowa; "unknown" gdy brak danych). Zwróć WYŁĄCZNIE JSON:
{{"attributes":[{{"name":"...","description":"...","values":{{"<material>":"<value>"}}}}]}}

MATERIAŁY:
{materials}"""


def profile(f: dict) -> str:
    llm = f.get("llm", {})
    t = f.get("text", {})
    return json.dumps({
        "material": f["name"], "titles": t.get("titles", [])[:2], "summary": llm.get("summary_pl"),
        "product": llm.get("product_or_platform_name"), "persons": f.get("persons_named", [])[:4],
        "domains": f.get("web", {}).get("landing_domains", [])[:3], "keywords": t.get("keywords", [])[:8],
        "phrases": llm.get("distinctive_phrases", [])[:4], "excerpt": t.get("excerpt", "")[:500],
    }, ensure_ascii=False)


def ask(prompt: str) -> dict | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    r = subprocess.run([exe, "-p", "--model", config.LLM_MODEL, "--output-format", "json", "--tools", "",
                        "--no-session-persistence"], input=prompt, capture_output=True, text=True, timeout=180)
    try:
        res = json.loads(r.stdout).get("result", "")
        return json.loads(re.search(r"\{.*\}", res, re.S).group(0))
    except Exception:
        return None


def main(max_groups: int):
    st = Store()
    items = st.all()
    cl = build(items)
    groups = []
    for fam in cl["families"]:
        camps = {cl["campaign_of"][m] for m in fam}
        if len(camps) > 1:
            groups.append(sorted(fam))
    for l in cl["links"]:
        if 0.30 <= l.p < config.LINK_THRESHOLD and cl["campaign_of"][l.a] != cl["campaign_of"][l.b]:
            g = sorted({l.a, l.b})
            if not any(set(g) <= set(x) for x in groups):
                groups.append(g)
    schema = json.loads(SCHEMA_F.read_text()) if SCHEMA_F.exists() else []
    values = json.loads(VALUES_F.read_text()) if VALUES_F.exists() else {}
    for g in groups[:max_groups]:
        mats = "\n".join(profile(items[m][0]) for m in g)
        out = ask(PROMPT.format(existing=", ".join(EXISTING + [a["name"] for a in schema]), materials=mats))
        if not out:
            print("no answer for", [items[m][0]["name"] for m in g])
            continue
        name2id = {items[m][0]["name"]: m for m in g}
        for a in out.get("attributes", []):
            nm = re.sub(r"[^a-z0-9_]", "_", a.get("name", "").lower())[:40]
            if not nm or nm in EXISTING:
                continue
            if nm not in [x["name"] for x in schema]:
                schema.append({"name": nm, "description": a.get("description", "")[:200]})
            for mname, v in (a.get("values") or {}).items():
                mid = name2id.get(str(mname))
                if mid and v and str(v).lower() != "unknown":
                    values.setdefault(mid, {})[nm] = str(v).lower()[:60]
            print(f"+ {nm}: {a.get('description', '')[:90]}  {a.get('values')}")
    SCHEMA_F.write_text(json.dumps(schema, ensure_ascii=False, indent=1))
    VALUES_F.write_text(json.dumps(values, ensure_ascii=False, indent=1))
    print(f"schema: {len(schema)} extra attributes; values for {len(values)} materials -> {SCHEMA_F}")
    # apply to already-stored materials (new materials get them via the extended extraction schema)
    from ftf.ingest import Material

    for mid, (f, v) in items.items():
        if mid in values:
            f2 = {k: x for k, x in f.items() if not k.startswith("_")}
            f2.setdefault("llm", {})["extra"] = {**(f2["llm"].get("extra") or {}), **values[mid]}
            st.upsert(Material.from_dict(f["_material"]), f2, v)
    print("store updated")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-groups", type=int, default=4)
    main(ap.parse_args().max_groups)
