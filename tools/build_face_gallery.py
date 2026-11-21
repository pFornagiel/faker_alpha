"""Build the small face reference DB of the persons most often impersonated in Polish scam ads.

Images: Wikipedia page image + up to N extra Wikimedia Commons photos per person (free licences;
attribution metadata saved to data/reference_faces/<Person>/sources.json).
Consistency: the Wikipedia portrait is the anchor; extra photos are kept only if they contain a face
with ArcFace cosine >= 0.35 to the anchor (group photos therefore contribute the right face).

    .venv/bin/python tools/build_face_gallery.py [--extra 3] ["Name 1" "Name 2" ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftf import config, faces  # noqa: E402

UA = {"User-Agent": "FakeTrace-hackathon-POC/0.1 (research prototype; reference face gallery)"}
PERSONS = [
    "Rafał Brzoska", "Andrzej Duda", "Karol Nawrocki", "Donald Tusk", "Adam Glapiński", "Robert Lewandowski",
    "Rafał Trzaskowski", "Sławomir Mentzen", "Sebastian Kulczyk", "Wojciech Cejrowski", "Bogdan Rymanowski",
    "Monika Olejnik", "Krzysztof Stanowski", "Tomasz Sekielski", "Mateusz Morawiecki", "Szymon Hołownia",
    "Kuba Wojewódzki", "Omena Mensah", "Daniel Obajtek", "Izabela Leszczyna", "Krzysztof Ibisz", "Marcin Prokop",
    "Dorota Wellman", "Piotr Kraśko", "Anna Lewandowska", "Cristiano Ronaldo", "Elon Musk", "Grzegorz Braun",
    "Krzysztof Bosak", "Jerzy Zięba", "Paweł Grzesiowski", "Ewa Drzyzga",
]


def wiki_pageimage(name: str) -> tuple[str | None, dict]:
    for lang in ("pl", "en"):
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=20, params={
            "action": "query", "titles": name, "prop": "pageimages", "piprop": "thumbnail|name",
            "pithumbsize": 640, "redirects": 1, "format": "json"})
        try:
            pages = r.json().get("query", {}).get("pages", {}).values()
        except ValueError:
            continue
        for p in pages:
            if "thumbnail" in p:
                return p["thumbnail"]["source"], {"page": f"https://{lang}.wikipedia.org/wiki/{name.replace(' ', '_')}",
                                                  "file": p.get("pageimage")}
    return None, {}


def commons_search(name: str, n: int) -> list[tuple[str, dict]]:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=20, params={
        "action": "query", "generator": "search", "gsrsearch": f'"{name}" filetype:bitmap', "gsrnamespace": 6,
        "gsrlimit": n * 3, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 640, "format": "json"})
    out = []
    for p in sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("thumburl"):
            md = ii.get("extmetadata", {})
            out.append((ii["thumburl"], {"file": p.get("title"), "licence": md.get("LicenseShortName", {}).get("value"),
                                         "author": (md.get("Artist", {}).get("value") or "")[:200]}))
    return out


def fetch_img(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        from io import BytesIO

        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def build(person: str, extra: int) -> int:
    out = config.REFERENCE_FACES / person
    if out.exists() and len(list(out.glob("*.jpg"))) >= 2:
        return len(list(out.glob("*.jpg")))
    out.mkdir(parents=True, exist_ok=True)
    sources = []
    url, info = wiki_pageimage(person)
    anchor = None
    if url:
        im = fetch_img(url)
        if im is not None:
            fs = faces.faces_in_image(im, min_side=24)
            if fs:
                best = max(fs, key=lambda f: f["side"])
                anchor = best["embedding"]
                im.save(out / "wiki_0.jpg", quality=90)
                sources.append({"img": "wiki_0.jpg", "url": url, **info})
    kept = 0
    for i, (u, meta) in enumerate(commons_search(person, extra)):
        if kept >= extra:
            break
        im = fetch_img(u)
        if im is None:
            continue
        fs = faces.faces_in_image(im, min_side=40)
        if not fs:
            continue
        if anchor is None:
            if len(fs) != 1:
                continue
            anchor = fs[0]["embedding"]
            sim = 1.0
        else:
            sims = [float(f["embedding"] @ anchor) for f in fs]
            j = int(np.argmax(sims))
            sim = sims[j]
            if sim < 0.35:
                continue
            if len(fs) > 1:   # crop the matching face (with margin) so the gallery mean is not polluted
                x0, y0, x1, y1 = fs[j]["box"]
                w, h = x1 - x0, y1 - y0
                im = im.crop((max(0, x0 - w), max(0, y0 - h), min(im.width, x1 + w), min(im.height, y1 + h)))
        im.save(out / f"commons_{kept + 1}.jpg", quality=90)
        sources.append({"img": f"commons_{kept + 1}.jpg", "url": u, "sim_to_anchor": round(sim, 3), **meta})
        kept += 1
        time.sleep(0.3)
    (out / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=1))
    return len(sources)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--extra", type=int, default=3)
    a = ap.parse_args()
    for p in a.names or PERSONS:
        try:
            n = build(p, a.extra)
            print(f"{p:28s} {n} images", flush=True)
        except Exception as exc:
            print(f"{p:28s} FAILED {exc}", flush=True)
        time.sleep(0.5)
    faces.gallery.cache_clear()
    names, vecs, meta = faces.gallery()
    print("gallery:", len(names), "persons")
