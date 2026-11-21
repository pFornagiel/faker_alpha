"""Ingestion: turn heterogeneous inputs into `Material` objects.

A Material = one incident (one case folder of the organiser set, one uploaded file, one URL capture,
one ad-library hit or a free-text hint). It groups *artifacts*: landing pages (saved HTML, HAR,
MHTML, page-capture/archiver folders), screenshots / creatives, videos, metadata JSON and free text.
The loader is deliberately tolerant: anything missing (deleted video, dead page) is just absent.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VID_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
HTML_EXT = {".html", ".htm"}
ASSET_DIR_RX = re.compile(r"(_files|_pliki|/resources/|/assets?/|/static/|/images?/|/img/)", re.I)


@dataclass
class Material:
    id: str
    name: str
    source: str                      # organizer | upload | url | text | scheduler:<lib>
    source_ref: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    pages: list[dict] = field(default_factory=list)     # {kind: html|har|mhtml, path, url?}
    images: list[str] = field(default_factory=list)     # screenshots / ad creatives
    assets: list[str] = field(default_factory=list)     # images embedded in saved landing pages
    videos: list[str] = field(default_factory=list)
    meta: list[str] = field(default_factory=list)       # json metadata files
    texts: list[str] = field(default_factory=list)      # free text (ad copy, product name, OCR'd input...)
    urls: list[str] = field(default_factory=list)       # input URLs
    notes: list[str] = field(default_factory=list)
    label: str | None = None                            # optional ground-truth campaign label

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Material":
        return Material(**{k: v for k, v in d.items() if k in Material.__dataclass_fields__})


def _mid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", "replace")).hexdigest()[:12]


def load_folder(folder: str | Path, source: str = "organizer", name: str | None = None) -> Material:
    folder = Path(folder)
    m = Material(id=_mid(source, str(folder.resolve())), name=name or folder.name, source=source, source_ref=str(folder))
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    html_dirs = set()
    for p in files:
        rel = "/" + str(p.relative_to(folder)).replace("\\", "/")
        ext = p.suffix.lower()
        in_assets = bool(ASSET_DIR_RX.search(rel))
        low = p.name.lower()
        if ext == ".har":
            m.pages.append({"kind": "har", "path": str(p)})
        elif ext in HTML_EXT and not in_assets:
            if "/html/source.html" in rel and (p.parent / "rendered.html").exists():
                continue          # archiver: prefer the rendered DOM
            m.pages.append({"kind": "html", "path": str(p)})
            html_dirs.add(p.parent)
        elif ext == ".mhtml":
            m.pages.append({"kind": "mhtml", "path": str(p)})
        elif ext in IMG_EXT:
            if in_assets or "/screenshots/viewport" in rel:
                m.assets.append(str(p))
            else:
                m.images.append(str(p))
        elif ext in VID_EXT:
            m.videos.append(str(p))
        elif ext == ".json" and any(k in low for k in ("info.json", "manifest", "archive_info", "metadata", "dns_ssl")):
            m.meta.append(str(p))
        elif ext == ".txt":
            if "deleted" in low or "removed" in low or "usuni" in low:
                m.notes.append(f"missing material: {p.name}")
            elif p.stat().st_size < 200_000:
                txt = p.read_text(encoding="utf-8", errors="replace")
                if "page_text" in low or len(txt) > 20:
                    m.texts.append(txt[:20000])
        elif ext == ".pobrane" or ext == "" and in_assets:
            m.assets.append(str(p))       # Chrome 'Save as' assets without extension (Polish locale)
    # an MHTML next to a saved HTML of the same page is redundant
    if any(pg["kind"] == "html" for pg in m.pages):
        m.pages = [pg for pg in m.pages if not (pg["kind"] == "mhtml" and Path(pg["path"]).parent in html_dirs)]
    return m


def load_dataset(root: str | Path, source: str = "organizer") -> list[Material]:
    """Each immediate sub-folder of `root` is one incident (organiser layout: do_udostępnienia/<id>/...)."""
    root = Path(root)
    subs = [p for p in sorted(root.iterdir(), key=lambda p: (len(p.name), p.name)) if p.is_dir()]
    if len(subs) == 1 and not any(f.is_file() for f in root.iterdir()):
        return load_dataset(subs[0], source)
    return [load_folder(s, source=source, name=s.name) for s in subs]


def from_upload(filename: str, data: bytes, label: str | None = None) -> Material:
    """A single uploaded file: screenshot / creative / video / html / har / mhtml / zip of a case."""
    h = hashlib.sha1(data).hexdigest()[:12]
    dst = config.DATA / "uploads" / h
    dst.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]", "_", Path(filename).name)[:120] or "upload.bin"
    fp = dst / safe
    fp.write_bytes(data)
    if fp.suffix.lower() == ".zip":
        ex = dst / "unzipped"
        with zipfile.ZipFile(fp) as zf:
            for info in zf.infolist():
                n = info.filename
                if not (info.flag_bits & 0x800):
                    try:
                        n = n.encode("cp437").decode("utf-8")
                    except UnicodeError:
                        pass
                target = (ex / n).resolve()
                if not str(target).startswith(str(ex.resolve())) or n.endswith("/"):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
        fp.unlink()
        m = load_folder(ex, source="upload", name=Path(filename).stem)
    else:
        m = load_folder(dst, source="upload", name=Path(filename).name)
    m.id = _mid("upload", h)
    m.label = label
    return m


def from_text(text: str, name: str | None = None) -> Material:
    """Free-text hint: pasted ad copy, a product name, or a list of URLs."""
    urls = re.findall(r"https?://\S+", text)
    m = Material(id=_mid("text", text), name=name or text[:60], source="text", source_ref=text[:200])
    m.texts.append(text)
    m.urls.extend(urls)
    return m


def from_url(url: str, capture: dict | None = None) -> Material:
    """A URL (ad landing page or ad-library link). `capture` = output of capture.capture_url()."""
    m = Material(id=_mid("url", url), name=url[:80], source="url", source_ref=url)
    m.urls.append(url)
    if capture:
        for kind in ("html", "har"):
            if capture.get(kind):
                m.pages.append({"kind": kind, "path": capture[kind], "url": capture.get("final_url", url)})
        if capture.get("screenshot"):
            m.images.append(capture["screenshot"])
        m.meta.extend(capture.get("meta", []))
        m.notes.extend(capture.get("notes", []))
        m.videos.extend(capture.get("videos", []))
    return m


def copy_into_store(m: Material) -> Material:
    """(optional) keep a private copy of transient artifacts (uploads, captures) next to the store."""
    return m


def read_meta(m: Material) -> dict:
    """Merge known metadata formats: yt-dlp .info.json (Meta Ad Library via facebook:ads extractor),
    page-capture manifest.json, archiver archive_info/metadata/dns_ssl.json."""
    out: dict = {"ad_library": [], "capture": [], "dns": []}
    for p in m.meta:
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        name = Path(p).name.lower()
        if name.endswith("info.json") and ("extractor" in d or "webpage_url" in d):
            out["ad_library"].append({
                "platform": d.get("extractor_key") or d.get("extractor"), "ad_id": d.get("playlist_id") or d.get("id"),
                "advertiser": d.get("playlist_uploader") or d.get("uploader"),
                "advertiser_id": d.get("playlist_uploader_id") or d.get("uploader_id"),
                "title": d.get("title"), "description": d.get("description"), "url": d.get("webpage_url"),
                "timestamp": d.get("epoch") or d.get("timestamp"), "duration": d.get("duration"),
                "thumbnail": d.get("thumbnail"),
            })
        elif "page_url" in d or "tool" in d:
            out["capture"].append({"url": d.get("page_url") or d.get("url"), "title": d.get("title"),
                                   "captured_at": d.get("captured_at"), "tool": d.get("tool"),
                                   "final_url": d.get("final_url"), "redirects": d.get("redirects") or d.get("redirect_chain")})
        elif "dns" in name or "ssl" in name:
            out["dns"].append(d)
        else:
            out["capture"].append({k: d.get(k) for k in ("url", "final_url", "title", "timestamp", "domain") if k in d})
    return out


def clean_upload_dir(m: Material) -> None:
    if m.source == "upload":
        shutil.rmtree(Path(m.source_ref), ignore_errors=True)
