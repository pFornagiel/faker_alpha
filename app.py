"""FakeTrace — Streamlit demonstrator ("Kolekcjoner Fejków / Follow the Fake", HackNation 2026).

Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ftf import config, ingest
from ftf.engine import Engine
from ftf.similarity import FAMILY_PL

logging.basicConfig(level=logging.WARNING)
st.set_page_config(page_title="FakeTrace – Follow the Fake", page_icon="🕵️", layout="wide")

DECISION_PL = {
    "duplicate": ("🟣 DUPLIKAT", "Materiał jest duplikatem już przeanalizowanego zgłoszenia."),
    "known_campaign": ("🔴 ZNANA KAMPANIA", "Materiał przypisano do istniejącej kampanii."),
    "merge_proposal": ("🟠 PROPOZYCJA SCALENIA", "Materiał silnie łączy się z więcej niż jedną kampanią — możliwe, że to jedna kampania."),
    "candidate_review": ("🟡 MOŻLIWY WARIANT", "Podobieństwo umiarkowane — wymaga weryfikacji analityka."),
    "new_campaign": ("🟢 NOWY WZORZEC", "Brak wystarczających powiązań — prawdopodobnie nowa kampania."),
}


@st.cache_resource
def engine() -> Engine:
    return Engine()


def name_of(items, mid):
    return items[mid][0].get("name", mid) if mid in items else mid


def show_links(links, items, top=10):
    rows = []
    for l in links[:top]:
        rows.append({"materiał": name_of(items, l.b), "p": round(l.p, 3), "relacja": l.relation,
                     "rodziny dowodów": ", ".join(f"{FAMILY_PL.get(k, k)}={v:.2f}" for k, v in sorted(l.families.items(), key=lambda kv: -kv[1])),
                     "uzasadnienie": l.explain(5)})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def show_evidence(link):
    ev = pd.DataFrame([e.as_dict() for e in link.evidence])
    if ev.empty:
        st.caption("brak dowodów")
        return
    ev["rodzina"] = ev["family"].map(lambda f: FAMILY_PL.get(f, f))
    st.dataframe(ev[["rodzina", "signal", "detail", "weight", "ignored"]].sort_values("weight", ascending=False),
                 use_container_width=True, hide_index=True)


def show_features(f: dict):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🌐 Warstwa web / infrastruktura**")
        w = f.get("web", {})
        st.write({"domeny docelowe": w.get("landing_domains"), "URL": w.get("landing_urls", [])[:3],
                  "łańcuchy przekierowań": w.get("redirect_chains"), "IP": w.get("ips"),
                  "nagłówki serwera": w.get("server_headers"), "za Cloudflare": f.get("behind_cloudflare"),
                  "metadane domen (RDAP/DNS/crt.sh/CERT PL)": f.get("infra")})
        st.markdown("**🔑 Wskaźniki (indicators)**")
        ind = f.get("indicators", {})
        st.dataframe(pd.DataFrame([{"typ": k, "wartości": ", ".join(v[:6])} for k, v in ind.items()]),
                     use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**📝 Tekst / narracja**")
        t = f.get("text", {})
        st.write({"tytuły": t.get("titles"), "szablony tytułów": t.get("title_templates"), "słowa kluczowe": t.get("keywords"),
                  "kwoty": t.get("amounts"), "osoby (tekst)": f.get("persons_named"), "osoby (twarze)": f.get("persons_visual"),
                  "marki": t.get("brands_text"), "media": t.get("media_text"), "daty": f.get("dates")})
        st.markdown(f"**🤖 Atrybuty LLM** (backend: `{f.get('llm', {}).get('_backend')}`)")
        st.json({k: v for k, v in f.get("llm", {}).items() if not k.startswith("_")}, expanded=False)
    imgs = f.get("images", [])
    if imgs:
        st.markdown("**🖼️ Kreacje / zrzuty / klatki wideo** (OCR, twarze)")
        cols = st.columns(min(4, len(imgs)))
        for i, im in enumerate(imgs[:12]):
            with cols[i % len(cols)]:
                if Path(im["src"]).exists():
                    st.image(im["src"], use_container_width=True)
                who = [fc["identity"] or f"nieznana ({fc['sim']:.2f})" for fc in im.get("faces", [])]
                st.caption(f"{im['kind']} · twarze: {', '.join(who) or '—'}\n\nOCR: {im.get('ocr_text', '')[:160]}")
    links_on_creative = sorted(set(f.get("indicators", {}).get("ocr_domain", [])) |
                               {q for im in imgs for q in im.get("qr", [])})
    if links_on_creative:
        st.markdown("**🔗 Linki/domeny odczytane z kreacji (OCR/QR)** — można je przechwycić i przeanalizować:")
        for u in links_on_creative[:6]:
            if st.button(f"Przechwyć i analizuj: {u}", key=f"cap_{u}"):
                from ftf.capture import capture_url

                url = u if u.startswith("http") else f"https://{u}/"
                with st.spinner(f"Przechwytywanie {url} …"):
                    m2 = ingest.from_url(url, capture_url(url))
                    st.session_state["last"] = engine().analyse_new(m2, use_llm=True, keep=True)
                st.rerun()
    if f.get("notes"):
        st.warning("Uwagi / braki danych: " + "; ".join(f["notes"]))


eng = engine()
items = eng.store.all()
st.sidebar.title("🕵️ FakeTrace")
st.sidebar.caption("Łączenie pozornie niezależnych reklam-oszustw w kampanie — z uzasadnieniem każdej krawędzi.")
st.sidebar.metric("Materiały w bazie", len(items))
use_llm = st.sidebar.toggle("Atrybuty LLM (claude CLI / Gemini / reguły)", value=True)
with st.sidebar.expander("📥 Wczytaj zbiór (folder z przypadkami)"):
    root = st.text_input("Ścieżka", str(config.DATA / "organizer" / "dane"))
    if st.button("Wczytaj / dociąż"):
        with st.status("Analiza zbioru…", expanded=True) as s:
            n = eng.add_dataset(root, use_llm=use_llm, progress=lambda m: s.write(m))
            s.update(label=f"Wczytano {n} przypadków", state="complete")
        st.rerun()
if st.sidebar.button("🔄 Przelicz klastry"):
    eng.clustering(refresh=True)
    st.rerun()

tabs = st.tabs(["🔎 Analiza materiału", "🧩 Kampanie", "🕸️ Graf powiązań", "🔗 Powiązania", "⏱️ Scheduler", "📚 Metodyka"])

# =============================================================================== analysis
with tabs[0]:
    st.subheader("Analiza nowego materiału względem bazy")
    mode = st.radio("Wejście", ["URL", "Plik (zrzut ekranu / wideo / HTML / HAR / ZIP)", "Tekst / nazwa produktu"], horizontal=True)
    keep = st.checkbox("Dodaj do bazy po analizie", value=True)
    m = None
    if mode == "URL":
        url = st.text_input("Adres reklamy / strony docelowej / biblioteki reklam", placeholder="https://…")
        render = st.checkbox("Renderuj w headless Chromium (Playwright)", value=True)
        if st.button("Analizuj URL", type="primary") and url:
            from ftf.capture import capture_url

            with st.spinner("Pobieranie (3 profile klienta, wykrywanie cloakingu)…"):
                cap = capture_url(url, render=render)
            st.write({"profile": cap["profiles"], "cloaking": cap.get("cloaking", False), "uwagi": cap["notes"]})
            m = ingest.from_url(url, cap)
    elif mode.startswith("Plik"):
        up = st.file_uploader("Plik", type=None)
        if st.button("Analizuj plik", type="primary") and up:
            m = ingest.from_upload(up.name, up.getvalue())
    else:
        txt = st.text_area("Tekst reklamy, nazwa produktu lub lista linków")
        if st.button("Analizuj tekst", type="primary") and txt:
            m = ingest.from_text(txt)
            hits = []
            q = txt.lower()
            for mid, (f, _) in items.items():
                hay = json.dumps(f.get("llm", {}), ensure_ascii=False).lower() + " ".join(f.get("text", {}).get("titles", [])).lower()
                if q[:40] in hay:
                    hits.append(f.get("name"))
            if hits:
                st.info(f"Bezpośrednie trafienia w bazie (nazwa/produkt): {hits}")
            if len(txt) < 80 and not txt.startswith("http"):
                from ftf import scheduler, sources

                with st.spinner("Szukam w bibliotekach reklam (Microsoft, Google ATC, Meta API*) …"):
                    found = []
                    for fn in (sources.ms_adlib_search, sources.google_atc_suggest, sources.meta_api_search):
                        try:
                            found += fn(txt)
                        except Exception as exc:
                            st.caption(f"{fn.__name__}: {exc}")
                    for r in found:
                        r["score"], r["why"] = scheduler.suspicion(r)
                st.session_state["lib_hits"] = sorted(found, key=lambda r: -r["score"])
    if st.session_state.get("lib_hits"):
        st.markdown("**Trafienia w bibliotekach reklam** (*Meta tylko z `META_ACCESS_TOKEN`)")
        st.dataframe(pd.DataFrame(st.session_state["lib_hits"])[[c for c in ["score", "source", "advertiser", "name", "title", "url", "domain", "why"]
                                                                   if c in pd.DataFrame(st.session_state["lib_hits"]).columns]],
                     use_container_width=True, hide_index=True)
    if m is not None:
        with st.status("Ekstrakcja cech…", expanded=False) as s:
            res = eng.analyse_new(m, use_llm=use_llm, keep=keep, progress=lambda x: s.write(x))
            s.update(label=f"Gotowe ({res['features'].get('elapsed_s')} s)", state="complete")
        st.session_state["last"] = res
    res = st.session_state.get("last")
    if res:
        items = eng.store.all()
        lab, desc = DECISION_PL[res["decision"]]
        cl = eng.clustering()
        camp_txt = ""
        if res["campaign"] is not None and res["campaign"] < len(cl.get("profiles", [])):
            camp_txt = f" → **C{res['campaign'] + 1}: {cl['profiles'][res['campaign']]['name']}**"
        st.markdown(f"### {lab}{camp_txt}")
        if res.get("similar_playbook") is not None and res["similar_playbook"] < len(cl.get("profiles", [])):
            st.info(f"Nowa kampania, ale podobny playbook do C{res['similar_playbook'] + 1}: "
                    f"{cl['profiles'][res['similar_playbook']]['name']} (brak wspólnych śladów operatora/kitu/kreacji)")
        st.caption(desc + f"  Wyniki kampanii (śr. top-2 p): {res['campaign_scores']}")
        st.markdown("#### Najbardziej podobne materiały (z uzasadnieniem)")
        show_links(res["links"], items)
        if res["links"]:
            pick = st.selectbox("Szczegóły dowodów dla pary", [f"{name_of(items, l.b)} (p={l.p:.2f})" for l in res["links"][:10]])
            idx = [f"{name_of(items, l.b)} (p={l.p:.2f})" for l in res["links"][:10]].index(pick)
            show_evidence(res["links"][idx])
        st.markdown("#### Wyekstrahowane cechy")
        show_features(res["features"])

# =============================================================================== campaigns
with tabs[1]:
    if not items:
        st.info("Baza jest pusta — wczytaj zbiór w panelu bocznym.")
    else:
        cl = eng.clustering()
        st.subheader(f"{len(cl['campaigns'])} kampanii · {len(cl['families'])} rodzin (playbooków) · {len(cl['duplicates'])} grup duplikatów")
        rows = []
        for ci, p in enumerate(cl["profiles"]):
            rows.append({"kampania": f"C{ci + 1}", "nazwa": p["name"], "liczność": p["size"],
                         "materiały": ", ".join(name_of(items, mm) for mm in p["members"]),
                         "typ": ", ".join(p["scam_types"]), "osoby": ", ".join(list(p["persons"])[:4]),
                         "domeny": ", ".join(list(p["domains"])[:4]), "okres": " → ".join(p["date_range"]),
                         "śr. p": p["mean_internal_p"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        for ci, p in enumerate(cl["profiles"]):
            with st.expander(f"C{ci + 1} · {p['name']} · {p['size']} mat."):
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown("**Wspólne ślady (shared indicators)**")
                    if p["shared_indicators"]:
                        st.dataframe(pd.DataFrame(p["shared_indicators"])[["type", "value", "count"]], hide_index=True, use_container_width=True)
                    st.markdown("**Warianty przekazu w kampanii:** " + " · ".join(
                        "{" + ", ".join(name_of(items, x) for x in g) + "}" for g in cl.get("variants", {}).get(ci, [])))
                    st.markdown("**Tytuły:** " + " | ".join(p["titles"]))
                    st.write({"narracje": p["narratives"], "produkty": p["products"], "rodziny dowodów (wewn.)": p["link_families"]})
                with c2:
                    for mm in p["members"][:6]:
                        f = items[mm][0]
                        im = next((x["src"] for x in f.get("images", []) if Path(x["src"]).exists()), None)
                        if im:
                            st.image(im, caption=f.get("name"), use_container_width=True)
                        else:
                            st.caption(f"{f.get('name')}: {(f.get('text', {}).get('titles') or [''])[0][:80]}")
        if cl["duplicates"]:
            st.markdown("**Duplikaty:** " + "; ".join(" = ".join(name_of(items, x) for x in g) for g in cl["duplicates"]))
        st.markdown("**Rodziny (ten sam playbook, możliwie różni operatorzy):** " +
                    "; ".join("{" + ", ".join(name_of(items, x) for x in fam) + "}" for fam in cl["families"] if len(fam) > 1))
        if cl.get("hdbscan"):
            st.caption("Baseline HDBSCAN (na 1-p): " + json.dumps({name_of(items, k): v for k, v in cl["hdbscan"].items()}, ensure_ascii=False))

# =============================================================================== graph
with tabs[2]:
    if items:
        c1, c2 = st.columns([1, 3])
        with c1:
            ent = st.checkbox("Pokaż węzły śladów (domeny, piksele, osoby…)", value=True)
            if st.button("Eksport Cypher (Neo4j)"):
                st.success(f"Zapisano: {eng.export_cypher()}")
            if st.button("Wyślij do Neo4j (NEO4J_URI)"):
                from ftf.graph import build_graph, push_neo4j

                cl = eng.clustering()
                st.info(push_neo4j(build_graph(items, cl, cl["profiles"])))
            st.caption("Krawędzie: czerwone = ta sama kampania, pomarańczowe przerywane = podobny playbook, czarne = duplikat. "
                       "Najedź na krawędź, aby zobaczyć uzasadnienie.")
        with c2:
            p = eng.graph_html(config.EXPORTS / "graph_ui.html", with_entities=ent)
            components.html(p.read_text(encoding="utf-8"), height=760, scrolling=True)

# =============================================================================== links
with tabs[3]:
    if items:
        cl = eng.clustering()
        rel = st.multiselect("Relacje", ["duplicate", "same_campaign", "similar", "none"], default=["duplicate", "same_campaign", "similar"])
        links = sorted([l for l in cl["links"] if l.relation in rel], key=lambda l: -l.p)
        df = pd.DataFrame([{"A": name_of(items, l.a), "B": name_of(items, l.b), "p": round(l.p, 3), "relacja": l.relation,
                            "rodziny": ", ".join(f"{FAMILY_PL.get(k, k)}={v:.2f}" for k, v in sorted(l.families.items(), key=lambda kv: -kv[1])),
                            "uzasadnienie": l.explain(6)} for l in links])
        st.dataframe(df, use_container_width=True, hide_index=True)
        if links:
            opts = [f"{name_of(items, l.a)} — {name_of(items, l.b)} (p={l.p:.2f})" for l in links]
            sel = st.selectbox("Pełne dowody dla pary", opts)
            show_evidence(links[opts.index(sel)])

# =============================================================================== scheduler
with tabs[4]:
    from ftf import scheduler

    st.subheader("Automatyczny skan bibliotek reklam i list ostrzeżeń")
    st.caption("Źródła: lista ostrzeżeń CERT Polska (hole.cert.pl), Google Ads Transparency Center, Microsoft Ad Library, "
               "Meta Ad Library (yt-dlp facebook:ads po ID reklamy; API z tokenem META_ACCESS_TOKEN).")
    kw = st.text_input("Słowa kluczowe (filtr)", ", ".join(scheduler.DEFAULT_KEYWORDS))
    c1, c2, c3 = st.columns(3)
    if c1.button("▶️ Uruchom skan teraz"):
        with st.spinner("Skanowanie…"):
            out = scheduler.run_once(eng, keywords=[k.strip() for k in kw.split(",") if k.strip()], analyse=False)
        st.json(out, expanded=False)
    if c2.button("⏱️ Start schedulera (co 30 min)"):
        st.info(scheduler.start_background(eng, minutes=30))
    if c3.button("⏹️ Stop"):
        st.info(scheduler.stop_background())
    st.markdown("**Ostatnie zdarzenia**")
    st.dataframe(pd.DataFrame(eng.store.events(100)), use_container_width=True, hide_index=True)
    found = eng.store.get("scheduler_found", [])
    if found:
        st.markdown("**Znalezione podejrzane pozycje**")
        st.dataframe(pd.DataFrame(found[-200:]), use_container_width=True, hide_index=True)

# =============================================================================== methodology
with tabs[5]:
    p = config.ROOT / "docs" / "METHODOLOGY.md"
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "docs/METHODOLOGY.md")
