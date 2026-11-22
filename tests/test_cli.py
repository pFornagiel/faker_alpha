"""Offline tests for the command line (ftf/cli.py): argument parsing, help, JSON shapes, exit codes, read-only access.

Every test uses a temporary SQLite store given with `--store`; the real data/store is never opened. Nothing is
fetched from the network: URL capture is mocked, the LLM is off (`--no-llm`) and domain enrichment is disabled
(`FTF_ENRICH=0`). The end-to-end class runs the real pipeline on the synthetic cases in tests/fixtures/ (invented
products, reserved `.example` domains).
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ftf import cli, cli_format, config, ingest
from ftf.store import Store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC_DATASET = FIXTURES / "synthetic_dataset"
SYNTHETIC_NEW_AD = FIXTURES / "synthetic_new_ad.html"
SYNTHETIC_LABELS = FIXTURES / "synthetic_labels.csv"

READ_COMMANDS = ["status", "campaigns", "campaign", "materials", "material", "search", "links", "pair", "trace", "matrix",
                 "metrics", "eval", "glossary", "export"]
ALL_COMMANDS = READ_COMMANDS + ["add", "ingest", "demo", "serve"]
PIXEL = "900000000000001"


def _feat(name: str, indicators: dict, product: str | None = None) -> dict:
    return {"name": name, "indicators": indicators, "llm": {"product_or_platform_name": product} if product else {}}


def make_store(path: Path) -> None:
    """Seven hand-made materials: alpha-1/2/3 share a pixel (one campaign, 3 of 7 is below the 50 % frequency cap),
    the other four stand alone. 21 pairs: 3 linked by the pixel, 18 unrelated."""
    st = Store(path)
    rows = [
        ("aaaa11110001", "alpha-1", {"fb_pixel": [PIXEL], "landing_domain": ["alpha-shop.example"]}, "Alphavit"),
        ("aaaa11110002", "alpha-2", {"fb_pixel": [PIXEL], "landing_domain": ["alpha-shop.example"]}, "Alphavit"),
        ("aaaa22220003", "alpha-3", {"fb_pixel": [PIXEL], "landing_domain": ["alpha-news.example"]}, None),
        ("bbbb33330004", "beta-1", {"landing_domain": ["beta-fund.example"], "telegram": ["beta_synthetic"]}, "Betafund"),
        ("cccc44440005", "gamma-1", {"landing_domain": ["gamma-lotto.example"]}, None),
        ("dddd55550006", "delta-1", {"landing_domain": ["delta-casino.example"]}, None),
        ("eeee66660007", "epsilon-1", {"landing_domain": ["epsilon-kurs.example"]}, None),
    ]
    for mid, name, ind, product in rows:
        st.upsert(ingest.Material(id=mid, name=name, source="test", source_ref=name), _feat(name, ind, product), {})
    st.db.close()


def run(*argv: str) -> tuple[int, str, str]:
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StoreCase(unittest.TestCase):
    """A fresh hand-made store per test class; `self.cli(...)` runs a command against it."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.td.name)
        cls.store = cls.dir / "cli.sqlite"
        make_store(cls.store)
        cls._env = mock.patch.dict(os.environ, {"FTF_ENRICH": "0"})
        cls._env.start()

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls.td.cleanup()

    def cli(self, *argv: str) -> tuple[int, str, str]:
        return run("--store", self.store, *argv)

    def json(self, *argv: str) -> dict:
        code, out, err = self.cli(*argv, "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIsInstance(data, dict, "every --json output is an object")
        return data


# =============================================================================== parsing and help
class TestParser(unittest.TestCase):
    def setUp(self):
        self.p = cli.build_parser()

    def test_old_invocations_keep_their_flags_and_defaults(self):
        a = self.p.parse_args(["ingest", "data/x", "--no-llm", "--force"])
        self.assertEqual((a.cmd, a.root, a.no_llm, a.force), ("ingest", "data/x", True, True))
        a = self.p.parse_args(["add", "plik.png", "--no-llm", "--dry"])
        self.assertEqual((a.cmd, a.target, a.no_llm, a.dry), ("add", "plik.png", True, True))
        self.assertEqual(self.p.parse_args(["campaigns"]).cmd, "campaigns")
        self.assertEqual(self.p.parse_args(["links"]).min, 0.1)
        self.assertEqual(self.p.parse_args(["links", "--min", "0.4"]).min, 0.4)
        self.assertEqual(self.p.parse_args(["export"]).cmd, "export")
        self.assertEqual(self.p.parse_args(["eval", "labels.csv"]).labels, "labels.csv")
        a = self.p.parse_args(["serve"])
        self.assertEqual((a.host, a.port), ("127.0.0.1", 8765))
        a = self.p.parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
        self.assertEqual((a.host, a.port), ("0.0.0.0", 9000))

    def test_common_options_before_or_after_the_command(self):
        before = self.p.parse_args(["--store", "x.sqlite", "-v", "campaigns"])
        after = self.p.parse_args(["campaigns", "--store", "x.sqlite", "-v"])
        for a in (before, after):
            self.assertEqual((a.store, a.verbose, a.quiet, a.color, a.wide), ("x.sqlite", 1, False, "auto", False))
        a = self.p.parse_args(["--store", "outer.sqlite", "status"])
        self.assertEqual(a.store, "outer.sqlite", "a command's default must not overwrite the value given before it")
        self.assertEqual(self.p.parse_args(["status", "--no-color"]).color, "never")
        self.assertEqual(self.p.parse_args(["-q", "status"]).quiet, True)

    def test_every_read_command_has_json_and_alias_works(self):
        args = {"campaign": ["C1"], "material": ["m"], "search": ["ab"], "pair": ["a", "b"], "trace": ["v"], "eval": ["l.csv"]}
        for name in READ_COMMANDS:
            a = self.p.parse_args([name, *args.get(name, []), "--json"])
            self.assertTrue(a.json, name)
        a = self.p.parse_args(["analyse", "tekst", "--dry", "--json"])
        self.assertIs(a.fn, cli.cmd_add)
        self.assertTrue(a.dry and a.json)

    def test_options_of_the_new_commands(self):
        a = self.p.parse_args(["links", "--relation", "duplicate", "--relation", "similar", "--material", "m1", "--limit", "5"])
        self.assertEqual((a.relation, a.material, a.limit), (["duplicate", "similar"], "m1", 5))
        a = self.p.parse_args(["campaign", "--of", "alpha-1", "--all-pairs"])
        self.assertEqual((a.ref, a.of, a.all_pairs), (None, "alpha-1", True))
        a = self.p.parse_args(["trace", "Jan", "Testowy", "--type", "person"])
        self.assertEqual((a.value, a.type), (["Jan", "Testowy"], "person"))
        a = self.p.parse_args(["export", "--out", "/tmp/x", "--only", "links.csv"])
        self.assertEqual((a.out, a.only), ("/tmp/x", ["links.csv"]))
        a = self.p.parse_args(["add", "x", "--text", "--no-render"])
        self.assertTrue(a.text and a.no_render)


class TestHelpAndUsage(unittest.TestCase):
    def test_top_level_help_is_an_overview(self):
        code, out, _ = run("--help")
        self.assertEqual(code, 0)
        for name in ALL_COMMANDS:
            self.assertRegex(out, rf"(?m)^  {name}\b", f"{name} missing from the overview")
        for needle in ("Pierwsze kroki", "FTF_STORE", "--store", "docs/CLI.md", "Kody wyjścia"):
            self.assertIn(needle, out)

    def test_every_command_help_has_an_example(self):
        for name in ALL_COMMANDS + ["analyse"]:
            code, out, _ = run(name, "--help")
            self.assertEqual(code, 0, name)
            self.assertIn("Przykłady:", out, name)
            shown = "add" if name == "analyse" else name
            self.assertIn(f"{cli.PROG} {shown}", out, name)
            self.assertIn("--store", out, name)

    def test_add_help_points_to_the_safety_note(self):
        _, out, _ = run("add", "--help")
        self.assertIn("README", out)
        self.assertIn("odizolowanym", out)

    def test_no_arguments_and_usage_errors_exit_2(self):
        code, out, err = run()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Pierwsze kroki", err)
        code, _, err = run("materiasl")
        self.assertEqual(code, 2)
        self.assertIn("nieznane polecenie", err)
        self.assertIn("materials", err)
        self.assertEqual(run("links", "--min", "abc")[0], 2)
        self.assertEqual(run("pair", "only-one")[0], 2)
        self.assertEqual(run("status", "--no-such-flag")[0], 2)

    def test_version(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn("FakerAlpha", out)

    def test_reference_documents_every_command_and_option(self):
        doc = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
        parser = cli.build_parser()
        commands = next(a for a in parser._actions if getattr(a, "choices", None) and "status" in a.choices).choices
        for name in ALL_COMMANDS:
            self.assertIn(f"\n### {name}\n", doc, f"docs/CLI.md has no section for `{name}`")
            for action in commands[name]._actions:
                for flag in action.option_strings:
                    if flag.startswith("--"):
                        self.assertIn(f"`{flag}", doc, f"docs/CLI.md does not mention {name} {flag}")
        for code in (cli.EXIT_USAGE, cli.EXIT_STORE, cli.EXIT_NOT_FOUND, cli.EXIT_INPUT, cli.EXIT_ENV, cli.EXIT_INTERRUPTED):
            self.assertIn(f"\n| {code} |", doc, f"exit code {code} is not in the table")
        for variable in ("FTF_STORE", "FTF_ROOT", "FTF_LLM", "FTF_ENRICH", "NO_COLOR", "COLUMNS"):
            self.assertIn(f"`{variable}`", doc)
        self.assertIn("docs/CLI.md", (ROOT / "README.md").read_text(encoding="utf-8"))


# =============================================================================== read commands
class TestReadCommands(StoreCase):
    def test_status(self):
        d = self.json("status")
        self.assertLessEqual({"version", "store", "store_exists", "n_materials", "n_campaigns", "n_multi", "n_singletons",
                              "n_pairs", "links", "by_source", "thresholds", "llm_backend", "web_ui_built"}, set(d))
        self.assertEqual((d["store_exists"], d["n_materials"], d["n_campaigns"], d["n_pairs"]), (True, 7, 5, 21))
        self.assertEqual(d["by_source"], {"test": 7})
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Materiały:", out)
        self.assertIn("tylko do odczytu", out)

    def test_campaigns(self):
        d = self.json("campaigns")
        self.assertLessEqual({"n_materials", "n_campaigns", "n_multi", "n_singletons", "campaigns", "duplicates", "families",
                              "thresholds"}, set(d))
        self.assertEqual([c["code"] for c in d["campaigns"]], ["C1", "C2", "C3", "C4", "C5"])
        c1 = d["campaigns"][0]
        self.assertLessEqual({"id", "code", "name", "size", "members", "domains", "top_shared", "n_shared", "mean_internal_p"}, set(c1))
        self.assertEqual((c1["id"], c1["size"]), (0, 3))
        self.assertEqual({m["name"] for m in c1["members"]}, {"alpha-1", "alpha-2", "alpha-3"})
        self.assertEqual(len(self.json("campaigns", "--min-size", "2")["campaigns"]), 1)
        code, out, _ = self.cli("campaigns")
        self.assertEqual(code, 0)
        self.assertIn("KOD", out)
        self.assertIn(PIXEL, out)

    def test_campaign_by_code_number_and_member(self):
        by_code = self.json("campaign", "C1")
        self.assertLessEqual({"id", "code", "name", "size", "members", "matrix", "chain", "links", "nearest_outside",
                              "view_profile", "n_pairs"}, set(by_code))
        self.assertEqual((by_code["code"], by_code["size"], by_code["n_pairs"]), ("C1", 3, 3))
        self.assertTrue(any(r["type"] == "fb_pixel" and len(r["members"]) == 3 for r in by_code["matrix"]))
        self.assertEqual(self.json("campaign", "1")["code"], "C1")
        self.assertEqual(self.json("campaign", "c1")["code"], "C1")
        self.assertEqual(self.json("campaign", "--of", "alpha-3")["code"], "C1")
        code, out, _ = self.cli("campaign", "C1", "--all-pairs")
        self.assertEqual(code, 0)
        for needle in ("Materiały", "Wspólne ślady", "Wszystkie pary w kampanii", "alpha-3"):
            self.assertIn(needle, out)

    def test_materials_list_and_filters(self):
        d = self.json("materials")
        self.assertEqual((d["n_total"], d["n_matched"], len(d["materials"])), (7, 7, 7))
        m = d["materials"][0]
        self.assertLessEqual({"id", "name", "display_name", "title", "source", "campaign", "domains", "signals"}, set(m))
        self.assertEqual(self.json("materials", "--campaign", "C1")["n_matched"], 3)
        self.assertEqual([x["name"] for x in self.json("materials", "beta")["materials"]], ["beta-1"])
        self.assertEqual(self.json("materials", "ALPHA")["n_matched"], 3, "the filter ignores case")
        self.assertEqual(self.json("materials", "aaaa2222")["n_matched"], 1, "the filter also matches ids")
        lim = self.json("materials", "--limit", "2")
        self.assertEqual((lim["n_matched"], len(lim["materials"])), (7, 2))
        self.assertEqual(self.json("materials", "--source", "url")["n_matched"], 0)
        code, out, _ = self.cli("materials")
        self.assertEqual(code, 0)
        self.assertIn("aaaa11110001", out)

    def test_material_by_id_prefix_and_name(self):
        d = self.json("material", "alpha-1")
        self.assertLessEqual({"id", "name", "campaign", "features", "links", "inputs"}, set(d))
        self.assertEqual(d["id"], "aaaa11110001")
        self.assertLessEqual({"indicators", "views", "n_corpus", "llm", "text", "web", "persons"}, set(d["features"]))
        values = {(it["type"], v["value"]): v["df"] for g in d["features"]["indicators"] for it in g["items"] for v in it["values"]}
        self.assertEqual(values[("fb_pixel", PIXEL)], 3)
        self.assertEqual(d["features"]["n_corpus"], 7)
        self.assertTrue(all("other" in l and "relation" in l and "p" in l for l in d["links"]))
        self.assertEqual(self.json("material", "aaaa11110001")["name"], "alpha-1")
        self.assertEqual(self.json("material", "bbbb")["name"], "beta-1")
        self.assertEqual(self.json("material", "gamma")["name"], "gamma-1")
        code, out, _ = self.cli("material", "alpha-1", "--all-values")
        self.assertEqual(code, 0)
        for needle in ("Identyfikatory", "łączy z 2 mat.", "Widoki treści", "Najbliższe materiały", "alpha-2"):
            self.assertIn(needle, out)

    def test_search(self):
        d = self.json("search", "alpha-shop")
        self.assertEqual(set(d), {"query", "materials", "campaigns", "traces"})
        self.assertEqual({m["name"] for m in d["materials"]}, {"alpha-1", "alpha-2"})
        self.assertTrue(any(t["type"] == "landing_domain" and t["n"] == 2 for t in d["traces"]))
        code, out, _ = self.cli("search", "nic", "takiego")
        self.assertEqual(code, 0)
        self.assertIn("Brak wyników", out)

    def test_links(self):
        d = self.json("links")
        self.assertEqual(set(d), {"min_p", "n_matched", "links"})
        self.assertEqual((d["min_p"], d["n_matched"]), (0.1, 3))
        l = d["links"][0]
        self.assertLessEqual({"a", "b", "p", "distance", "relation", "relation_label", "reasons", "a_info", "b_info"}, set(l))
        self.assertEqual(self.json("links", "--min", "0")["n_matched"], 21)
        self.assertEqual(self.json("links", "--min", "0", "--material", "beta-1")["n_matched"], 6)
        self.assertEqual(self.json("links", "--min", "0", "--relation", "none")["n_matched"], 18)
        self.assertEqual(len(self.json("links", "--min", "0", "--limit", "2")["links"]), 2)
        self.assertEqual(self.json("links", "--campaign", "C1")["n_matched"], 3)
        code, out, _ = self.cli("links", "--min", "0.1")
        self.assertEqual(code, 0)
        self.assertIn("UZASADNIENIE", out)
        self.assertIn("3 par", out)

    def test_pair(self):
        d = self.json("pair", "alpha-1", "alpha-3")
        self.assertLessEqual({"a", "b", "p", "distance", "relation", "relation_label", "rule", "must_link", "identifiers",
                              "ignored", "views", "formula"}, set(d))
        self.assertEqual((d["relation"], d["must_link"], d["p"]), ("same_campaign", True, 1.0))
        shared = [it for g in d["identifiers"] for it in g["items"]]
        self.assertTrue(any(it["type"] == "fb_pixel" and it["df"] == 3 for it in shared))
        self.assertEqual(self.json("pair", "alpha-1", "gamma-1")["relation"], "none")
        code, out, _ = self.cli("pair", "aaaa11110001", "aaaa22220003")
        self.assertEqual(code, 0)
        for needle in ("Relacja:", "Wspólne identyfikatory", "Podobieństwo w widokach treści", "Obliczenie odległości treści"):
            self.assertIn(needle, out)

    def test_trace(self):
        d = self.json("trace", PIXEL)
        self.assertEqual(set(d), {"query", "type", "traces"})
        t = d["traces"][0]
        self.assertLessEqual({"type", "type_label", "value", "display", "linking", "counted", "df", "n", "max_df", "materials"}, set(t))
        self.assertEqual((t["type"], t["df"], t["n"]), ("fb_pixel", 3, 7))
        self.assertEqual({m["name"] for m in t["materials"]}, {"alpha-1", "alpha-2", "alpha-3"})
        self.assertEqual(self.json("trace", "ALPHA-SHOP.example", "--type", "landing_domain")["traces"][0]["df"], 2)
        code, out, _ = self.cli("trace", PIXEL)
        self.assertEqual(code, 0)
        self.assertIn("występuje w 3 z 7", out)

    def test_matrix(self):
        d = self.json("matrix")
        self.assertEqual(set(d), {"materials", "p", "distance", "relation", "thresholds"})
        self.assertEqual((len(d["materials"]), len(d["p"]), len(d["p"][0])), (7, 7, 7))
        sub = self.json("matrix", "--campaign", "C1")
        self.assertEqual((len(sub["materials"]), len(sub["relation"])), (3, 3))
        code, out, _ = self.cli("matrix")
        self.assertEqual(code, 0)
        self.assertIn("alpha-1", out)
        self.assertIn("progi:", out)

    def test_metrics(self):
        d = self.json("metrics")
        self.assertLessEqual({"n_materials", "n_campaigns", "n_pairs", "n_must_link", "thresholds", "methods", "labels",
                              "distance_histogram", "signal_attribution", "view_summary", "feature_coverage", "merge_heights",
                              "projections", "dendrogram"}, set(d))
        self.assertEqual((d["n_materials"], d["n_pairs"], d["n_must_link"]), (7, 21, 3))
        own = next(m for m in d["methods"] if m["key"] == "fakeralpha")
        self.assertLessEqual({"key", "label", "n_clusters", "n_singletons", "silhouette", "ari_fakeralpha", "ari_labels", "clusters"}, set(own))
        self.assertEqual(set(own["clusters"]), {"aaaa11110001", "aaaa11110002", "aaaa22220003", "bbbb33330004", "cccc44440005", "dddd55550006",
                                               "eeee66660007"})
        code, out, _ = self.cli("metrics", "--methods")
        self.assertEqual(code, 0)
        for needle in ("SILHOUETTE", "Rozkład odległości", "FakerAlpha"):
            self.assertIn(needle, out)

    def test_eval_keeps_the_old_json_keys(self):
        labels = self.dir / "labels.csv"
        labels.write_text("# comment\nalpha-1,a\nalpha-2,a\naaaa22220003,a\nbeta-1,b\ngamma-1,c\ndelta-1,d\nepsilon-1,e\nnot-in-store,z\n", encoding="utf-8")
        d = self.json("eval", labels)
        self.assertEqual(set(d) - {"ARI_hdbscan_baseline"}, {"n", "pairwise_precision", "pairwise_recall", "pairwise_f1",
                                                              "bcubed_precision", "bcubed_recall", "ARI"})
        self.assertEqual((d["n"], d["pairwise_f1"], d["ARI"]), (7, 1.0, 1.0))
        code, out, _ = self.cli("eval", labels)
        self.assertEqual(code, 0)
        self.assertIn("pairwise_f1", out)

    def test_glossary_needs_no_store(self):
        code, out, err = run("--store", self.dir / "missing.sqlite", "glossary", "--json")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(set(d), {"identifier_groups", "descriptive_types", "views", "relations", "decisions", "constants",
                                  "measures", "steps"})
        types = {t["type"] for g in d["identifier_groups"] for t in g["types"]}
        self.assertLessEqual({"fb_pixel", "landing_domain", "phone", "product"}, types)
        self.assertEqual([r["relation"] for r in d["relations"]], ["duplicate", "same_campaign", "similar", "none"])
        self.assertEqual(d["constants"]["campaign_cut"], config.CAMPAIGN_CUT)
        self.assertEqual(run("glossary")[0], 0)

    def test_json_has_no_ui_only_fields(self):
        for argv in (["campaigns"], ["campaign", "C1"], ["materials"], ["material", "alpha-1"], ["pair", "alpha-1", "alpha-2"]):
            code, out, _ = self.cli(*argv, "--json")
            self.assertEqual(code, 0)
            for needle in ('"thumb', '"color"', "/api/file"):
                self.assertNotIn(needle, out, argv)

    def test_export(self):
        out_dir = self.dir / "exp"
        d = self.json("export", "--out", out_dir)
        self.assertEqual([f["kind"] for f in d["files"]], cli.EXPORT_KINDS)
        for f in d["files"]:
            self.assertTrue(Path(f["path"]).is_file() and f["bytes"] > 0, f)
        with open(out_dir / "links.csv", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["a", "b", "p", "distance", "relation", "views", "explanation"])
        self.assertEqual(len(rows), 1 + 3)
        camps = json.loads((out_dir / "campaigns.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(camps[0]["members"]), ["alpha-1", "alpha-2", "alpha-3"])
        only = self.dir / "only"
        code, out, _ = self.cli("export", "--out", only, "--only", "links.csv")
        self.assertEqual((code, out.strip()), (0, str(only / "links.csv")))
        self.assertEqual([p.name for p in only.iterdir()], ["links.csv"])

    def test_read_commands_never_modify_the_store(self):
        before = sha(self.store)
        for argv in (["status"], ["campaigns"], ["campaign", "C1"], ["materials"], ["material", "alpha-1"], ["search", "alpha"],
                     ["links"], ["pair", "alpha-1", "alpha-2"], ["trace", PIXEL], ["matrix"], ["metrics"],
                     ["export", "--out", self.dir / "ro-exp"]):
            self.assertEqual(self.cli(*argv)[0], 0, argv)
        self.assertEqual(sha(self.store), before)
        self.assertEqual(self.json("status")["n_materials"], 7)

    def test_engine_binding_is_restored_after_a_command(self):
        from ftf import api

        saved_engine, saved_path = api._ENGINE, config.STORE_PATH
        self.assertEqual(self.cli("campaigns")[0], 0)
        self.assertIs(api._ENGINE, saved_engine)
        self.assertEqual(config.STORE_PATH, saved_path)


class TestOutputFormatting(StoreCase):
    def test_no_colour_unless_asked(self):
        _, plain, _ = self.cli("campaigns")
        self.assertNotIn("\x1b[", plain)
        _, coloured, _ = self.cli("--color", "always", "campaigns")
        self.assertIn("\x1b[", coloured)
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(cli_format.want_colour("auto", sys.stdout))
        self.assertTrue(cli_format.want_colour("always"))
        self.assertFalse(cli_format.want_colour("auto", io.StringIO()))

    def test_tables_fit_the_width_and_wide_lifts_the_limit(self):
        with mock.patch.dict(os.environ, {"COLUMNS": "80"}):
            _, narrow, _ = self.cli("links", "--min", "0")
        self.assertTrue(all(cli_format.wlen(line) <= 80 for line in narrow.splitlines()), narrow)
        self.assertIn("…", narrow)
        _, wide, _ = self.cli("links", "--min", "0", "--wide")
        self.assertGreater(max(map(len, wide.splitlines())), 80)

    def test_hints_and_progress_stay_out_of_piped_stdout(self):
        code, out, _ = self.cli("campaigns")
        self.assertEqual(code, 0)
        self.assertNotIn("Dalej:", out)

    def test_table_helper(self):
        t = cli_format.table(["A", "LONG"], [["x", "abcdefghijklmnopqrstuvwxyz"], [1, None]], limits={1: 10}, align="rl")
        lines = t.splitlines()
        self.assertEqual(lines[1], "x  abcdefghi…")
        self.assertEqual(lines[2], "1  —")
        self.assertEqual(cli_format.trunc("zażółć gęślą", 7), "zażółć…")
        self.assertEqual(cli_format.join_more(["a", "b", "c", "d"], 2), "a, b (+2)")


# =============================================================================== errors and exit codes
class TestErrors(StoreCase):
    def test_missing_store_is_exit_3_and_is_not_created(self):
        missing = self.dir / "no-such-dir" / "none.sqlite"
        for argv in (["status"], ["campaigns"], ["materials"], ["links"], ["export"], ["add", "tekst reklamy", "--dry", "--no-llm"]):
            code, out, err = run("--store", missing, *argv)
            self.assertEqual(code, cli.EXIT_STORE, argv)
            self.assertIn("nie znaleziono bazy", err)
            for needle in ("--store", "FTF_STORE", "ingest"):
                self.assertIn(needle, err)
            self.assertNotIn("Traceback", err)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())
        code, out, _ = run("--store", missing, "status", "--json")
        self.assertEqual(code, cli.EXIT_STORE)
        self.assertEqual(json.loads(out)["store_exists"], False)

    def test_store_from_environment(self):
        with mock.patch.dict(os.environ, {"FTF_STORE": str(self.store)}):
            code, out, _ = run("status", "--json")
            self.assertEqual((code, json.loads(out)["n_materials"]), (0, 7))
        with mock.patch.dict(os.environ, {"FTF_STORE": str(self.dir / "absent.sqlite")}):
            self.assertEqual(run("campaigns")[0], cli.EXIT_STORE)
            code, out, _ = run("--store", self.store, "status", "--json")     # the option wins over the variable
            self.assertEqual((code, json.loads(out)["n_materials"]), (0, 7))

    def test_empty_and_unreadable_store_are_exit_3(self):
        empty = self.dir / "empty.sqlite"
        Store(empty).db.close()
        code, _, err = run("--store", empty, "campaigns")
        self.assertEqual(code, cli.EXIT_STORE)
        self.assertIn("pusta", err)
        self.assertIn("ingest", err)
        code, out, _ = run("--store", empty, "status", "--json")
        self.assertEqual((code, json.loads(out)["n_materials"]), (cli.EXIT_STORE, 0))
        garbage = self.dir / "garbage.sqlite"
        garbage.write_text("this is not an SQLite file, only some text to make it long enough " * 4, encoding="utf-8")
        code, _, err = run("--store", garbage, "campaigns")
        self.assertEqual(code, cli.EXIT_STORE)
        self.assertIn("nie można odczytać bazy", err)
        self.assertNotIn("Traceback", err)

    def test_unknown_references_are_exit_4(self):
        for argv, needle in ((["material", "zzz-nope"], "nie ma materiału"),
                             (["material", "alpha"], "pasuje do 3 materiałów"),
                             (["pair", "alpha-1", "zzz-nope"], "nie ma materiału"),
                             (["campaign", "C9"], "nie ma kampanii C9"),
                             (["campaign", "xyz"], "nie jest kodem kampanii"),
                             (["campaign", "--of", "zzz-nope"], "nie ma materiału"),
                             (["materials", "--campaign", "C42"], "nie ma kampanii"),
                             (["links", "--material", "zzz-nope"], "nie ma materiału"),
                             (["trace", "no-such-value.example"], "żaden materiał nie ma śladu")):
            code, out, err = self.cli(*argv)
            self.assertEqual(code, cli.EXIT_NOT_FOUND, argv)
            self.assertIn(needle, err)
            self.assertEqual(out, "")
            self.assertNotIn("Traceback", err)

    def test_not_found_suggests_what_to_do(self):
        _, _, err = self.cli("trace", "alpha-shop")
        self.assertIn("alpha-shop.example", err)
        self.assertIn("search", err)
        _, _, err = self.cli("material", "alpha-11")
        self.assertIn("podobne: alpha-1", err)

    def test_usage_problems_inside_commands_are_exit_2(self):
        self.assertEqual(self.cli("campaign")[0], cli.EXIT_USAGE)
        self.assertEqual(self.cli("campaign", "C1", "--of", "alpha-1")[0], cli.EXIT_USAGE)
        self.assertEqual(self.cli("search", "x")[0], cli.EXIT_USAGE)
        self.assertEqual(self.cli("pair", "alpha-1", "alpha-1")[0], cli.EXIT_USAGE)
        self.assertEqual(self.cli("trace", "x", "--type", "nonsense")[0], cli.EXIT_USAGE)

    def test_bad_input_is_exit_5(self):
        code, _, err = self.cli("eval", self.dir / "no-labels.csv")
        self.assertEqual(code, cli.EXIT_INPUT)
        self.assertIn("nie znaleziono pliku etykiet", err)
        unmatched = self.dir / "unmatched.csv"
        unmatched.write_text("x,1\ny,2\n", encoding="utf-8")
        code, _, err = self.cli("eval", unmatched)
        self.assertEqual(code, cli.EXIT_INPUT)
        self.assertIn("nie pasuje", err)
        code, _, err = self.cli("add", self.dir / "no-such-file.png", "--dry", "--no-llm")
        self.assertEqual(code, cli.EXIT_INPUT)
        self.assertIn("--text", err)
        self.assertEqual(self.cli("add", "http://", "--dry", "--no-llm")[0], cli.EXIT_INPUT)
        self.assertEqual(self.cli("add", "   ", "--dry", "--no-llm")[0], cli.EXIT_INPUT)
        code, _, err = run("--store", self.dir / "x.sqlite", "ingest", self.dir / "no-such-folder", "--no-llm")
        self.assertEqual(code, cli.EXIT_INPUT)
        self.assertFalse((self.dir / "x.sqlite").exists(), "a failed ingest must not leave an empty store behind")
        flat = self.dir / "flat"
        flat.mkdir()
        (flat / "a.txt").write_text("tekst", encoding="utf-8")
        self.assertEqual(run("--store", self.dir / "x.sqlite", "ingest", flat, "--no-llm")[0], cli.EXIT_INPUT)

    def test_evaluate_function_reports_unmatched_labels(self):
        from ftf.engine import Engine

        unmatched = self.dir / "unmatched2.csv"
        unmatched.write_text("x,1\n", encoding="utf-8")
        st = Store(self.store, readonly=True)
        try:
            with self.assertRaises(ValueError):
                cli.evaluate(Engine(st), str(unmatched))
        finally:
            st.db.close()

    def test_serve_on_a_taken_port_is_exit_6(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            with mock.patch("uvicorn.run") as started:
                code, _, err = self.cli("serve", "--port", str(s.getsockname()[1]))
            started.assert_not_called()
        self.assertEqual(code, cli.EXIT_ENV)
        self.assertIn("--port", err)

    def test_serve_starts_uvicorn_with_the_old_arguments(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with mock.patch.dict(os.environ, {"FTF_STORE": str(self.store)}), mock.patch("uvicorn.run") as started:
            code, out, _ = run("serve", "--port", str(port))
        self.assertEqual(code, 0)
        started.assert_called_once_with("ftf.api:app", host="127.0.0.1", port=port, log_level="warning")
        self.assertIn(f"http://127.0.0.1:{port}", out)

    def test_unexpected_error_is_exit_1_without_traceback(self):
        with mock.patch("ftf.api.overview", side_effect=RuntimeError("boom")):
            code, _, err = self.cli("campaigns")
            self.assertEqual(code, cli.EXIT_ERROR)
            self.assertIn("boom", err)
            self.assertNotIn("Traceback", err)
            code, _, err = self.cli("-v", "campaigns")
            self.assertEqual(code, cli.EXIT_ERROR)
            self.assertIn("Traceback", err)

    def test_readonly_store_rejects_writes(self):
        import sqlite3

        st = Store(self.store, readonly=True)
        try:
            self.assertEqual(st.count(), 7)
            with self.assertRaises(sqlite3.OperationalError):
                st.log("test", {})
        finally:
            st.db.close()


# =============================================================================== add (pipeline mocked)
def _fake_analyze(indicators: dict):
    def analyze(m, use_llm=True, progress=None):
        return _feat(m.name, indicators), {}
    return analyze


class TestAdd(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.store = self.dir / "add.sqlite"
        make_store(self.store)
        self.data = self.dir / "data"
        patches = [mock.patch.dict(os.environ, {"FTF_ENRICH": "0"}), mock.patch.object(config, "DATA", self.data)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.td.cleanup)

    def count(self) -> int:
        st = Store(self.store, readonly=True)
        try:
            return st.count()
        finally:
            st.db.close()

    def add(self, *argv, indicators=None):
        with mock.patch("ftf.engine.analyze", side_effect=_fake_analyze(indicators or {})) as an:
            code, out, err = run("--store", self.store, "add", *argv)
        return code, out, err, an

    def test_dry_run_decides_without_saving(self):
        before = sha(self.store)
        code, out, err, an = self.add("Alphavit, tylko dziś -50%", "--dry", "--no-llm", "--json", indicators={"fb_pixel": [PIXEL]})
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertLessEqual({"decision", "decision_label", "decision_hint", "campaign", "nearest", "scores", "links", "kept",
                              "material_id", "name", "input", "features", "thresholds"}, set(d))
        self.assertEqual((d["decision"], d["kept"], d["campaign"]["code"]), ("known_campaign", False, "C1"))
        self.assertEqual(d["input"], {"mode": "text", "source": "Alphavit, tylko dziś -50%", "use_llm": False, "keep": False,
                                      "render": False})
        self.assertFalse(an.call_args.kwargs["use_llm"])
        self.assertEqual(sha(self.store), before)
        self.assertEqual(self.count(), 7)

    def test_saving_adds_one_material(self):
        code, out, err, an = self.add("Zupełnie nowa reklama", "--json")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["decision"], d["kept"], d["campaign"]), ("new_campaign", True, None))
        self.assertTrue(an.call_args.kwargs["use_llm"])
        self.assertEqual(self.count(), 8)
        code, out, _ = run("--store", self.store, "material", d["material_id"], "--json")
        self.assertEqual((code, json.loads(out)["source"]), (0, "text"))

    def test_human_output_shows_decision_and_evidence(self):
        code, out, err, _ = self.add("Alphavit, tylko dziś -50%", "--dry", "--no-llm", indicators={"fb_pixel": [PIXEL]})
        self.assertEqual(code, 0, err)
        for needle in ("Decyzja: Znana kampania → C1", "[known_campaign]", "nie zapisano", "Dowody", "alpha-1",
                       "Identyfikatory nowego materiału", "3/7", "łączy z 3 mat."):
            self.assertIn(needle, out)
        self.assertIn("Analiza (tekst)", err)
        code, out, err, _ = self.add("Alphavit", "--dry", "--no-llm", "-q", indicators={"fb_pixel": [PIXEL]})
        self.assertEqual((code, err), (0, ""))

    def test_merge_proposal_and_new_value(self):
        ind = {"fb_pixel": [PIXEL], "telegram": ["beta_synthetic"], "landing_domain": ["brand-new.example"]}
        code, out, err, _ = self.add("łącznik", "--dry", "--json", indicators=ind)
        self.assertEqual((code, json.loads(out)["decision"]), (0, "merge_proposal"))
        code, out, err, _ = self.add("łącznik", "--dry", indicators=ind)
        self.assertIn("nowa wartość", out)

    def test_file_input_dry_run_leaves_no_copy_behind(self):
        code, out, err, _ = self.add(SYNTHETIC_NEW_AD, "--dry", "--no-llm", "--json", indicators={"fb_pixel": [PIXEL]})
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["input"]["mode"], d["name"], d["kept"]), ("file", SYNTHETIC_NEW_AD.name, False))
        uploads = self.data / "uploads"
        self.assertEqual(list(uploads.iterdir()) if uploads.exists() else [], [])
        code, out, err, _ = self.add(SYNTHETIC_NEW_AD, "--no-llm", "--json")
        self.assertEqual((code, json.loads(out)["kept"]), (0, True))
        self.assertEqual(len(list(uploads.iterdir())), 1, "a saved material keeps its working copy")

    def test_folder_input(self):
        code, out, err, _ = self.add(SYNTHETIC_DATASET / "syn-06-loteria", "--dry", "--no-llm", "--json")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["input"]["mode"], d["name"]), ("folder", "syn-06-loteria"))
        empty = self.dir / "empty-folder"
        empty.mkdir()
        self.assertEqual(self.add(empty, "--dry")[0], cli.EXIT_INPUT)

    def test_text_flag_forces_text(self):
        code, out, err, _ = self.add("promo.html", "--text", "--dry", "--json")
        self.assertEqual((code, json.loads(out)["input"]["mode"]), (0, "text"))
        self.assertEqual(self.add("promo.html", "--dry")[0], cli.EXIT_INPUT)

    def test_url_is_captured_through_the_capture_layer_only(self):
        """The network layer is mocked: no request leaves the machine."""
        page = self.dir / "captured.html"
        page.write_text("<html><title>Synthetic</title><body>synthetic capture</body></html>", encoding="utf-8")
        cap = {"dir": str(self.dir), "html": str(page), "final_url": "https://synthetic-landing.example/", "cloaking": False,
               "notes": []}
        with mock.patch("ftf.capture.capture_url", return_value=cap) as cu:
            code, out, err, an = self.add("https://synthetic-landing.example/promo", "--dry", "--no-llm", "--no-render", "--json")
        self.assertEqual(code, 0, err)
        cu.assert_called_once_with("https://synthetic-landing.example/promo", render=False)
        d = json.loads(out)
        self.assertEqual((d["input"]["mode"], d["input"]["render"], d["kept"]), ("url", False, False))
        material = an.call_args.args[0]
        self.assertEqual((material.source, material.pages[0]["path"]), ("url", str(page)))

    def test_rejected_url_is_exit_5(self):
        with mock.patch("ftf.capture.capture_url", return_value={"dir": None, "error": "Non-public IP address blocked"}):
            code, out, err, an = self.add("http://127.0.0.1:9/", "--dry", "--no-llm")
        self.assertEqual((code, out), (cli.EXIT_INPUT, ""))
        self.assertIn("odrzucony", err)
        an.assert_not_called()

    def test_add_creates_a_missing_store_only_when_saving(self):
        fresh = self.dir / "sub" / "fresh.sqlite"
        with mock.patch("ftf.engine.analyze", side_effect=_fake_analyze({})):
            self.assertEqual(run("--store", fresh, "add", "pierwszy materiał", "--dry")[0], cli.EXIT_STORE)
            self.assertFalse(fresh.exists())
            code, out, err = run("--store", fresh, "add", "pierwszy materiał", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["decision"], "new_campaign")
        self.assertIn("Tworzę nową bazę", err)
        self.assertTrue(fresh.exists())


