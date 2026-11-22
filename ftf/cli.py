"""Command line of FakerAlpha:  python -m ftf <command>   (also: python -m ftf.cli <command>)

Everything the analyst panel shows is available here as text tables or JSON. The commands call the same functions
as the HTTP API in ftf/api.py, so the numbers, labels and explanations are the ones the panel prints.

  status / campaigns / campaign / materials / material / search      what is in the store
  links / pair / trace / matrix                                      why materials are linked
  metrics / eval                                                     clustering quality
  add (alias: analyse) / ingest / demo                               new data (the only commands that write to the store)
  export / serve / glossary                                          files, the web panel, the vocabulary

Reference with examples and JSON shapes: docs/CLI.md. User-facing text is Polish, like the panel; JSON keys,
command names and flags are English.

Read commands open the store read-only (ftf/store.py, `readonly=True`) and never create it. Exit codes: 0 ok,
1 unexpected error, 2 usage, 3 store missing / empty / unreadable, 4 unknown material / campaign / trace,
5 bad input (file, folder, URL, labels), 6 environment (port taken, missing component), 130 interrupted.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from . import __version__
from .cli_format import Style, bar, join_more, kv, num, one_line, output_width, table, trunc, want_colour, wrap

PROG = "python -m ftf"

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_STORE, EXIT_NOT_FOUND, EXIT_INPUT, EXIT_ENV, EXIT_INTERRUPTED = 0, 1, 2, 3, 4, 5, 6, 130

RELATION_STYLE = {"duplicate": ("magenta",), "same_campaign": ("green",), "similar": ("yellow",), "none": ("dim",)}
BIG_STORE = 400          # above this many materials the pairwise comparison takes minutes; say so before starting


class CliError(Exception):
    """A user-facing error: message on stderr, optional hint lines saying what to do, a specific exit code."""
    code = EXIT_ERROR

    def __init__(self, message: str, hint: str | list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.hints = [hint] if isinstance(hint, str) else list(hint or [])


class UsageError(CliError):
    code = EXIT_USAGE


class StoreError(CliError):
    code = EXIT_STORE


class NotFound(CliError):
    code = EXIT_NOT_FOUND


class InputError(CliError):
    code = EXIT_INPUT


class EnvError(CliError):
    code = EXIT_ENV


# =============================================================================== context, store, output
def show_path(p: Path) -> str:
    """Path as the user would type it: relative to the current directory when it lies inside it."""
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def store_path(args) -> Path:
    """--store, else $FTF_STORE, else <FTF_ROOT>/data/store/ftf.sqlite (ftf/config.py)."""
    from . import config

    if getattr(args, "store", None):
        return Path(args.store).expanduser()
    env = os.environ.get("FTF_STORE")
    return Path(env).expanduser() if env else Path(config.STORE_PATH)


def _missing_store(path: Path) -> StoreError:
    others = sorted(p.name for p in path.parent.glob("*.sqlite") if p != path) if path.parent.is_dir() else []
    hints = [f"wskaż istniejącą bazę:  {PROG} --store ŚCIEŻKA <polecenie>   albo zmienna FTF_STORE=ŚCIEŻKA",
             f"albo utwórz ją:         {PROG} ingest <folder_zbioru>   lub   {PROG} add <plik|folder|\"tekst\">",
             "domyślna baza to <FTF_ROOT>/data/store/ftf.sqlite; FTF_ROOT domyślnie wskazuje katalog repozytorium"]
    if others:
        hints.append(f"inne bazy w {show_path(path.parent)}: {', '.join(others[:6])}")
    return StoreError(f"nie znaleziono bazy materiałów: {show_path(path)}", hints)


class Ctx:
    """Per-invocation state: parsed arguments, output styling, and the engine bound to the chosen store."""

    def __init__(self, args, stdout=None, stderr=None):
        self.args = args
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        colour = getattr(args, "color", "auto")
        self.st = Style(want_colour(colour, self.stdout))
        self.est = Style(want_colour(colour, self.stderr))
        self.width = output_width(getattr(args, "wide", False), self.stdout)
        self.quiet = bool(getattr(args, "quiet", False))
        self.verbose = int(getattr(args, "verbose", 0) or 0)
        self.engine = None
        self.api = None
        self.items: dict = {}
        self.cl: dict = {}
        self._saved = None

    # ---------------------------------------------------------------- output
    def out(self, text: str = "") -> None:
        print(text, file=self.stdout)

    def note(self, text: str) -> None:
        """Progress and remarks: stderr, silenced by --quiet. stdout stays clean for the result."""
        if not self.quiet:
            print(text, file=self.stderr, flush=True)

    def hint(self, text: str) -> None:
        """'What next' line: only for a person at a terminal (never in piped or redirected output)."""
        try:
            tty = self.stdout.isatty()
        except Exception:
            tty = False
        if tty and not self.quiet:
            print(self.st(text, "dim"), file=self.stdout)

    def heading(self, text: str) -> None:
        self.out()
        self.out(self.st(text, "bold"))

    def json(self, obj) -> None:
        print(json.dumps(clean(obj), ensure_ascii=False, indent=2, default=str), file=self.stdout)

    # ---------------------------------------------------------------- store
    def open(self, write: bool = False) -> None:
        """Bind the engine (and the API module, whose helpers the commands reuse) to the chosen store.
        Read access never creates or modifies the file; write access creates it when missing."""
        import sqlite3

        from . import api, config
        from .engine import Engine
        from .store import Store

        path = store_path(self.args)
        if write:
            if not path.exists():
                self.note(f"Tworzę nową bazę: {show_path(path)}")
            try:
                store = Store(path)
            except (sqlite3.Error, OSError) as exc:
                raise StoreError(f"nie można otworzyć bazy do zapisu: {show_path(path)} ({exc})",
                                 "sprawdź uprawnienia do pliku i katalogu albo wskaż inną bazę opcją --store")
        else:
            if not path.exists():
                raise _missing_store(path)
            try:
                store = Store(path, readonly=True)
                store.count()
            except sqlite3.Error as exc:
                raise StoreError(f"nie można odczytać bazy: {show_path(path)} ({exc})",
                                 "to nie wygląda na bazę FakerAlpha (plik SQLite z tabelą „materials”); wskaż właściwy "
                                 "plik opcją --store lub zmienną FTF_STORE")
        self._saved = (api._ENGINE, config.STORE_PATH)
        config.STORE_PATH = path
        self.engine = api._ENGINE = Engine(store)
        self.api = api

    def load(self, need_materials: bool = True) -> None:
        """Open read-only, read every material and compare all pairs (campaigns, families, duplicates)."""
        self.open(write=False)
        self.compute(need_materials)

    def compute(self, need_materials: bool = True) -> None:
        self.items = self.engine.store.all()
        n = len(self.items)
        if need_materials and not n:
            raise StoreError(f"baza {show_path(self.engine.store.path)} jest pusta (0 materiałów)",
                             [f"dodaj materiały:  {PROG} ingest <folder_zbioru>   lub   {PROG} add <plik|folder|\"tekst\">",
                              "albo wskaż inną bazę opcją --store / zmienną FTF_STORE"])
        if n > BIG_STORE:
            self.note(f"Baza ma {n} materiałów; porównanie wszystkich par jest kwadratowe i może potrwać kilka minut…")
        t = time.time()
        self.cl = self.engine.clustering()
        if self.verbose:
            self.note(f"[{n} materiałów, {len(self.cl['links'])} par, {len(self.cl['campaigns'])} kampanii; "
                      f"porównanie {time.time() - t:.1f} s]")

    def close(self) -> None:
        if self._saved is not None:
            from . import api, config

            api._ENGINE, config.STORE_PATH = self._saved
            self._saved = None
        if self.engine is not None:
            try:
                self.engine.store.db.close()
            except Exception:
                pass
            self.engine = None


_UI_KEYS = {"thumb", "thumb_kind", "thumbs", "color", "assets"}
_FILE_URL = "/api/file?path="


def clean(o):
    """API payload -> CLI JSON: drop what only the web UI needs (thumbnail URLs, colour slots) and turn the panel's
    file URLs into plain paths."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in _UI_KEYS:
                continue
            if k == "url" and ((isinstance(v, str) and v.startswith(_FILE_URL)) or (v is None and "ocr" in o)):
                out["path"] = unquote(v[len(_FILE_URL):]) if v else None
                continue
            out[k] = clean(v)
        return out
    if isinstance(o, (list, tuple)):
        return [clean(x) for x in o]
    return o


# =============================================================================== references (materials, campaigns)
def _fold(s) -> str:
    from .gazetteer import fold

    return fold(str(s or "")).strip()