# =============================================================================== real pipeline on synthetic fixtures
class TestSyntheticEndToEnd(unittest.TestCase):
    """ingest -> campaigns -> add on the synthetic cases, with the real feature extraction (no LLM, no network)."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.td.name)
        cls.store = cls.dir / "synthetic.sqlite"
        cls._patches = [mock.patch.dict(os.environ, {"FTF_ENRICH": "0"}), mock.patch.object(config, "DATA", cls.dir / "data")]
        for p in cls._patches:
            p.start()
        cls.ingest = run("--store", cls.store, "ingest", SYNTHETIC_DATASET, "--no-llm")

    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls._patches):
            p.stop()
        cls.td.cleanup()

    def json(self, *argv):
        code, out, err = run("--store", self.store, *argv, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_ingest_reports_and_groups(self):
        code, out, err = self.ingest
        self.assertEqual(code, 0, err)
        self.assertIn("Przetworzono 8 przypadków", out)
        self.assertIn("8 nowych", out)
        self.assertIn("[1/8]", err)
        d = self.json("campaigns")
        self.assertEqual(d["n_materials"], 8)
        c1 = d["campaigns"][0]
        self.assertEqual({m["name"] for m in c1["members"]},
                         {"syn-01-kardivix", "syn-02-kardivix-bis", "syn-03-kardivix-news"})
        self.assertEqual([sorted(m["name"] for m in g) for g in d["duplicates"]],
                         [["syn-01-kardivix", "syn-02-kardivix-bis"]])

    def test_ingest_again_skips_known_cases(self):
        code, out, err = run("--store", self.store, "-q", "ingest", SYNTHETIC_DATASET, "--no-llm")
        self.assertEqual(code, 0, err)
        self.assertIn("0 nowych", out)
        self.assertEqual(err, "")
        self.assertEqual(self.json("materials")["n_total"], 8)

    def test_dataset_folder_layouts(self):
        from ftf import ingest
        text = "Kardivix kapsułki na serce, rabat 50 procent tylko dziś."
        one = self.dir / "one"
        (one / "case-01" / "strona_files").mkdir(parents=True)
        (one / "case-01" / "reklama.txt").write_text(text, encoding="utf-8")
        self.assertEqual([m.name for m in ingest.load_dataset(one)], ["case-01"])
        wrapped = self.dir / "wrapped"
        for name in ("a", "b"):
            (wrapped / "inner" / name).mkdir(parents=True)
            (wrapped / "inner" / name / "reklama.txt").write_text(text, encoding="utf-8")
        self.assertEqual([m.name for m in ingest.load_dataset(wrapped)], ["a", "b"])

    def test_demo_is_the_synthetic_dataset_and_skips_known_cases(self):
        self.assertEqual(config.DEMO_DATASET.resolve(), SYNTHETIC_DATASET.resolve())
        code, out, err = run("--store", self.store, "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("Przetworzono 8 przypadków", out)
        self.assertIn("0 nowych", out)
        self.assertIn("Zbiór demonstracyjny", err)

    def test_demo_never_uses_the_llm_or_online_lookups(self):
        calls = []

        def fake_analyze(m, use_llm=True, progress=None, enrich_online=None):
            calls.append((use_llm, enrich_online))
            return _feat(m.name, {"landing_domain": [f"{m.name}.example"]}), {}

        with mock.patch.dict(os.environ, {"FTF_ENRICH": "1", "FTF_LLM": "auto"}), \
                mock.patch("ftf.engine.analyze", fake_analyze):
            code, out, err = run("--store", self.dir / "demo.sqlite", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("8 nowych", out)
        self.assertEqual(set(calls), {(False, False)})
        self.assertEqual(len(calls), 8)

    def test_trace_and_pair_explain_the_link(self):
        t = self.json("trace", PIXEL)["traces"][0]
        self.assertEqual((t["type"], t["df"], t["counted"]), ("fb_pixel", 3, True))
        p = self.json("pair", "syn-01-kardivix", "syn-03-kardivix-news")
        self.assertEqual((p["relation"], p["must_link"]), ("same_campaign", True))
        self.assertEqual(self.json("pair", "syn-01-kardivix", "syn-02-kardivix-bis")["relation"], "duplicate")

    def test_eval_against_synthetic_labels(self):
        d = self.json("eval", SYNTHETIC_LABELS)
        self.assertEqual(d["n"], 8)
        self.assertEqual(d["pairwise_precision"], 1.0)

    def test_new_synthetic_ad_joins_the_known_campaign(self):
        before = sha(self.store)
        d = self.json("add", SYNTHETIC_NEW_AD, "--dry", "--no-llm")
        self.assertEqual((d["decision"], d["kept"]), ("known_campaign", False))
        self.assertIn("syn-0", d["nearest"]["material_name"])
        self.assertTrue(any(l["relation"] == "same_campaign" for l in d["links"]))
        self.assertEqual(sha(self.store), before)
        text = self.json("add", "Wygraj nagrodę w loterii, opłać tylko przesyłkę", "--dry", "--no-llm")
        self.assertIn(text["decision"], {"new_campaign", "known_campaign", "duplicate"})
        self.assertFalse(text["kept"])


# =============================================================================== as a process
class TestAsProcess(unittest.TestCase):
    def _proc(self, *argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
        e = {**os.environ, "FTF_ENRICH": "0", "FTF_LLM": "none", "NO_COLOR": "1", **(env or {})}
        return subprocess.run([sys.executable, *argv], cwd=ROOT, env=e, capture_output=True, text=True, timeout=300)

    def test_python_m_ftf_and_python_m_ftf_cli(self):
        for module in ("ftf", "ftf.cli"):
            r = self._proc("-m", module, "--version")
            self.assertEqual((r.returncode, r.stdout.strip()[:10]), (0, "FakerAlpha"), r.stderr)
        r = self._proc("-m", "ftf", "glossary", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("relations", json.loads(r.stdout))

    def test_exit_codes_reach_the_shell(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "proc.sqlite"
            make_store(store)
            r = self._proc("-m", "ftf", "status", "--json", env={"FTF_STORE": str(store)})
            self.assertEqual((r.returncode, json.loads(r.stdout)["n_materials"]), (0, 7), r.stderr)
            r = self._proc("-m", "ftf.cli", "campaigns", env={"FTF_STORE": str(store)})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("C1", r.stdout)
            self.assertNotIn("\x1b[", r.stdout)
            r = self._proc("-m", "ftf", "material", "zzz-nope", env={"FTF_STORE": str(store)})
            self.assertEqual((r.returncode, r.stdout), (4, ""))
            self.assertIn("błąd:", r.stderr)
            r = self._proc("-m", "ftf", "--store", str(Path(td) / "absent.sqlite"), "campaigns")
            self.assertEqual(r.returncode, 3)
            self.assertFalse((Path(td) / "absent.sqlite").exists())
            self.assertEqual(self._proc("-m", "ftf", "no-such-command").returncode, 2)


if __name__ == "__main__":
    unittest.main()