def resolve_material(ctx: Ctx, ref: str) -> str:
    """Material id from what the user typed: full id, exact name, unique id prefix (>= 4 chars), unique part of the name."""
    items = ctx.items
    ref = str(ref).strip()
    if ref in items:
        return ref
    names = {mid: str(f.get("name") or mid) for mid, (f, _) in items.items()}
    for test in (lambda mid: names[mid] == ref,
                 lambda mid: len(ref) >= 4 and mid.startswith(ref.lower()),
                 lambda mid: _fold(names[mid]) == _fold(ref),
                 lambda mid: len(ref) >= 3 and _fold(ref) in _fold(names[mid])):
        hits = [mid for mid in items if test(mid)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            shown = ", ".join(f"{mid} ({trunc(names[mid], 30)})" for mid in hits[:6])
            raise NotFound(f"„{ref}” pasuje do {len(hits)} materiałów: {shown}{' …' if len(hits) > 6 else ''}",
                           "podaj pełny identyfikator materiału (pierwsza kolumna ID w `materials`)")
    import difflib

    close = difflib.get_close_matches(ref, list(names.values()) + list(items), n=3, cutoff=0.5)
    hints = [f"lista materiałów:  {PROG} materials      szukanie:  {PROG} search <tekst>"]
    if close:
        hints.insert(0, "podobne: " + ", ".join(close))
    raise NotFound(f"nie ma materiału „{ref}” (ani takiego identyfikatora, ani takiej nazwy)", hints)


def resolve_campaign(ctx: Ctx, ref: str) -> int:
    """Campaign index from its code as printed everywhere: C3, c3 or 3 (1-based)."""
    n = len(ctx.cl["profiles"])
    s = str(ref).strip().lower().lstrip("c")
    if not s.isdigit():
        raise NotFound(f"„{ref}” nie jest kodem kampanii",
                       f"kod kampanii to C1…C{n} (kolumna KOD w `{PROG} campaigns`); kampanię materiału pokaże "
                       f"`{PROG} campaign --of <materiał>`")
    ci = int(s) - 1
    if not 0 <= ci < n:
        raise NotFound(f"nie ma kampanii C{int(s)}",
                       f"w tej bazie są kampanie C1…C{n}; numeracja zmienia się po dodaniu materiałów — zobacz `{PROG} campaigns`")
    return ci


def _camp_code(ref: dict | None) -> str:
    return ref["code"] if ref else "—"


def _rel(ctx: Ctx, relation: str, label: str) -> tuple:
    return (label, *RELATION_STYLE.get(relation, ()))


def _reasons(link: dict, limit: int = 3) -> str:
    return "; ".join(r["detail"] if isinstance(r, dict) else str(r) for r in link.get("reasons", [])[:limit])


# =============================================================================== status
def cmd_status(ctx: Ctx) -> int:
    from . import config

    a = ctx.args
    path = store_path(a)
    ui = (config.ROOT / "web" / "dist" / "index.html").exists()
    data = {"version": __version__, "store": show_path(path), "store_exists": path.exists(), "root": str(config.ROOT),
            "n_materials": 0, "n_campaigns": 0, "web_ui_built": ui}
    if not path.exists():
        if a.json:
            ctx.json(data)
        else:
            ctx.out(kv([("Baza", f"{show_path(path)} — nie istnieje"), ("Katalog danych", str(config.DATA))], style=ctx.st, indent=0))
        raise _missing_store(path)
    ctx.load(need_materials=False)
    api, cl, items = ctx.api, ctx.cl, ctx.items
    ds = api.data_status()
    rel = Counter(l.relation for l in cl["links"])
    sizes = [len(c) for c in cl["campaigns"]]
    fams = [f for f in cl["families"] if len({cl["campaign_of"][m] for m in f}) > 1]
    data.update({
        "store_size_bytes": path.stat().st_size, "n_materials": len(items), "n_campaigns": len(sizes),
        "n_multi": sum(1 for s in sizes if s > 1), "n_singletons": sum(1 for s in sizes if s == 1),
        "n_in_multi": sum(s for s in sizes if s > 1), "n_duplicate_groups": len(cl["duplicates"]),
        "n_families_multi": len(fams), "n_pairs": len(cl["links"]),
        "links": {k: rel.get(k, 0) for k in ("duplicate", "same_campaign", "similar", "none")},
        "by_source": dict(Counter((f.get("_material") or {}).get("source", "?") for f, _ in items.values())),
        "last_added": ds["last_added"] or None,
        "llm_backend": ds["llm_backend"], "llm_available": ds["llm_available"], "neo4j": ds["neo4j"],
        "thresholds": {"duplicate_cut": config.DUPLICATE_CUT, "campaign_cut": config.CAMPAIGN_CUT,
                       "family_cut": config.FAMILY_CUT, "max_df": config.MAX_DF},
        "recent": ds["recent"],
    })
    if a.json:
        ctx.json(data)
    else:
        from .labels import RELATION_PL, SOURCE_PL

        pl = api.plural
        src = " · ".join(f"{SOURCE_PL.get(k, k)} {v}" for k, v in data["by_source"].items())
        avail = ", ".join(f"{k} {'tak' if v else 'nie'}" for k, v in data["llm_available"].items())
        ctx.out(ctx.st(f"FakerAlpha {__version__}", "bold"))
        ctx.out(kv([
            ("Baza", f"{data['store']}  ({data['store_size_bytes'] / 1024:.0f} kB, otwarta tylko do odczytu)"),
            ("Materiały", f"{data['n_materials']}" + (f"  ({src})" if src else "")),
            ("Kampanie", f"{data['n_campaigns']}  ({data['n_multi']} wielomateriałowych obejmuje "
                         f"{pl(data['n_in_multi'], 'materiał', 'materiały', 'materiałów')} · {data['n_singletons']} pojedynczych)"),
            ("Duplikaty", pl(data["n_duplicate_groups"], "grupa", "grupy", "grup")),
            ("Rodziny", f"{data['n_families_multi']} łączących co najmniej 2 kampanie"),
            ("Pary", f"{data['n_pairs']}  (" + " · ".join(f"{RELATION_PL[k]} {v}" for k, v in data["links"].items()) + ")"),
            ("Progi", f"duplikat d ≤ {config.DUPLICATE_CUT} · kampania d ≤ {config.CAMPAIGN_CUT} · rodzina d ≤ "
                      f"{config.FAMILY_CUT} · identyfikator liczy się przy df/N ≤ {config.MAX_DF:.0%}"),
            ("Ostatnio dodany", data["last_added"]),
            ("LLM", f"FTF_LLM={data['llm_backend']} ({ds['llm_backend_label']}); dostępne: {avail}"),
            ("Panel WWW", f"zbudowany — {PROG} serve" if ui else "niezbudowany — cd web && npm ci && npm run build"),
            ("Neo4j", "skonfigurowany (NEO4J_URI)" if data["neo4j"] else "nieskonfigurowany (NEO4J_URI)"),
        ], style=ctx.st, indent=0, width=ctx.width))
        if data["recent"]:
            ctx.heading("Ostatnie zdarzenia")
            ctx.out(table(["CZAS", "ZDARZENIE", "OPIS"], [[e["ts"], e["label"], e["text"]] for e in data["recent"][:5]],
                          flex=2, width=ctx.width, style=ctx.st, indent=2))
    if not items:
        raise StoreError(f"baza {show_path(path)} jest pusta (0 materiałów)",
                         f"dodaj materiały:  {PROG} ingest <folder_zbioru>   lub   {PROG} add <plik|folder|\"tekst\">")
    ctx.hint(f"\nDalej: {PROG} campaigns")
    return EXIT_OK


# =============================================================================== campaigns
def _campaign_rows(ctx: Ctx, camps: list[dict]) -> list[list]:
    rows = []
    for c in camps:
        stype = join_more([s["label"] for s in c["scam_types"]], 1)
        rows.append([(c["code"], "cyan", "bold") if c["size"] > 1 else c["code"], c["size"], c["name"], stype or "—",
                     c["n_shared"] or "—", num(c["mean_internal_p"]),
                     join_more([m["display_name"] for m in c["members"]], 6), join_more(c["domains"], 2)])
    return rows


def _print_campaigns(ctx: Ctx, ov: dict, camps: list[dict]) -> None:
    pl = ctx.api.plural
    ctx.out(f"{pl(ov['n_campaigns'], 'kampania', 'kampanie', 'kampanii')} · {pl(ov['n_materials'], 'materiał', 'materiały', 'materiałów')} "
            f"({ov['n_multi']} wielomateriałowych, {ov['n_singletons']} pojedynczych)")
    ctx.out()
    ctx.out(table(["KOD", "MAT.", "NAZWA", "TYP OSZUSTWA", "ŚLADY", "ŚR. p", "MATERIAŁY", "DOMENY"], _campaign_rows(ctx, camps),
                  align="lrllrrll", limits={2: 38, 3: 28, 6: 26, 7: 40}, flex=2, width=ctx.width, style=ctx.st))
    multi = [c for c in camps if c["size"] > 1 and c["top_shared"]]
    if multi:
        ctx.heading("Najmocniejsze wspólne ślady")
        for c in multi:
            parts = [f"{t['type_label']}: {trunc(t['display'], 44)}" + (f" (+{t['n_values'] - 1})" if t["n_values"] > 1 else "")
                     + f" — {t['count']} mat." for t in c["top_shared"] if t["type"] != "asset_phash"]
            imgs = [t for t in c["top_shared"] if t["type"] == "asset_phash"]
            parts += [f"obrazy na stronie: {t['n_values']} wspólnych — {t['count']} mat." for t in imgs]
            for i, p in enumerate(parts):
                ctx.out(f"  {ctx.st(c['code'], 'cyan', 'bold') if i == 0 else ' ' * len(c['code'])}  {p}")
    if ov["duplicates"]:
        ctx.heading("Duplikaty (ten sam materiał zgłoszony kilka razy)")
        for g in ov["duplicates"]:
            ctx.out("  " + " = ".join(m["display_name"] for m in g))
    if ov["families"]:
        ctx.heading("Rodziny (podobna treść, osobne kampanie)")
        for f in ov["families"]:
            ctx.out("  " + " + ".join(f"{r['code']} {trunc(r['name'], 34)}" for r in f["refs"] if r))


def cmd_campaigns(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    ov = ctx.api.overview()
    camps = [c for c in ov["campaigns"] if c["size"] >= a.min_size]
    if a.json:
        ctx.json({"n_materials": ov["n_materials"], "n_campaigns": ov["n_campaigns"], "n_multi": ov["n_multi"],
                  "n_singletons": ov["n_singletons"], "campaigns": camps,
                  "duplicates": [[{"id": m["id"], "name": m["name"]} for m in g] for g in ov["duplicates"]],
                  "families": ov["families"], "links": ov["links"], "thresholds": ov["thresholds"]})
        return EXIT_OK
    _print_campaigns(ctx, ov, camps)
    ctx.hint(f"\nDalej: {PROG} campaign {camps[0]['code'] if camps else 'C1'}")
    return EXIT_OK


def cmd_campaign(ctx: Ctx) -> int:
    a = ctx.args
    if bool(a.ref) == bool(a.of):
        raise UsageError("podaj kod kampanii (np. C1) albo --of <materiał>, jedno z dwóch", f"pomoc: {PROG} campaign --help")
    ctx.load()
    api, cl = ctx.api, ctx.cl
    ci = cl["campaign_of"][resolve_material(ctx, a.of)] if a.of else resolve_campaign(ctx, a.ref)
    d = api.campaign_detail(ci)
    if a.json:
        ctx.json(d)
        return EXIT_OK
    st = ctx.st
    names = {m["id"]: m["display_name"] for m in d["members"]}
    ctx.out(st(f"{d['code']} · {d['name']}", "bold"))
    fam = " + ".join(s["code"] for s in d["siblings"] if s)
    ctx.out(kv([
        ("materiały", f"{d['size']} · par wewnątrz: {d['n_pairs']} · średnie p wewnątrz: {num(d['mean_internal_p'])}"),
        ("typ oszustwa", ", ".join(f"{s['label']} ({s['n']})" for s in d["scam_types"])),
        ("produkty", join_more(d["products"], 6)),
        ("osoby (opis, nie łączą)", join_more(d["persons"], 8)),
        ("domeny", join_more(d["domains"], 8)),
        ("daty", " – ".join(dict.fromkeys(d["date_range"])) if d["date_range"] else None),
        ("ta sama rodzina", fam or None),
    ], style=st, width=ctx.width))

    ctx.heading("Materiały")
    ctx.out(table(["NAZWA", "ID", "TYP OSZUSTWA", "PRODUKT", "DOMENY", "TYTUŁ"],
                  [[m["display_name"], m["id"], m["scam_type_label"], m["product"], join_more(m["domains"], 2), m["title"]]
                   for m in d["members"]], limits={2: 31, 3: 26, 4: 34}, flex=5, width=ctx.width, style=st, indent=2))

    if d["matrix"]:
        ctx.heading("Wspólne ślady — który ślad łączy które materiały")
        rows = []
        for r in d["matrix"]:
            val = (f"{len(r['values'])} × obraz (pHash)" if r["type"] == "asset_phash"
                   else join_more([v["display"] for v in r["values"]], 2, " | "))
            rows.append([r["group_label"], r["type_label"], val, ", ".join(names.get(m, m) for m in r["members"]),
                         ("tak", "green") if r["linking"] else "nie"])
        ctx.out(table(["GRUPA", "ŚLAD", "WARTOŚĆ", "MATERIAŁY", "ŁĄCZY"], rows, limits={0: 24, 1: 30, 3: 30}, flex=2,
                      width=ctx.width, style=st, indent=2))

    pairs = d["links"] if a.all_pairs else d["chain"]
    if pairs:
        ctx.heading("Wszystkie pary w kampanii" if a.all_pairs else "Łańcuch najsilniejszych par — jak kampania trzyma się razem")
        rows = []
        for l in pairs:
            an = l.get("a_name") or l["a_info"]["name"]
            bn = l.get("b_name") or l["b_info"]["name"]
            basis = l.get("basis") or l["relation_label"]
            rows.append([an, bn, num(l["p"]), num(l["distance"]), _rel(ctx, l["relation"], basis), _reasons(l)])
        ctx.out(table(["A", "B", "p", "d", "PODSTAWA", "UZASADNIENIE"], rows, align="llrr", limits={0: 20, 1: 20, 4: 30},
                      flex=5, width=ctx.width, style=st, indent=2))

    prof = [v for v in d["view_profile"] if v["n_inside"] or v["n_outside"]]
    if prof:
        ctx.heading("Profil podobieństwa w widokach treści (średnia: pary wewnątrz kampanii / pary z materiałami spoza)")
        ctx.out(table(["WIDOK", "WEWNĄTRZ", "NA ZEWNĄTRZ", "PAR WEWN.", "PAR ZEWN."],
                      [[v["label"], num(v["inside"]), num(v["outside"]), v["n_inside"], v["n_outside"]] for v in prof],
                      align="lrrrr", style=st, indent=2))

    if d["nearest_outside"]:
        ctx.heading("Najbliższe materiały spoza kampanii")
        rows = []
        for l in d["nearest_outside"]:
            ins, outs = (l["a_info"], l["b_info"]) if l["a"] == l["inside"] else (l["b_info"], l["a_info"])
            oc = l.get("outside_campaign")
            rows.append([ins["name"], outs["name"], f"{oc['code']} {oc['name']}" if oc else "—", num(l["p"]),
                         num(l["distance"]), _rel(ctx, l["relation"], l["relation_label"]), _reasons(l)])
        ctx.out(table(["W KAMPANII", "SPOZA", "JEGO KAMPANIA", "p", "d", "RELACJA", "UZASADNIENIE"], rows, align="lllrr",
                      limits={0: 20, 1: 20, 2: 30}, flex=6, width=ctx.width, style=st, indent=2))
    if d["chain"]:
        c0 = d["chain"][0]
        ctx.hint(f"\nDalej: {PROG} pair {c0['a']} {c0['b']}")
    return EXIT_OK


# =============================================================================== materials
def _material_matches(m: dict, q: str) -> bool:
    c = m.get("campaign") or {}
    hay = [m["id"], m["name"], m["title"], m.get("product"), m.get("scam_type_label"), m.get("source_label"),
           c.get("code"), c.get("name"), *m.get("persons", []), *m.get("domains", [])]
    return any(q in _fold(x) for x in hay if x)


def cmd_materials(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    rows = ctx.api.materials()
    total = len(rows)
    if a.campaign:
        ci = resolve_campaign(ctx, a.campaign)
        rows = [m for m in rows if (m["campaign"] or {}).get("id") == ci]
    if a.source:
        rows = [m for m in rows if m["source"] == a.source or m["source"].startswith(a.source + ":")]
    if a.query:
        q = _fold(a.query)
        rows = [m for m in rows if _material_matches(m, q)]
    matched = len(rows)
    if a.limit:
        rows = rows[:a.limit]
    if a.json:
        ctx.json({"n_total": total, "n_matched": matched, "materials": rows})
        return EXIT_OK
    if not rows:
        ctx.out(f"Brak materiałów spełniających warunki (w bazie: {total}).")
        return EXIT_OK
    ctx.out(table(["ID", "NAZWA", "KAMP.", "TYP OSZUSTWA", "PRODUKT", "ID.", "DOMENY", "TYTUŁ"],
                  [[m["id"], m["display_name"], _camp_code(m["campaign"]), m["scam_type_label"], m["product"],
                    m["signals"]["n_linking_indicators"], join_more(m["domains"], 2), m["title"]] for m in rows],
                  align="lllllrll", limits={1: 26, 3: 31, 4: 26, 6: 32}, flex=7, width=ctx.width, style=ctx.st))
    ctx.out()
    shown = f"{len(rows)} z {matched}" if len(rows) < matched else str(matched)
    word = ctx.api.plural(matched, "materiał", "materiały", "materiałów").split(" ", 1)[1]
    ctx.out(wrap(f"{shown} {word}" + (f" (w bazie: {total})" if matched < total else "")
                 + " · ID. = liczba wartości identyfikatorów, które mogą łączyć", ctx.width, 0))
    ctx.hint(f"Dalej: {PROG} material {rows[0]['id']}")
    return EXIT_OK


def _identifier_status(ctx: Ctx, group: dict, df: int, n: int) -> tuple:
    from .similarity import counted

    if not group["linking"]:
        return ("nie łączy (opis)" if group["group"] == "descriptive" else "widok „obrazy”", "dim")
    if df <= 1:
        return ("tylko w tym materiale", "dim")
    if counted(df, n):
        return (f"łączy z {df - 1} mat.", "green")
    return ("zbyt popularne — pomijane", "yellow")


def _print_identifiers(ctx: Ctx, groups: list[dict], n: int, per_type: int | None) -> None:
    """Identifier values of one material grouped as in the panel; df = number of stored materials holding the value."""
    rows = []
    for g in groups:
        for it in g["items"]:
            vals = it["values"] if per_type is None else it["values"][:per_type]
            for v in vals:
                df = v["df"]
                rows.append([g["label"], it["type_label"], "obraz (pHash " + v["value"] + ")" if it["type"] == "asset_phash" else v["display"],
                             f"{df}/{n}", _identifier_status(ctx, g, df, n)])
            hidden = len(it["values"]) - len(vals) + it.get("more", 0)
            if hidden:
                rows.append([g["label"], it["type_label"], (f"… i {hidden} kolejnych (--all-values)", "dim"), "", ""])
    if rows:
        ctx.out(table(["GRUPA", "ŚLAD", "WARTOŚĆ", "df", "STATUS"], rows, align="lllr", limits={0: 24, 1: 30}, flex=2,
                      width=ctx.width, style=ctx.st, indent=2))
    else:
        ctx.out("  (brak identyfikatorów)")


def cmd_material(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    api, items, cl = ctx.api, ctx.items, ctx.cl
    mid = resolve_material(ctx, a.ref)
    d = api.material_detail(mid)
    f = d["features"]
    if a.all_values:
        df = Counter((t, v) for g, _ in items.values() for t, vals in g.get("indicators", {}).items() for v in set(vals))
        f["indicators"] = api._indicator_groups(items[mid][0], df, items, cl, limit=None)
    if a.json:
        ctx.json(d)
        return EXIT_OK
    st, pl = ctx.st, api.plural
    camp = d["campaign"]
    inp = d["inputs"]
    ctx.out(st(f"Materiał {d['display_name']}", "bold") + f"   id {d['id']}")
    ctx.out(kv([
        ("nazwa", d["name"] if d["name"] != d["display_name"] else None),
        ("tytuł", d["title"]),
        ("kampania", f"{camp['code']} · {camp['name']} ({pl(camp['size'], 'materiał', 'materiały', 'materiałów')})" if camp else None),
        ("źródło", f"{d['source_label']} — {d['source_ref']}" if d.get("source_ref") else d["source_label"]),
        ("dodany", d["created_at"]),
        ("wejście", f"{pl(len(inp['pages']), 'strona', 'strony', 'stron')}, {pl(inp['images'], 'obraz', 'obrazy', 'obrazów')}, "
                    f"{inp['videos']} wideo, {inp['assets']} zasobów strony" + (f"; URL: {join_more(inp['urls'], 2)}" if inp["urls"] else "")),
    ], style=st, width=ctx.width))

    ctx.heading("Opis (cechy opisowe — nigdy nie łączą)")
    tx, web, per = f["text"], f["web"], f["persons"]
    desc = [("streszczenie", f["summary"])]
    desc += [(r["label"].lower(), ", ".join(r["value"]) if isinstance(r["value"], list) else r["value"]) for r in f["llm"]]
    desc += [
        ("źródło atrybutów", f["llm_backend_label"]),
        ("osoby rozpoznane z twarzy", join_more(per["faces"], 8)),
        ("osoby wymienione w tekście", join_more(per["named"], 8)),
        ("marki / media w tekście", join_more(list(tx["brands"]) + list(tx["media"]), 8)),
        ("słowa kluczowe", join_more(tx["keywords"], 10)),
        ("kwoty", join_more(tx["amounts"], 8)),
        ("daty", join_more(f["dates"], 4)),
        ("adresy docelowe", join_more([trunc(u, 100) for u in web["landing_urls"]], 2, " | ")),
        ("adresy IP", join_more(web["ips"], 6) + (" (za Cloudflare)" if web.get("behind_cloudflare") else "") if web["ips"] else None),
        ("linki z OCR / QR", join_more(f["ocr_links"], 4)),
        ("uwagi", join_more(f["notes"], 4, " | ")),
    ]
    ctx.out(kv(desc, style=st, width=ctx.width) or "  (brak)")
    for x in web["infra"]:
        extra = ", ".join(f"{k}: {join_more(v, 3) if isinstance(v, list) else v}" for k, v in x.items()
                          if k != "domain" and v not in (None, "", [], {}))
        ctx.out(f"  {st('domena ' + str(x.get('domain')) + ':', 'dim')} {trunc(extra, (ctx.width - 12) if ctx.width else None)}")

    ctx.heading(f"Identyfikatory (df = w ilu z {f['n_corpus']} materiałów bazy występuje wartość)")
    _print_identifiers(ctx, f["indicators"], f["n_corpus"], None if a.all_values else 6)

    ctx.heading("Widoki treści — na czym ten materiał da się porównać")
    ctx.out(table(["WIDOK", "DOSTĘPNY", "CO ZAWIERA"],
                  [[v["label"], ("tak", "green") if v["available"] else ("nie", "dim"), v["detail"] or "—"] for v in f["views"]],
                  style=st, indent=2))

    ctx.heading("Najbliższe materiały")
    if d["links"]:
        rows = [[l["other"].get("display_name") or l["other"]["name"], l["other"]["id"], _camp_code(l["other"].get("campaign")),
                 num(l["p"]), num(l["distance"]), _rel(ctx, l["relation"], l["relation_label"]), _reasons(l)] for l in d["links"]]
        ctx.out(table(["NAZWA", "ID", "KAMP.", "p", "d", "RELACJA", "UZASADNIENIE"], rows, align="lllrr", limits={0: 26},
                      flex=6, width=ctx.width, style=st, indent=2))
        ctx.hint(f"\nDalej: {PROG} pair {mid} {d['links'][0]['other']['id']}")
    else:
        ctx.out("  (żaden inny materiał nie jest bliżej niż p = 0.05)")
    return EXIT_OK


# =============================================================================== search / trace
def cmd_search(ctx: Ctx) -> int:
    a = ctx.args
    q = " ".join(a.query).strip()
    if len(q) < 2:
        raise UsageError("zapytanie musi mieć co najmniej 2 znaki", f"przykład: {PROG} search kardivix")
    ctx.load()
    res = ctx.api.search(q)
    if a.json:
        ctx.json({"query": q, **res})
        return EXIT_OK
    st = ctx.st
    if not (res["campaigns"] or res["materials"] or res["traces"]):
        ctx.out(f"Brak wyników dla „{q}”.")
        return EXIT_OK
    if res["campaigns"]:
        ctx.out(st("Kampanie", "bold"))
        ctx.out(table(["KOD", "MAT.", "NAZWA"], [[c["code"], c["size"], c["name"]] for c in res["campaigns"]], align="lr",
                      style=st, indent=2))
    if res["materials"]:
        ctx.heading("Materiały") if res["campaigns"] else ctx.out(st("Materiały", "bold"))
        ctx.out(table(["ID", "NAZWA", "KAMP.", "TRAFIENIA"],
                      [[m["id"], m["display_name"], _camp_code(m["campaign"]),
                        "; ".join(f"{h['field']}: {trunc(h['value'], 50)}" for h in m["hits"])] for m in res["materials"]],
                      limits={1: 26}, flex=3, width=ctx.width, style=st, indent=2))
    if res["traces"]:
        ctx.heading("Ślady (wartości identyfikatorów i osoby)") if (res["campaigns"] or res["materials"]) \
            else ctx.out(st("Ślady (wartości identyfikatorów i osoby)", "bold"))
        ctx.out(table(["TYP", "ŚLAD", "WARTOŚĆ", "MAT."], [[t["type"], t["type_label"], t["display"], t["n"]] for t in res["traces"]],
                      align="lllr", flex=2, width=ctx.width, style=st, indent=2))
        t0 = res["traces"][0]
        ctx.hint(f"\nDalej: {PROG} trace --type {t0['type']} \"{t0['value']}\"")
    return EXIT_OK


def trace_types() -> list[str]:
    from . import api

    return sorted(api.DISPLAY_TYPES) + ["person"]


def cmd_trace(ctx: Ctx) -> int:
    a = ctx.args
    value = " ".join(a.value).strip()
    if not value:
        raise UsageError("podaj wartość śladu", f"przykład: {PROG} trace kardivix-promo.example")
    ctx.load()
    api, items, cl = ctx.api, ctx.items, ctx.cl
    if a.type and a.type not in trace_types():
        raise UsageError(f"nieznany typ śladu „{a.type}”", [f"dozwolone typy: {', '.join(trace_types())}",
                                                           f"opis typów: {PROG} glossary"])
    q = _fold(value)
    found: dict[tuple[str, str], None] = {}
    for f, _ in items.values():
        for t, vals in f.get("indicators", {}).items():
            if t not in api.DISPLAY_TYPES or (a.type and t != a.type):
                continue
            for v in vals:
                if v == value or _fold(v) == q or _fold(api.display_value(t, v, cl)) == q:
                    found[(t, v)] = None
        if not a.type or a.type == "person":
            for p in set(f.get("persons_visual", [])) | set(f.get("persons_named", [])):
                if _fold(p) == q:
                    found[("person", p)] = None
    if not found:
        near = api.search(value)["traces"][:5] if len(value) >= 2 else []
        hints = [f"wartość musi być pełna i dokładna; fragmentu szukaj przez: {PROG} search \"{value}\""]
        if near:
            hints.insert(0, "podobne ślady: " + "; ".join(f"{t['type']} „{t['display']}” ({t['n']} mat.)" for t in near))
        raise NotFound(f"żaden materiał nie ma śladu „{value}”" + (f" typu {a.type}" if a.type else ""), hints)
    traces = [api.trace(t, v) for t, v in sorted(found)]
    if a.json:
        ctx.json({"query": value, "type": a.type, "traces": traces})
        return EXIT_OK
    st = ctx.st
    for i, tr in enumerate(traces):
        if i:
            ctx.out()
        share = tr["df"] / max(1, tr["n"])
        ctx.out(st(f"{tr['type_label']}: „{tr['display']}”", "bold") + f"   [{tr['type']} · {tr['group_label']}]")
        if not tr["linking"]:
            verdict = "cecha opisowa — pokazywana analitykowi, nie łączy materiałów"
        elif tr["df"] < 2:
            verdict = "identyfikator, ale tylko w jednym materiale — nie ma czego łączyć"
        elif tr["counted"]:
            verdict = st(f"liczy się jako identyfikator łączący (df/N ≤ {tr['max_df']:.0%})", "green")
        else:
            verdict = st(f"zbyt popularne — pomijane przy łączeniu (df/N > {tr['max_df']:.0%})", "yellow")
        ctx.out(f"  występuje w {tr['df']} z {tr['n']} materiałów ({share:.0%})")
        ctx.out(f"  {verdict}")
        ctx.out(table(["ID", "NAZWA", "KAMP.", "TYP OSZUSTWA", "TYTUŁ"],
                      [[m["id"], m["display_name"], _camp_code(m["campaign"]), m["scam_type_label"], m["title"]]
                       for m in tr["materials"]], limits={1: 26, 3: 31}, flex=4, width=ctx.width, style=st, indent=2))
    return EXIT_OK


# =============================================================================== links / pair / matrix
def cmd_links(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    api, cl = ctx.api, ctx.cl
    only = resolve_material(ctx, a.material) if a.material else None
    ci = resolve_campaign(ctx, a.campaign) if a.campaign else None
    camp_of = cl["campaign_of"]
    picked = []
    for l in sorted(cl["links"], key=lambda l: (-l.p, l.distance)):
        if l.p < a.min or (a.relation and l.relation not in a.relation):
            continue
        if only and only not in (l.a, l.b):
            continue
        if ci is not None and not (camp_of.get(l.a) == ci and camp_of.get(l.b) == ci):
            continue
        picked.append(l)
    matched = len(picked)
    if a.limit:
        picked = picked[:a.limit]
    rows = [api.link_brief(l, ctx.items, cl) for l in picked]
    if a.json:
        ctx.json({"min_p": a.min, "n_matched": matched, "links": rows})
        return EXIT_OK
    if not rows:
        ctx.out(f"Brak par o p ≥ {a.min:g} spełniających warunki.")
        return EXIT_OK
    ctx.out(table(["A", "B", "KAMP.", "p", "d", "RELACJA", "UZASADNIENIE"],
                  [[l["a_info"]["name"], l["b_info"]["name"],
                    " / ".join(dict.fromkeys([_camp_code(l["a_info"]["campaign"]), _camp_code(l["b_info"]["campaign"])])),
                    num(l["p"]), num(l["distance"]), _rel(ctx, l["relation"], l["relation_label"]), _reasons(l)] for l in rows],
                  align="lllrr", limits={0: 22, 1: 22}, flex=6, width=ctx.width, style=ctx.st))
    ctx.out()
    shown = f"{len(rows)} z {matched}" if len(rows) < matched else str(matched)
    ctx.out(wrap(f"{shown} par o p ≥ {a.min:g} (p = 1 − D; p = 1.00 przy wspólnym identyfikatorze, inaczej 1 − d)", ctx.width, 0))
    ctx.hint(f"Dalej: {PROG} pair {rows[0]['a']} {rows[0]['b']}")
    return EXIT_OK


def cmd_pair(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    ma, mb = resolve_material(ctx, a.a), resolve_material(ctx, a.b)
    if ma == mb:
        raise UsageError("para wymaga dwóch różnych materiałów", f"przykład: {PROG} pair 1 2")
    d = ctx.api.pair_detail(ma, mb)
    if a.json:
        ctx.json(d)
        return EXIT_OK
    st = ctx.st
    A, B = d["a"], d["b"]
    ctx.out(st(f"{A['display_name']}  ↔  {B['display_name']}", "bold"))
    ctx.out(kv([(m["display_name"], f"{m['id']} · {_camp_code(m['campaign'])} · {m['title'] or m['source_label']}") for m in (A, B)],
               style=st, width=ctx.width))
    ctx.out()
    ctx.out(f"Relacja: {st(d['relation_label'], *RELATION_STYLE.get(d['relation'], ()), 'bold')}   "
            f"p = {num(d['p'])}   d = {num(d['distance'])}")
    ctx.out(wrap(d["rule"], ctx.width))
    ctx.out(wrap(f"({d['relation_label']}: {d['relation_hint']})", ctx.width))

    ctx.heading("Wspólne identyfikatory (łączą na pewno)")
    if d["identifiers"]:
        rows = []
        for g in d["identifiers"]:
            if not g["items"]:
                rows.append([g["label"], g["hint"], "", ""])
            for it in g["items"]:
                rows.append([g["label"], it["type_label"], it["display"], f"{it['df']}/{it['n']}"])
        ctx.out(table(["GRUPA", "ŚLAD", "WARTOŚĆ", "df"], rows, align="lllr", limits={0: 24, 1: 34}, flex=2, width=ctx.width,
                      style=st, indent=2))
    else:
        ctx.out("  brak")
    if d["ignored"]:
        ctx.heading("Wspólne, ale pominięte (zbyt popularne)")
        for x in d["ignored"]:
            ctx.out(wrap(x["detail"], ctx.width))

    ctx.heading("Podobieństwo w widokach treści")
    ctx.out(table(["WIDOK", "PODOBIEŃSTWO", "WKŁAD s/k", "UWAGI"],
                  [[v["label"], num(v["score"], 3), num(v["contribution"], 3),
                    v["note"] if v["available"] else ("niedostępny po obu stronach — pominięty", "dim")] for v in d["views"]],
                  align="lrr", flex=3, width=ctx.width, style=st, indent=2))

    ctx.heading("Obliczenie odległości treści")
    ctx.out(f"  {d['formula']}")
    ctx.out(f"  p = {num(d['p'])}  ({'wspólny identyfikator → p = 1' if d['must_link'] else 'p = 1 − d'})")
    return EXIT_OK


def cmd_matrix(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    mx = ctx.api.matrix()
    keep = list(range(len(mx["materials"])))
    if a.campaign:
        ci = resolve_campaign(ctx, a.campaign)
        keep = [i for i, m in enumerate(mx["materials"]) if (m["campaign"] or {}).get("id") == ci]
    sub = lambda M: [[M[i][j] for j in keep] for i in keep]
    out = {"materials": [mx["materials"][i] for i in keep], "p": sub(mx["p"]), "distance": sub(mx["distance"]),
           "relation": sub(mx["relation"]), "thresholds": mx["thresholds"]}
    if a.json:
        ctx.json(out)
        return EXIT_OK
    st = ctx.st
    n = len(keep)
    need = 34 + 4 * n
    if ctx.width is not None and need > ctx.width:
        raise UsageError(f"macierz {n} × {n} nie mieści się w {ctx.width} kolumnach",
                         ["zawęź do jednej kampanii: --campaign C1", "albo wyłącz ograniczenie szerokości: --wide",
                          "albo weź dane: --json"])
    vals = out["distance"] if a.distance else out["p"]
    what = "odległość treści d" if a.distance else "bliskość p = 1 − D"
    ctx.out(wrap(f"{what} (×100), wiersze i kolumny w kolejności kampanii; · = brak powiązania, kolor = relacja", ctx.width, 0))
    ctx.out()
    head = " " * 34 + "".join(f"{j + 1:>4}" for j in range(n))
    ctx.out(st(head, "bold"))
    for i, m in enumerate(out["materials"]):
        label = f"{i + 1:>3} {_camp_code(m['campaign']):<5}{trunc(m['name'], 24):<24} "
        cells = []
        for j in range(n):
            if i == j:
                cells.append(st(f"{'—':>4}", "dim"))
                continue
            v, r = vals[i][j], out["relation"][i][j]
            if v is None:
                cells.append(st(f"{'?':>4}", "dim"))
            elif r == "none" and not a.distance:
                cells.append(st(f"{'·':>4}", "dim"))
            else:
                cells.append(st(f"{round(v * 100):>4}", *RELATION_STYLE.get(r, ())))
        ctx.out(label + "".join(cells))
    ctx.out()
    th = out["thresholds"]
    ctx.out(wrap(f"progi: duplikat d ≤ {th['duplicate_cut']} · ta sama kampania d ≤ {th['campaign_cut']} lub wspólny "
                 f"identyfikator (p = 100) · podobna treść d ≤ {th['family_cut']}", ctx.width, 0))
    return EXIT_OK


# =============================================================================== metrics / eval
def cmd_metrics(ctx: Ctx) -> int:
    a = ctx.args
    ctx.load()
    api = ctx.api
    mo = api.metrics_overview()
    fs = api.feature_space_view()
    ids = [p["id"] for p in fs.get("points", [])]
    methods = [{"key": m["key"], "label": m["label"], "hint": m["hint"], "n_clusters": m["n_clusters"],
                "n_singletons": m["n_singletons"], "n_noise": m["n_noise"], "silhouette": m["silhouette"],
                "ari_fakeralpha": m["ari_fakeralpha"], "ari_labels": m["ari_labels"],
                "clusters": {ids[i]: c for i, c in enumerate(m["cluster"])},
                "noise": [ids[i] for i, x in enumerate(m["noise"]) if x]} for m in fs["methods"]]
    dendro = mo.get("dendrogram")
    heights = sorted(round(m["y"], 3) for m in dendro["merges"]) if dendro else []
    data = {
        "n_materials": mo["n_materials"], "n_campaigns": mo["n_campaigns"], "n_multi": mo["n_multi"],
        "n_singletons": mo["n_singletons"], "n_pairs": mo["n_pairs"], "n_must_link": mo["n_must_link"],
        "thresholds": mo["thresholds"], "methods": methods, "labels": fs.get("labels"),
        "distance_histogram": mo["distance_histogram"], "signal_attribution": mo["signal_attribution"],
        "view_summary": mo["view_summary"], "feature_coverage": mo["feature_coverage"], "scam_types": mo["scam_types"],
        "top_persons": mo["top_persons"], "merge_heights": heights,
        "projections": {k: {"label": v["label"], "fit": v["fit"], "xy": {ids[i]: xy for i, xy in enumerate(v["xy"])}}
                        for k, v in fs.get("projections", {}).items()},
        "dendrogram": dendro,
    }
    if a.json:
        ctx.json(data)
        return EXIT_OK
    st = ctx.st
    th = data["thresholds"]
    ctx.out(wrap(f"{data['n_materials']} materiałów · {data['n_campaigns']} kampanii ({data['n_multi']} wielomateriałowych, "
                 f"{data['n_singletons']} pojedynczych) · {data['n_pairs']} par, w tym {data['n_must_link']} ze wspólnym "
                 "identyfikatorem", ctx.width, 0))
    if methods:
        lab = data["labels"]
        ctx.heading("Metody grupowania na tych samych odległościach")
        ctx.out(table(["METODA", "GRUPY ≥ 2", "POJED.", "SZUM", "SILHOUETTE", "ARI/FakerAlpha", "ARI/etykiety"],
                      [[(m["label"], "bold") if m["key"] == "fakeralpha" else m["label"], m["n_clusters"], m["n_singletons"],
                        m["n_noise"], num(m["silhouette"], 3), num(m["ari_fakeralpha"], 3), num(m["ari_labels"], 3)]
                       for m in methods], align="lrrrrrr", style=st, indent=2))
        ctx.out(wrap("POJED. = grupy jednoelementowe; silhouette: zwartość grup na macierzy D (bliżej 1 = lepiej); ARI: zgodność "
                     "podziału z FakerAlpha i z "
                     + (f"etykietami referencyjnymi {lab['file']} ({lab['n']} materiałów)" if lab else
                        "etykietami referencyjnymi (brak pliku data/labels_dane.csv albo brak dopasowanych materiałów)")
                     + f"; opis metod: {PROG} metrics --methods", ctx.width))
        if a.methods:
            ctx.out()
            for m in methods:
                ctx.out(wrap(f"{m['label']}: {m['hint']}", ctx.width))
    if heights:
        cnt = Counter(heights)
        ctx.heading("Wysokości scaleń dendrogramu (UPGMA)")
        ctx.out(wrap(", ".join(f"{h:g}" + (f" (×{c})" if c > 1 else "") for h, c in sorted(cnt.items())[:40])
                     + (" …" if len(cnt) > 40 else "") + f"   — cięcia: kampanie {th['campaign_cut']}, rodziny {th['family_cut']}",
                     ctx.width))
    ctx.heading("Rozkład odległości treści d między parami")
    top = max((b["total"] for b in data["distance_histogram"]), default=0)
    ctx.out(table(["d", "PAR", "", "W. IDENT.", "TA SAMA KAMP.", "PODOBNE", "BRAK"],
                  [[b["range"], b["total"], bar(b["total"], top, 28), b["must_link"], b["same_campaign"], b["similar"], b["none"]]
                   for b in data["distance_histogram"]], align="lrlrrrr", style=st, indent=2))
    if data["signal_attribution"]:
        ctx.heading("Co łączy pary w kampaniach")
        top = max(s["pairs"] for s in data["signal_attribution"])
        ctx.out(table(["PODSTAWA", "PAR", ""], [[s["label"], s["pairs"], bar(s["pairs"], top, 28)] for s in data["signal_attribution"]],
                      align="lr", style=st, indent=2))
    ctx.heading("Widoki treści: średnie podobieństwo w tej samej kampanii / w różnych kampaniach")
    ctx.out(table(["WIDOK", "TA SAMA", "RÓŻNE", "PAR (TA SAMA)", "PAR (RÓŻNE)"],
                  [[v["label"], num(v["mean_same"], 3), num(v["mean_diff"], 3), v["n_same"], v["n_diff"]] for v in data["view_summary"]],
                  align="lrrrr", style=st, indent=2))
    ctx.heading("Pokrycie cech")
    ctx.out(table(["CECHA", "MAT.", "%", ""], [[c["label"], f"{c['count']}/{c['total']}", c["pct"], bar(c["pct"], 100, 20)]
                                               for c in data["feature_coverage"]], align="lrr", style=st, indent=2))
    ctx.heading("Typy oszustw")
    ctx.out(table(["TYP", "MAT."], [[s["label"], s["count"]] for s in data["scam_types"]], align="lr", style=st, indent=2))
    if data["top_persons"]:
        ctx.heading("Najczęściej wykorzystywane wizerunki")
        ctx.out(table(["OSOBA", "MAT.", "Z TWARZY", "Z TEKSTU"],
                      [[p["name"], p["count"], p["visual"], p["named"]] for p in data["top_persons"]], align="lrrr", style=st, indent=2))
    return EXIT_OK


def evaluate(eng, labels_csv: str) -> dict:
    """Pairwise P/R/F1, B-cubed and ARI of the campaigns against reference labels (`id_or_name,label` rows).
    Also used by tools/evaluate.py. Raises ValueError when no row of the file matches a stored material."""
    from itertools import combinations

    from sklearn.metrics import adjusted_rand_score

    items = eng.store.all()
    name2id = {f["name"]: mid for mid, (f, _) in items.items()}
    gold = {}
    with open(labels_csv, encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and not row[0].startswith("#"):
                key = row[0].strip()
                mid = key if key in items else name2id.get(key)
                if mid:
                    gold[mid] = row[1].strip()
    if not gold:
        raise ValueError("no row of the labels file matches a stored material (expected rows: id_or_name,label)")
    cl = eng.clustering(refresh=True)
    pred = {m: cl["campaign_of"][m] for m in gold}
    ids = sorted(gold)
    tp = fp = fn = 0
    for a, b in combinations(ids, 2):
        g, p = gold[a] == gold[b], pred[a] == pred[b]
        tp += g and p
        fp += (not g) and p
        fn += g and (not p)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    # B-cubed
    bp = br = 0.0
    for m in ids:
        same_p = [x for x in ids if pred[x] == pred[m]]
        same_g = [x for x in ids if gold[x] == gold[m]]
        inter = len([x for x in same_p if gold[x] == gold[m]])
        bp += inter / len(same_p)
        br += inter / len(same_g)
    bp, br = bp / len(ids), br / len(ids)
    res = {"n": len(ids), "pairwise_precision": round(prec, 3), "pairwise_recall": round(rec, 3), "pairwise_f1": round(f1, 3),
           "bcubed_precision": round(bp, 3), "bcubed_recall": round(br, 3),
           "ARI": round(adjusted_rand_score([gold[m] for m in ids], [pred[m] for m in ids]), 3)}
    hd = cl.get("hdbscan") or {}
    if hd:
        res["ARI_hdbscan_baseline"] = round(adjusted_rand_score([gold[m] for m in ids], [hd.get(m, -1) if hd.get(m, -1) >= 0 else 1000 + i for i, m in enumerate(ids)]), 3)
    return res


EVAL_PL = {"n": "materiały z etykietą", "pairwise_precision": "precyzja par", "pairwise_recall": "czułość par",
           "pairwise_f1": "F1 par", "bcubed_precision": "B-cubed precyzja", "bcubed_recall": "B-cubed czułość",
           "ARI": "ARI (FakerAlpha)", "ARI_hdbscan_baseline": "ARI (HDBSCAN, punkt odniesienia)"}


def cmd_eval(ctx: Ctx) -> int:
    a = ctx.args
    p = Path(a.labels)
    if not p.is_file():
        raise InputError(f"nie znaleziono pliku etykiet: {a.labels}",
                         "plik CSV z wierszami `id_lub_nazwa_materiału,etykieta` (linie zaczynające się od # są pomijane); "
                         "przykład w repozytorium: data/labels_dane.csv")
    ctx.load()
    try:
        res = evaluate(ctx.engine, str(p))
    except ValueError:
        raise InputError(f"żaden wiersz pliku {a.labels} nie pasuje do materiału w bazie",
                         [f"pierwsza kolumna musi być identyfikatorem albo nazwą materiału (zobacz `{PROG} materials`)",
                          "format: id_lub_nazwa,etykieta"])
    if a.json:
        ctx.json(res)
        return EXIT_OK
    ctx.out(f"Zgodność kampanii z etykietami {show_path(p)}")
    ctx.out(table(["MIARA", "WARTOŚĆ", "KLUCZ JSON"], [[EVAL_PL.get(k, k), v if k == "n" else num(v, 3), k] for k, v in res.items()],
                  align="lr", style=ctx.st, indent=2, styles={2: ("dim",)}))
    return EXIT_OK


# =============================================================================== glossary
def cmd_glossary(ctx: Ctx) -> int:
    from . import api, config
    from .labels import DECISION_PL, GROUP_HINT, GROUP_ORDER, RELATION_HINT, RELATION_PL, VIEW_HINT, group_label, signal_label, view_label
    from .similarity import VIEWS

    a = ctx.args
    by_group: dict[str, list] = {g: [] for g in GROUP_ORDER}
    for t, g in config.IDENTIFIER_GROUP.items():
        by_group.setdefault(g, []).append({"type": t, "label": signal_label(t)})
    extra = sorted(api.DISPLAY_TYPES - set(config.IDENTIFIER_GROUP))
    data = {
        "identifier_groups": [{"group": g, "label": group_label(g), "hint": GROUP_HINT.get(g, ""), "types": by_group[g]}
                              for g in by_group],
        "descriptive_types": [{"type": t, "label": signal_label(t)} for t in extra] + [{"type": "person", "label": "osoba"}],
        "views": [{"view": v, "label": view_label(v), "hint": VIEW_HINT[v]} for v in VIEWS],
        "relations": [{"relation": k, "label": RELATION_PL[k], "hint": RELATION_HINT[k]} for k in RELATION_PL],
        "decisions": [{"decision": k, "label": v[0], "hint": v[1]} for k, v in DECISION_PL.items()],
        "constants": {"max_df": config.MAX_DF, "duplicate_cut": config.DUPLICATE_CUT, "campaign_cut": config.CAMPAIGN_CUT,
                      "family_cut": config.FAMILY_CUT, "phash_hamming": config.PHASH_HAMMING},
        "measures": [
            {"key": "d", "label": "odległość treści (Gower)",
             "hint": "1 − średnia podobieństw w widokach dostępnych po obu stronach; 1 = nic wspólnego albo nic do porównania"},
            {"key": "p", "label": "bliskość", "hint": "1 − D; równa 1 przy wspólnym identyfikatorze, inaczej 1 − d"},
            {"key": "df", "label": "częstość dokumentowa",
             "hint": f"w ilu materiałach bazy występuje wartość; identyfikator łączy, gdy df/N ≤ {config.MAX_DF:.0%} "
                     "(albo mają go tylko dwa porównywane materiały)"},
        ],
        "steps": api.method_steps(),
    }
    if a.json:
        ctx.json(data)
        return EXIT_OK
    st = ctx.st
    ctx.out(st("Jak powstają kampanie", "bold"))
    for s in data["steps"]:
        ctx.out(wrap(f"{s['step']}. {s['title']}. {s['text']}", ctx.width))
    ctx.heading("Miary")
    ctx.out(kv([(m["key"], f"{m['label']} — {m['hint']}") for m in data["measures"]], style=st, width=ctx.width))
    ctx.heading("Identyfikatory — wspólna wartość łączy materiały (typ podajesz w `trace --type`)")
    rows = [[g["label"], t["type"], t["label"]] for g in data["identifier_groups"] for t in g["types"]]
    ctx.out(table(["GRUPA", "TYP", "ZNACZENIE"], rows, style=st, indent=2))
    ctx.heading("Ślady opisowe — pokazywane, nigdy nie łączą")
    ctx.out(table(["TYP", "ZNACZENIE"], [[t["type"], t["label"]] for t in data["descriptive_types"]], style=st, indent=2))
    ctx.heading("Widoki treści — z nich liczona jest odległość d")
    ctx.out(kv([(v["view"], f"{v['label']} — {v['hint']}") for v in data["views"]], style=st, width=ctx.width))
    ctx.heading("Relacje pary")
    ctx.out(kv([(r["relation"], f"{r['label']} — {r['hint']}") for r in data["relations"]], style=st, width=ctx.width))
    ctx.heading("Decyzje dla nowego materiału (`add`)")
    ctx.out(kv([(x["decision"], f"{x['label']} — {x['hint']}") for x in data["decisions"]], style=st, width=ctx.width))
    return EXIT_OK


# =============================================================================== add / ingest
_PATHLIKE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi",
                 ".html", ".htm", ".har", ".mhtml", ".zip", ".txt", ".json", ".pdf"}


def _looks_like_path(t: str) -> bool:
    if any(ch.isspace() for ch in t):
        return False
    return t.startswith(("/", "./", "../", "~")) or Path(t).suffix.lower() in _PATHLIKE_EXT


def _new_material(ctx: Ctx, progress):
    """Material from the `add` target: an existing file or folder, an http(s) URL, otherwise free text."""
    import hashlib
    import re

    from . import config, ingest

    a = ctx.args
    t = a.target
    cleanup = None
    if a.text:
        return ingest.from_text(t), "text", None
    p = Path(t).expanduser()
    if p.is_dir():
        if not any(x.is_file() for x in p.rglob("*")):
            raise InputError(f"folder {t} jest pusty", "folder przypadku powinien zawierać zapisane strony (HTML/HAR/MHTML), "
                                                      "zrzuty ekranu, wideo albo pliki .txt")
        return ingest.load_folder(p, source="upload"), "folder", None
    if p.is_file():
        data = p.read_bytes()
        if not data:
            raise InputError(f"plik {t} jest pusty")
        updir = config.DATA / "uploads" / hashlib.sha1(data).hexdigest()[:12]
        existed = updir.exists()
        m = ingest.from_upload(p.name, data)
        if a.dry and not existed:           # a dry run leaves no working copy of the file behind
            cleanup = lambda: ingest.clean_upload_dir(m)
        return m, "file", cleanup
    if re.match(r"^https?://", t, re.I):
        if not re.match(r"^https?://[^\s/?#]+\S*$", t, re.I):
            raise InputError(f"niepoprawny adres URL: {t}", "podaj pełny adres zaczynający się od http:// lub https://")
        from .capture import capture_url

        progress("Pobieranie strony w 3 profilach klienta (wykrywanie cloakingu)…")
        cap = capture_url(t, render=not a.no_render)
        if cap.get("error"):
            raise InputError(f"adres został odrzucony: {cap['error']}",
                             "dozwolone są tylko publiczne adresy http(s); adresy lokalne i prywatne są blokowane")
        progress("Cloaking: " + ("TAK — różna treść dla różnych klientów" if cap.get("cloaking") else "nie wykryto"))
        return ingest.from_url(t, cap), "url", None
    if _looks_like_path(t):
        raise InputError(f"nie znaleziono pliku ani folderu: {t}",
                         "sprawdź ścieżkę; jeśli to ma być tekst do analizy, dodaj opcję --text")
    if not t.strip():
        raise InputError("pusty tekst — nie ma czego analizować")
    return ingest.from_text(t), "text", None


def _print_analysis(ctx: Ctx, r: dict) -> None:
    st = ctx.st
    camp = r["campaign"]
    head = r["decision_label"] + (f" → {camp['code']} · {camp['name']}" if camp else "")
    colour = {"known_campaign": "green", "duplicate": "magenta", "merge_proposal": "yellow", "new_campaign": "cyan"}[r["decision"]]
    ctx.out(f"Decyzja: {st(head, colour, 'bold')}   [{r['decision']}]")
    ctx.out(wrap(r["decision_hint"], ctx.width))
    near = r["nearest"]
    ctx.out(kv([
        ("materiał", f"{trunc(r['name'], 70)} · id {r['material_id']}"),
        ("najbliższy znany materiał", f"{trunc(near['material_name'], 40)} ({near['code']} · {near['name']}), d = {num(near['distance'])}"
         if near else None),
        ("podobna rodzina", f"{r['similar_family']['code']} · {r['similar_family']['name']}" if r["similar_family"] else None),
        ("zapis", f"zapisano w bazie ({show_path(ctx.engine.store.path)})" if r["kept"]
         else "nie zapisano — analiza na sucho (--dry)"),
    ], style=st, width=ctx.width))
    if r["scores"]:
        ctx.heading("Najbliższe kampanie (odległość do najbliższego materiału kampanii, 1-NN)")
        ctx.out(table(["KOD", "NAZWA", "MAT.", "p", "d"],
                      [[s["code"], s["name"], s["size"], num(s["score"]), num(s["distance"])] for s in r["scores"]],
                      align="llrrr", limits={1: 60}, style=st, indent=2))
    if r["links"]:
        ctx.heading("Dowody — najbliższe materiały w bazie")
        rows = []
        for l in r["links"]:
            o = l["other"]
            ex = l["explain"]
            ids = "; ".join(it["detail"] for g in ex["identifiers"] for it in g["items"][:2])
            vs = ", ".join(f"{v['label']} {v['score']:.2f}" for v in sorted((v for v in ex["views"] if v["available"]),
                                                                           key=lambda v: -v["score"]) if v["score"] > 0)
            rows.append([o.get("display_name") or o["name"], _camp_code(o.get("campaign")), num(l["p"]), num(l["distance"]),
                         _rel(ctx, l["relation"], l["relation_label"]), "; ".join(x for x in (ids, vs) if x) or ex["basis"]])
        ctx.out(table(["MATERIAŁ", "KAMP.", "p", "d", "RELACJA", "UZASADNIENIE"], rows, align="llrr", limits={0: 26}, flex=5,
                      width=ctx.width, style=st, indent=2))
        ctx.out(wrap("Najbliższa para: " + r["links"][0]["explain"]["rule"] + " " + r["links"][0]["explain"]["formula"], ctx.width))
    f = r["features"]
    from .similarity import counted

    others = {mid: g for mid, (g, _) in ctx.engine.store.all().items() if mid != r["material_id"]}
    seen = Counter((t, v) for g in others.values() for t, vals in g.get("indicators", {}).items() for v in set(vals))
    n = len(others)
    rows = []
    for g in f["indicators"]:
        if not g["linking"]:
            continue
        for it in g["items"]:
            for v in it["values"][:5]:
                k = seen.get((it["type"], v["value"]), 0)
                status = (("nowa wartość", "dim") if k == 0 else (f"łączy z {k} mat.", "green") if counted(k + 1, n + 1)
                          else ("zbyt popularne — pomijane", "yellow"))
                rows.append([g["label"], it["type_label"], v["display"], f"{k}/{n}", status])
            hidden = len(it["values"]) - min(5, len(it["values"])) + it.get("more", 0)
            if hidden:
                rows.append([g["label"], it["type_label"], (f"… i {hidden} kolejnych", "dim"), "", ""])
    ctx.heading(f"Identyfikatory nowego materiału (W BAZIE = ile z {n} pozostałych materiałów ma tę wartość)")
    if rows:
        ctx.out(table(["GRUPA", "ŚLAD", "WARTOŚĆ", "W BAZIE", "STATUS"], rows, align="lllr", limits={0: 24, 1: 30}, flex=2,
                      width=ctx.width, style=st, indent=2))
    else:
        ctx.out("  (brak identyfikatorów)")
    views = [v["label"] for v in f["views"] if v["available"]]
    desc = [(row["label"].lower(), ", ".join(row["value"]) if isinstance(row["value"], list) else row["value"]) for row in f["llm"]]
    ctx.out()
    ctx.out(kv([("dostępne widoki treści", ", ".join(views) or "żaden — materiału nie da się porównać treścią"), *desc,
                ("osoby", join_more(list(f["persons"]["faces"]) + list(f["persons"]["named"]), 6)),
                ("uwagi", join_more(f["notes"], 4, " | "))], style=st, indent=0, width=ctx.width))


def cmd_add(ctx: Ctx) -> int:
    a = ctx.args
    keep = not a.dry
    progress = (lambda s: None) if ctx.quiet else (lambda s: ctx.note(f"  {s}"))
    ctx.open(write=keep)
    api = ctx.api
    m, mode, cleanup = _new_material(ctx, progress)
    try:
        ctx.note(f"Analiza ({ {'file': 'plik', 'folder': 'folder', 'url': 'adres URL', 'text': 'tekst'}[mode] }): {trunc(m.name, 70)}")
        res = ctx.engine.analyse_new(m, use_llm=not a.no_llm, keep=keep, progress=progress)
        meta = {"mode": mode, "source": str(a.target)[:200], "use_llm": not a.no_llm, "keep": keep,
                "render": mode == "url" and not a.no_render}
        payload = api._analysis_payload(res, keep, meta)
    finally:
        if cleanup:
            cleanup()
    if a.json:
        ctx.json(payload)
        return EXIT_OK
    _print_analysis(ctx, payload)
    if keep:
        ctx.hint(f"\nDalej: {PROG} material {payload['material_id']}")
    return EXIT_OK


def _import_dataset(ctx: Ctx, root: Path, use_llm: bool, force: bool, enrich_online: bool | None = None) -> int:
    ctx.open(write=True)
    before = ctx.engine.store.count()
    n = ctx.engine.add_dataset(root, use_llm=use_llm, progress=lambda s: ctx.note(s), force=force, enrich_online=enrich_online)
    after = ctx.engine.store.count()
    ctx.out(wrap(f"Przetworzono {n} przypadków z {show_path(root)}: {after - before} nowych, {n - (after - before)} "
                 + ("przeliczonych ponownie (--force)" if force else "już było w bazie (pominięte; --force analizuje ponownie)")
                 + f". Baza {show_path(ctx.engine.store.path)} ma {after} materiałów.", ctx.width, 0))
    ctx.compute(need_materials=False)
    if ctx.items:
        ctx.out()
        ov = ctx.api.overview()
        _print_campaigns(ctx, ov, ov["campaigns"])
    return EXIT_OK


def cmd_ingest(ctx: Ctx) -> int:
    a = ctx.args
    root = Path(a.root).expanduser()
    if not root.is_dir():
        raise InputError(f"nie znaleziono folderu zbioru: {a.root}",
                         "podaj folder, w którym każdy podfolder to jeden przypadek (strony, zrzuty, wideo, pliki .txt)")
    if not any(p.is_dir() for p in root.iterdir()):
        raise InputError(f"folder {a.root} nie ma podfolderów z przypadkami",
                         f"każdy podfolder to jeden materiał; pojedynczy przypadek dodaj przez `{PROG} add {a.root}`")
    return _import_dataset(ctx, root, use_llm=not a.no_llm, force=a.force)


def cmd_demo(ctx: Ctx) -> int:
    """The synthetic dataset shipped with the code: invented cases on .example domains, so no LLM and no lookups."""
    from . import config

    root = config.DEMO_DATASET
    if not root.is_dir():
        raise EnvError(f"brak zbioru demonstracyjnego: {show_path(root)}",
                       "zbiór jest w repozytorium w tests/fixtures/synthetic_dataset — pobierz pełne repozytorium")
    ctx.note("Zbiór demonstracyjny: zmyślone przypadki (domeny .example), bez modelu językowego i bez zapytań do sieci.")
    return _import_dataset(ctx, root, use_llm=False, force=ctx.args.force, enrich_online=False)


# =============================================================================== export / serve
EXPORT_KINDS = ["graph.html", "graph.cypher", "campaigns.json", "links.csv"]


def cmd_export(ctx: Ctx) -> int:
    from . import config

    a = ctx.args
    kinds = a.only or EXPORT_KINDS
    out = Path(a.out).expanduser() if a.out else config.EXPORTS
    ctx.load()
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputError(f"nie można utworzyć katalogu {a.out}: {exc}")
    eng, cl, items = ctx.engine, ctx.cl, ctx.items
    written = []
    if "graph.html" in kinds:
        written.append(eng.graph_html(out / "graph.html"))
    if "graph.cypher" in kinds:
        written.append(eng.export_cypher(out / "graph.cypher"))
    if "campaigns.json" in kinds:
        p = out / "campaigns.json"
        p.write_text(json.dumps([{**prof, "members": [items[m][0]["name"] for m in prof["members"]]} for prof in cl["profiles"]],
                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        written.append(p)
    if "links.csv" in kinds:
        p = out / "links.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["a", "b", "p", "distance", "relation", "views", "explanation"])
            for l in sorted(cl["links"], key=lambda l: (-l.p, l.distance)):
                if l.relation != "none":
                    w.writerow([items[l.a][0]["name"], items[l.b][0]["name"], round(l.p, 3), round(l.distance, 3), l.relation,
                                json.dumps({k: round(v, 3) for k, v in l.views.items()}), l.explain(8)])
        written.append(p)
    if a.json:
        ctx.json({"directory": str(out), "files": [{"kind": Path(p).name, "path": str(p), "bytes": Path(p).stat().st_size}
                                                   for p in written]})
        return EXIT_OK
    for p in written:
        ctx.out(str(p))
    return EXIT_OK


def cmd_serve(ctx: Ctx) -> int:
    import socket

    from . import config

    a = ctx.args
    try:
        import uvicorn
    except ImportError:
        raise EnvError("brak pakietu uvicorn", "zainstaluj zależności: uv pip install --python .venv/bin/python -r requirements.txt")
    try:
        with socket.socket(socket.AF_INET6 if ":" in a.host else socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((a.host, a.port))
    except OSError as exc:
        raise EnvError(f"nie można nasłuchiwać na {a.host}:{a.port} ({exc.strerror or exc})",
                       ["port jest zajęty — być może panel już działa; wybierz inny, np. --port 8770",
                        "do samego odczytu panel nie jest potrzebny: polecenia tekstowe czytają bazę bezpośrednio"])
    path = store_path(a)
    if a.store:
        os.environ["FTF_STORE"] = str(path)
        ctx.open(write=True)
        ctx._saved = None                    # the server keeps this engine for its whole life
        ctx.engine = None
    if not (config.ROOT / "web" / "dist" / "index.html").exists():
        print("uwaga: panel WWW nie jest zbudowany — uruchom: cd web && npm ci && npm run build   "
              "(samo API pod /api działa mimo to)", file=ctx.stderr, flush=True)
    if not path.exists():
        ctx.note(f"uwaga: baza {show_path(path)} nie istnieje — panel wystartuje z pustą bazą (materiały dodasz na stronie "
                 f"„Analizuj materiał” albo przez `{PROG} ingest`)")
    ctx.out(f"FakerAlpha UI: http://{a.host}:{a.port}   (baza: {show_path(path)}; Ctrl+C kończy)")
    try:
        ctx.stdout.flush()
    except Exception:
        pass
    uvicorn.run("ftf.api:app", host=a.host, port=a.port, log_level="info" if ctx.verbose else "warning")
    return EXIT_OK


# =============================================================================== argument parser
OVERVIEW = f"""\
FakerAlpha {__version__} (Follow the Fake) — łączy podejrzane reklamy w kampanie i uzasadnia każde powiązanie.
Wszystko, co pokazuje panel analityka, jest tu dostępne jako tekst albo JSON.

Co jest w bazie
  status                 która baza, ile materiałów i kampanii, konfiguracja
  campaigns              lista kampanii z najmocniejszymi wspólnymi śladami, duplikaty, rodziny
  campaign C1            jedna kampania: materiały, wspólne ślady, najsilniejsze pary, najbliższe otoczenie
  materials [tekst]      lista materiałów (z filtrem)
  material <id|nazwa>    jeden materiał: identyfikatory z df, widoki treści, najbliższe materiały, opis
  search <tekst>         szukaj w materiałach, kampaniach i wartościach śladów

Dlaczego materiały są powiązane
  links                  pary materiałów z uzasadnieniem
  pair <A> <B>           jedna para: relacja, wspólne identyfikatory, podobieństwo w widokach, obliczenie d
  trace <wartość>        wszystkie materiały z daną wartością (domena, piksel, telefon, osoba…)
  matrix                 macierz bliskości wszystkich materiałów

Jakość grupowania
  metrics                metody grupowania (silhouette, ARI), rozkład odległości, co łączy pary
  eval <etykiety.csv>    precyzja / czułość / F1 par, B-cubed i ARI względem własnych etykiet

Nowe dane (jedyne polecenia, które zapisują do bazy)
  add <cel>              analiza nowego materiału — plik, folder, URL albo tekst — z decyzją i dowodami
                         (--dry: bez zapisu; alias: analyse)
  ingest <folder>        import zbioru: każdy podfolder to jeden przypadek
  demo                   import zbioru demonstracyjnego (8 zmyślonych przypadków, bez sieci, kilkanaście sekund)

Eksport, panel, słowniczek
  export                 graph.html, graph.cypher, campaigns.json, links.csv
  serve                  panel WWW i API (http://127.0.0.1:8765)
  glossary               pojęcia: typy śladów, widoki treści, relacje, decyzje, progi

Pierwsze kroki
  {PROG} status                              czy jest baza i co w niej jest
  {PROG} demo                                jeśli bazy jeszcze nie ma: zbiór demonstracyjny
  {PROG} ingest <folder_zbioru> --no-llm     albo własny zbiór przypadków
  {PROG} campaigns                           kampanie
  {PROG} campaign C1                         szczegóły pierwszej z nich
  {PROG} add "treść podejrzanej reklamy" --dry --no-llm

Każde polecenie ma własną pomoc z przykładami: {PROG} <polecenie> --help
Polecenia odczytu przyjmują --json (stabilne klucze, do skryptów). Pełny opis: docs/CLI.md

Baza: --store ŚCIEŻKA albo zmienna FTF_STORE; domyślnie <FTF_ROOT>/data/store/ftf.sqlite.
Kody wyjścia: 0 ok · 1 błąd nieoczekiwany · 2 złe wywołanie · 3 brak bazy / pusta baza · 4 nie ma takiego
materiału, kampanii lub śladu · 5 złe dane wejściowe · 6 środowisko (np. zajęty port) · 130 przerwano
"""


class _Help(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=30, width=min(110, output_width() or 110))

    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, "Użycie: " if prefix is None else prefix)


_ARGPARSE_PL = [(r"^argument <polecenie>: invalid choice: '(.*?)' \(choose from (.*)\)$", None),
                (r"^the following arguments are required: (.*)$", "brak wymaganych argumentów: {0}"),
                (r"^unrecognized arguments: (.*)$", "nieznane argumenty: {0}"),
                (r"^argument (.*?): invalid choice: (.*?) \(choose from (.*)\)$", "argument {0}: niedozwolona wartość {1} (dozwolone: {2})"),
                (r"^argument (.*?): invalid (\w+) value: (.*)$", "argument {0}: niepoprawna wartość {2} (oczekiwano: {1})"),
                (r"^argument (.*?): expected one argument$", "argument {0}: brak wartości"),
                (r"^argument (.*?): expected at least one argument$", "argument {0}: brak wartości")]


_COMMON_DESTS = {"store", "verbose", "quiet", "color", "wide", "help"}


class _Parser(argparse.ArgumentParser):
    def _add_own_usage(self, formatter) -> None:
        """Usage line without the common options (they are listed in their own section of the help)."""
        own = [a for a in self._actions if a.dest not in _COMMON_DESTS] if self.usage is None else self._actions
        formatter.add_usage(self.usage, own, self._mutually_exclusive_groups)

    def format_usage(self):
        formatter = self._get_formatter()
        self._add_own_usage(formatter)
        return formatter.format_help()

    def format_help(self):
        formatter = self._get_formatter()
        self._add_own_usage(formatter)
        formatter.add_text(self.description)
        for group in self._action_groups:
            formatter.start_section(group.title)
            formatter.add_text(group.description)
            formatter.add_arguments(group._group_actions)
            formatter.end_section()
        formatter.add_text(self.epilog)
        return formatter.format_help()

    def error(self, message):
        """Usage errors: Polish message on stderr, a suggestion for a mistyped command, exit code 2."""
        import difflib
        import re

        hints = []
        for rx, fmt in _ARGPARSE_PL:
            m = re.match(rx, message, re.S)
            if not m:
                continue
            if fmt is None:
                known = [c.strip(" '") for c in m.group(2).split(",")]
                message = f"nieznane polecenie „{m.group(1)}”"
                close = difflib.get_close_matches(m.group(1), known, n=2, cutoff=0.6)
                if close:
                    hints.append("czy chodziło o: " + ", ".join(close) + "?")
                hints.append("polecenia: " + ", ".join(known))
            else:
                groups = [{"float": "liczba", "int": "liczba całkowita"}.get(g, g) for g in m.groups()]
                message = fmt.format(*groups)
            break
        self.print_usage(sys.stderr)
        print(f"błąd: {message}", file=sys.stderr)
        for h in hints:
            print(f"  {h}", file=sys.stderr)
        print(f"  pomoc: {self.prog} --help", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _common(defaults: bool) -> argparse.ArgumentParser:
    """Options accepted both before and after the command. In the per-command copy the defaults are suppressed, so
    a value given before the command is not overwritten by the command's default."""
    d = (lambda v: v) if defaults else (lambda v: argparse.SUPPRESS)
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("opcje wspólne (przed poleceniem albo po nim)")
    g.add_argument("--store", metavar="ŚCIEŻKA", default=d(None),
                   help="plik bazy SQLite; domyślnie zmienna FTF_STORE, a bez niej <FTF_ROOT>/data/store/ftf.sqlite")
    g.add_argument("-v", "--verbose", action="count", default=d(0),
                   help="więcej informacji na stderr: -v kroki i czasy, -vv diagnostyka; przy błędzie pełny ślad stosu")
    g.add_argument("-q", "--quiet", action="store_true", default=d(False), help="bez komunikatów postępu i podpowiedzi")
    g.add_argument("--color", choices=["auto", "always", "never"], default=d("auto"),
                   help="kolor: auto = tylko w terminalu i gdy nie ustawiono NO_COLOR (domyślnie)")
    g.add_argument("--no-color", dest="color", action="store_const", const="never", default=d("auto"), help="to samo co --color never")
    g.add_argument("--wide", action="store_true", default=d(False),
                   help="nie skracaj tabel do szerokości terminala (poza terminalem limit to $COLUMNS albo 140 znaków)")
    g.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="pokaż tę pomoc i zakończ")
    return p


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog=PROG, formatter_class=_Help, add_help=False, parents=[_common(True)], description=OVERVIEW,
                 usage=f"{PROG} [opcje wspólne] <polecenie> [argumenty]")
    ap.add_argument("-V", "--version", action="version", version=f"FakerAlpha {__version__}", help="pokaż wersję i zakończ")
    ap._optionals.title = "opcje"
    sub = ap.add_subparsers(dest="cmd", metavar="<polecenie>", parser_class=_Parser, help=argparse.SUPPRESS)
    common = _common(False)

    def add(name: str, fn, summary: str, examples: list[str], aliases: tuple = (), json_flag: bool = True, more: str = ""):
        epilog = "Przykłady:\n" + "\n".join(f"  {e}" for e in examples) + (f"\n\n{more}" if more else "")
        p = sub.add_parser(name, aliases=list(aliases), parents=[common], add_help=False, formatter_class=_Help,
                           prog=f"{PROG} {name}", description=summary, epilog=epilog)
        p._positionals.title, p._optionals.title = "argumenty", "opcje"
        p.set_defaults(fn=fn, cmd_name=name)
        if json_flag:
            p.add_argument("--json", action="store_true", help="wynik jako JSON na stdout (stabilne klucze, do skryptów)")
        return p

    add("status", cmd_status,
        "Która baza jest używana, ile ma materiałów, kampanii i par, progi metody, dostępność LLM i panelu.\n"
        "Kod wyjścia 0 oznacza bazę z materiałami, 3 — brak bazy albo pustą bazę.",
        [f"{PROG} status", f"{PROG} --store data/store/ftf_harvest.sqlite status --json",
         f"FTF_STORE=/dane/inna.sqlite {PROG} status"])

    p = add("campaigns", cmd_campaigns,
            "Lista kampanii: kod, liczba materiałów, nazwa, typ oszustwa, liczba wspólnych wartości, średnia bliskość\n"
            "par, materiały i domeny; potem najmocniejsze wspólne ślady, duplikaty i rodziny (strona „Kampanie”).",
            [f"{PROG} campaigns", f"{PROG} campaigns --min-size 2", f"{PROG} campaigns --json | jq '.campaigns[].name'"])
    p.add_argument("--min-size", type=int, default=1, metavar="N", help="tylko kampanie z co najmniej N materiałami (domyślnie 1)")

    p = add("campaign", cmd_campaign,
            "Jedna kampania: materiały, który ślad łączy które materiały, łańcuch najsilniejszych par, profil\n"
            "podobieństwa w widokach treści i najbliższe materiały spoza kampanii (strona „Kampania”).",
            [f"{PROG} campaign C1", f"{PROG} campaign 2 --all-pairs", f"{PROG} campaign --of syn-04-fundusz",
             f"{PROG} campaign C1 --json | jq '.matrix[] | {{type, members}}'"],
            more="Kody kampanii (C1, C2…) nadawane są od największej; po dodaniu materiałów numeracja może się zmienić.")
    p.add_argument("ref", nargs="?", metavar="KAMPANIA", help="kod kampanii: C1, c1 albo 1")
    p.add_argument("--of", metavar="MATERIAŁ", help="zamiast kodu: kampania, do której należy ten materiał (id albo nazwa)")
    p.add_argument("--all-pairs", action="store_true", help="wszystkie pary wewnątrz kampanii zamiast samego łańcucha najsilniejszych")

    p = add("materials", cmd_materials,
            "Lista materiałów. Opcjonalny tekst filtruje po nazwie, identyfikatorze, tytule, produkcie, typie oszustwa,\n"
            "osobach, domenach i kampanii (bez rozróżniania wielkości liter i polskich znaków).",
            [f"{PROG} materials", f"{PROG} materials kardivix", f"{PROG} materials --campaign C1 --json",
             f"{PROG} materials --source url --limit 20"])
    p.add_argument("query", nargs="?", metavar="TEKST", help="pokaż tylko materiały zawierające ten tekst")
    p.add_argument("--campaign", metavar="KAMPANIA", help="tylko materiały tej kampanii (C1, 1)")
    p.add_argument("--source", metavar="ŹRÓDŁO", help="tylko materiały z tego źródła: organizer, upload, url, text, scheduler")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="najwyżej N wierszy (domyślnie wszystkie)")

    p = add("material", cmd_material,
            "Jeden materiał: opis (typ oszustwa, osoby, słowa kluczowe, infrastruktura), wartości identyfikatorów z df\n"
            "i informacją, czy łączą, dostępne widoki treści oraz najbliższe materiały z uzasadnieniem.",
            [f"{PROG} material syn-03-kardivix-news", f"{PROG} material c1ddb81f1b96 --all-values", f"{PROG} material c1dd --json"],
            more="MATERIAŁ to identyfikator (kolumna ID), jego początek (co najmniej 4 znaki) albo nazwa materiału.")
    p.add_argument("ref", metavar="MATERIAŁ", help="identyfikator, jego początek albo nazwa")
    p.add_argument("--all-values", action="store_true", help="wszystkie wartości identyfikatorów (domyślnie do 6 na typ; w JSON do 12)")

    p = add("search", cmd_search,
            "Szukanie tekstu w nazwach, tytułach, produktach, osobach i wartościach identyfikatorów. Zwraca pasujące\n"
            "kampanie, materiały i ślady; kod kampanii (np. C2) znajduje tę kampanię. Jak wyszukiwarka w nagłówku panelu.",
            [f"{PROG} search kardivix", f"{PROG} search \"złoty fundusz\" --json", f"{PROG} search C2"])
    p.add_argument("query", nargs="+", metavar="TEKST", help="co najmniej 2 znaki")

    p = add("links", cmd_links,
            "Pary materiałów od najbliższych, z relacją i najważniejszymi przesłankami. p = 1 − D: 1.00 przy wspólnym\n"
            "identyfikatorze, inaczej 1 − d (d = odległość treści).",
            [f"{PROG} links", f"{PROG} links --min 0.4 --relation same_campaign --relation duplicate",
             f"{PROG} links --material syn-04-fundusz --min 0", f"{PROG} links --json | jq '.links[] | [.a_info.name, .b_info.name, .p]'"])
    p.add_argument("--min", type=float, default=0.1, metavar="P", help="najmniejsza bliskość p (domyślnie 0.1)")
    p.add_argument("--relation", action="append", choices=["duplicate", "same_campaign", "similar", "none"],
                   help="tylko pary o tej relacji (można powtórzyć)")
    p.add_argument("--material", metavar="MATERIAŁ", help="tylko pary z tym materiałem")
    p.add_argument("--campaign", metavar="KAMPANIA", help="tylko pary wewnątrz tej kampanii")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="najwyżej N par (domyślnie wszystkie)")

    p = add("pair", cmd_pair,
            "Pełne wyjaśnienie jednej pary: relacja i reguła, która ją dała, wspólne identyfikatory z df, wartości\n"
            "pominięte jako zbyt popularne, podobieństwo w każdym widoku treści i obliczenie odległości d (strona „Para”).",
            [f"{PROG} pair syn-01-kardivix syn-03-kardivix-news", f"{PROG} pair 4799a4116662 c1ddb81f1b96 --json"])
    p.add_argument("a", metavar="A", help="pierwszy materiał (id, początek id albo nazwa)")
    p.add_argument("b", metavar="B", help="drugi materiał")

    p = add("trace", cmd_trace,
            "Wszystkie materiały, które mają daną wartość śladu, jej df i informacja, czy liczy się przy łączeniu\n"
            "(strona „Ślad”). Wartość musi być pełna; fragmentu szukaj przez `search`.",
            [f"{PROG} trace kardivix-promo.example", f"{PROG} trace --type fb_pixel 900000000000001",
             f"{PROG} trace --type person \"Jan Kowalski\"",
             f"{PROG} trace kardivix-promo.example --json | jq '.traces[].materials[].name'"],
            more=f"Typy śladów wypisuje `{PROG} glossary`. Bez --type przeszukiwane są wszystkie typy i osoby.")
    p.add_argument("value", nargs="+", metavar="WARTOŚĆ", help="domena, ID piksela, telefon, nazwa produktu, osoba…")
    p.add_argument("--type", metavar="TYP", help="ogranicz do jednego typu, np. landing_domain, fb_pixel, phone, product, person")

    p = add("matrix", cmd_matrix,
            "Macierz bliskości p wszystkich par (×100), wiersze i kolumny uporządkowane kampaniami (strona „Macierz”).",
            [f"{PROG} matrix", f"{PROG} matrix --campaign C1 --distance", f"{PROG} matrix --json | jq '.p'"])
    p.add_argument("--campaign", metavar="KAMPANIA", help="tylko materiały jednej kampanii")
    p.add_argument("--distance", action="store_true", help="pokaż odległość treści d zamiast bliskości p")

    p = add("metrics", cmd_metrics,
            "Jakość grupowania: porównanie metod na tych samych odległościach (silhouette, ARI względem FakerAlpha\n"
            "i względem data/labels_dane.csv), wysokości scaleń dendrogramu, rozkład odległości, co łączy pary,\n"
            "rozdzielczość widoków, pokrycie cech (strona „Przestrzeń cech” i wykresy strony „Kampanie”).",
            [f"{PROG} metrics", f"{PROG} metrics --methods", f"{PROG} metrics --json | jq '.methods[] | {{key, silhouette, ari_labels}}'"],
            more="JSON zawiera też współrzędne rzutów MDS / t-SNE i dendrogram, z których panel rysuje mapę.")
    p.add_argument("--methods", action="store_true", help="dopisz objaśnienie każdej metody grupowania")

    p = add("eval", cmd_eval,
            "Zgodność kampanii z własnymi etykietami: precyzja, czułość i F1 par, B-cubed, ARI oraz ARI punktu\n"
            "odniesienia HDBSCAN. Plik CSV: `id_lub_nazwa_materiału,etykieta`, linie z # są pomijane.",
            [f"{PROG} eval data/labels_dane.csv", f"{PROG} eval data/labels_dane.csv --json"])
    p.add_argument("labels", metavar="ETYKIETY.csv", help="plik CSV z etykietami referencyjnymi")

    p = add("add", cmd_add,
            "Analiza jednego nowego materiału i decyzja open-set: duplikat, znana kampania, propozycja scalenia albo\n"
            "nowy wzorzec — z dowodami (najbliższe materiały, wspólne identyfikatory, podobieństwo w widokach).\n"
            "CEL: istniejący plik (zrzut, wideo, HTML, HAR, MHTML, ZIP przypadku) lub folder przypadku, adres\n"
            "http(s) albo dowolny tekst (treść reklamy, nazwa produktu). Bez --dry materiał trafia do bazy.",
            [f"{PROG} add zrzut_reklamy.png --dry", f"{PROG} add ./przypadek_17 --no-llm",
             f"{PROG} add \"Kardivix — kapsułki na serce, tylko dziś -50%\" --dry --no-llm --json",
             f"{PROG} add https://example.com --dry --no-render --no-llm"],
            aliases=("analyse",),
            more="Bezpieczeństwo i prywatność:\n"
                 "  Adres URL jest pobierany z tego komputera (3 profile klienta, opcjonalnie headless Chromium). Nie kieruj\n"
                 "  polecenia na działające strony oszustów poza odizolowanym środowiskiem — patrz uwaga w README, sekcja\n"
                 "  „Większy zbiór badawczy”.\n"
                 "  Bez --no-llm tekst materiału może trafić do zewnętrznego modelu językowego (FTF_LLM), a domeny do\n"
                 "  publicznych usług RDAP / DNS / crt.sh (wyłącza je FTF_ENRICH=0).\n"
                 "  --dry nie zapisuje nic w bazie; pliki robocze analizy zostają w data/artifacts i data/cache.")
    p.add_argument("target", metavar="CEL", help="plik, folder, adres URL albo tekst")
    p.add_argument("--no-llm", action="store_true", help="bez modelu językowego: atrybuty opisowe z reguł słownikowych")
    p.add_argument("--dry", action="store_true", help="tylko analiza i decyzja, bez zapisu w bazie (baza otwierana tylko do odczytu)")
    p.add_argument("--text", action="store_true", help="traktuj CEL jako tekst, nawet jeśli wygląda jak ścieżka albo adres")
    p.add_argument("--no-render", action="store_true", help="adres URL: bez renderowania w headless Chromium (samo pobranie HTTP)")

    p = add("ingest", cmd_ingest,
            "Import zbioru: każdy podfolder FOLDERU to jeden przypadek (zapisane strony, HAR, zrzuty, wideo, .txt).\n"
            "Przypadki już obecne w bazie są pomijane. Na końcu wypisuje kampanie. Zapisuje do bazy.",
            [f"{PROG} ingest data/organizer/dane", f"{PROG} ingest ./nowe_przypadki --no-llm",
             f"{PROG} --store data/store/proba.sqlite ingest ./nowe_przypadki --force"],
            json_flag=False,
            more="Bez --no-llm tekst każdego przypadku może trafić do zewnętrznego modelu językowego (zmienna FTF_LLM;\n"
                 "FTF_LLM=none wyłącza), a domeny do publicznych usług RDAP / DNS / crt.sh (wyłącza je FTF_ENRICH=0).")
    p.add_argument("root", metavar="FOLDER", help="folder zbioru")
    p.add_argument("--no-llm", action="store_true", help="bez modelu językowego: atrybuty opisowe z reguł słownikowych")
    p.add_argument("--force", action="store_true", help="analizuj ponownie także przypadki, które już są w bazie")

    p = add("demo", cmd_demo,
            "Import zbioru demonstracyjnego dołączonego do kodu (tests/fixtures/synthetic_dataset): 8 zmyślonych\n"
            "przypadków w domenach .example, które układają się w kampanie, duplikat i rodzinę. Działa bez modelu\n"
            "językowego i bez zapytań do sieci, trwa kilkanaście sekund. Zapisuje do bazy.",
            [f"{PROG} demo", f"{PROG} --store data/store/demo.sqlite demo", f"{PROG} demo --force"],
            json_flag=False,
            more="Materiały zbioru mają nazwy syn-01 … syn-08. Żeby zacząć od pustej bazy z własnymi danymi, wskaż inną\n"
                 "bazę przez --store albo usuń plik bazy.")
    p.add_argument("--force", action="store_true", help="analizuj ponownie także przypadki, które już są w bazie")

    p = add("export", cmd_export,
            "Zapisuje pliki eksportu i wypisuje ich ścieżki: graph.html (interaktywny graf), graph.cypher (Neo4j),\n"
            "campaigns.json (profile kampanii), links.csv (pary z uzasadnieniem, bez relacji „brak powiązania”).",
            [f"{PROG} export", f"{PROG} export --out /tmp/raport --only links.csv --only campaigns.json",
             f"{PROG} export --json | jq -r '.files[].path'"],
            more="Domyślny katalog to <FTF_ROOT>/data/exports. Bazy polecenie nie zmienia.")
    p.add_argument("--out", metavar="KATALOG", help="katalog docelowy (domyślnie data/exports)")
    p.add_argument("--only", action="append", choices=EXPORT_KINDS, metavar="PLIK",
                   help=f"tylko ten plik (można powtórzyć): {', '.join(EXPORT_KINDS)}")

    p = add("serve", cmd_serve,
            "Uruchamia panel analityka i API pod http://HOST:PORT. Panel trzeba wcześniej zbudować:\n"
            "cd web && npm ci && npm run build (bez tego działa samo API pod /api).",
            [f"{PROG} serve", f"{PROG} serve --host 0.0.0.0 --port 8765",
             f"FTF_STORE=data/store/ftf_harvest.sqlite {PROG} serve --port 8790"],
            json_flag=False)
    p.add_argument("--host", default="127.0.0.1", help="adres nasłuchu (domyślnie 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="port (domyślnie 8765)")

    add("glossary", cmd_glossary,
        "Słowniczek: kroki metody, miary (d, p, df), typy identyfikatorów i ich grupy, ślady opisowe, widoki treści,\n"
        "relacje par i decyzje dla nowego materiału, z aktualnymi progami. Nie wymaga bazy.",
        [f"{PROG} glossary", f"{PROG} glossary --json | jq '.identifier_groups[].types[].type'"],
        more="Przykłady w pomocy używają syntetycznego zbioru z tests/fixtures/synthetic_dataset (docs/CLI.md pokazuje, jak\n"
             "go zaimportować do osobnej bazy).")
    return ap


# =============================================================================== entry point
def _fail(ctx_err, style: Style, exc: CliError) -> int:
    print(f"{style('błąd:', 'red', 'bold')} {exc.message}", file=ctx_err)
    for h in exc.hints:
        print(f"  {h}", file=ctx_err)
    return exc.code


def main(argv=None) -> int:
    parser = build_parser()
    try:
        a = parser.parse_args(argv)
    except SystemExit as exc:                     # argparse: --help / --version exit 0, usage errors exit 2
        return exc.code if isinstance(exc.code, int) else (EXIT_OK if exc.code is None else EXIT_USAGE)
    if not getattr(a, "cmd", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    level = logging.ERROR if a.quiet else (logging.WARNING, logging.INFO, logging.DEBUG)[min(2, a.verbose)]
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)
    ctx = Ctx(a)
    try:
        return a.fn(ctx) or EXIT_OK
    except CliError as exc:
        return _fail(ctx.stderr, ctx.est, exc)
    except BrokenPipeError:                       # e.g. `... | head`: the reader went away, nothing is wrong
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        print("\nprzerwano", file=ctx.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:
        if type(exc).__name__ == "HTTPException":          # raised by the reused API helpers for unknown ids
            return _fail(ctx.stderr, ctx.est, NotFound(str(getattr(exc, "detail", exc))))
        if ctx.verbose:
            import traceback

            traceback.print_exc(file=ctx.stderr)
        print(f"{ctx.est('błąd wewnętrzny:', 'red', 'bold')} {type(exc).__name__}: {one_line(exc)}", file=ctx.stderr)
        if not ctx.verbose:
            print("  uruchom ponownie z -v, aby zobaczyć pełny ślad stosu", file=ctx.stderr)
        return EXIT_ERROR
    finally:
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
