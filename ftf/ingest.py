"""Ingestion: turn heterogeneous inputs into `Material` objects.

A Material = one incident (one case folder of the organiser set, one uploaded file, one URL capture,
one ad-library hit, or a free-text hint). It groups *artifacts*: landing pages (saved HTML, HAR,
MHTML, page-capture/archiver folders), screenshots / creatives, embedded page images, saved scripts,
videos, metadata JSON, and free text.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import stat
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
VID_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
HTML_EXT = {".html", ".htm"}
SCRIPT_EXT = {".js", ".mjs"}
ASSET_DIR_RX = re.compile(r"(_files|_pliki|/resources/|/assets?/|/static/|/images?/|/img/)", re.I)

# Zip extraction safety bounds
MAX_FILES = 500
MAX_FILE_BYTES = 50_000_000
MAX_TOTAL_BYTES = 250_000_000

_SAVED_FROM_URL_RX = re.compile(r"saved from url=\(\d+\)\S+", re.I)
_MHTML_SNAPSHOT_RX = re.compile(rb"^Snapshot-Content-Location:\s*(\S+)", re.I | re.M)
_URL_RX = re.compile(r"https?://\S+")
_URL_TRAILING_PUNCT = ".,;:!?)]}>\"'"


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
    scripts: list[str] = field(default_factory=list)    # saved first/third-party JS files
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
        known = {k: v for k, v in d.items() if k in Material.__dataclass_fields__}
        return Material(**known)


def _mid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", "replace")).hexdigest()[:12]


def _is_image_file(path: Path) -> bool:
    """Identify raster image files by magic bytes (prevents .js.pobrane / CSS from entering `assets`)."""
    try:
        with path.open("rb") as fh:
            hdr = fh.read(16)
    except OSError:
        return False
    if len(hdr) < 4:
        return False
    if hdr.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if hdr.startswith(b"\xff\xd8\xff"):
        return True
    if hdr.startswith((b"GIF87a", b"GIF89a")):
        return True
    if hdr.startswith(b"BM"):
        return True
    if len(hdr) >= 12 and hdr[:4] == b"RIFF" and hdr[8:12] == b"WEBP":
        return True
    if hdr.startswith(b"\x00\x00\x01\x00"):
        return True
    if len(hdr) >= 12 and hdr[4:8] == b"ftyp" and hdr[8:12] in (b"avif", b"avis", b"mif1", b"heic"):
        return True
    return False


def _html_has_saved_url(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(3000)
        return bool(_SAVED_FROM_URL_RX.search(head))
    except OSError:
        return False


def _extract_mhtml_url(path: Path) -> str:
    """Read only the MHTML header to recover `Snapshot-Content-Location` without loading multi-MB bodies."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8192)
        m = _MHTML_SNAPSHOT_RX.search(head)
        if m:
            url = m.group(1).decode("utf-8", errors="replace").strip()
            if url.startswith(("http://", "https://")):
                return url
    except OSError:
        pass
    return ""


def load_folder(folder: str | Path, source: str = "organizer", name: str | None = None) -> Material:
    """Walk an incident folder and classify pages, creatives, page images, scripts, videos, and metadata."""
    folder = Path(folder)
    m = Material(id=_mid(source, str(folder.resolve())), name=name or folder.name, source=source, source_ref=str(folder))
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    html_dirs_with_url: set[Path] = set()
    html_dirs_all: set[Path] = set()

    for p in files:
        rel = "/" + str(p.relative_to(folder)).replace("\\", "/")
        ext = p.suffix.lower()
        low = p.name.lower()
        in_assets = bool(ASSET_DIR_RX.search(rel))

        if ext == ".har" or low == ".har":
            m.pages.append({"kind": "har", "path": str(p)})
        elif ext in HTML_EXT and not in_assets:
            if "/html/source.html" in rel and (p.parent / "rendered.html").exists():
                continue          # archiver: prefer the rendered DOM
            m.pages.append({"kind": "html", "path": str(p)})
            html_dirs_all.add(p.parent)
            if _html_has_saved_url(p):
                html_dirs_with_url.add(p.parent)
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
        elif ext in SCRIPT_EXT or low.endswith((".js.pobrane", ".js.pobierz", ".mjs.pobrane", ".mjs.pobierz")):
            m.scripts.append(str(p))
        elif ext in (".pobrane", ".pobierz") or (ext == "" and in_assets):
            # Chrome 'Save as' assets (Polish locale) or extensionless downloads: sniff magic bytes!
            if _is_image_file(p):
                m.assets.append(str(p))
            elif ext in (".pobrane", ".pobierz") and not low.endswith((".css.pobrane", ".css.pobierz")):
                m.scripts.append(str(p))

    # Handle redundant MHTML next to sibling HTML without losing Snapshot-Content-Location URLs
    if html_dirs_all:
        kept_pages: list[dict] = []
        for pg in m.pages:
            if pg["kind"] == "mhtml":
                mhtml_path = Path(pg["path"])
                parent = mhtml_path.parent
                if parent in html_dirs_all:
                    snap_url = _extract_mhtml_url(mhtml_path)
                    if snap_url:
                        if snap_url not in m.urls:
                            m.urls.append(snap_url)
                        # Attach URL to sibling HTML pages that lacked one
                        for other in m.pages:
                            if other["kind"] == "html" and Path(other["path"]).parent == parent and not other.get("url"):
                                other["url"] = snap_url
                        continue          # safe to drop duplicate MHTML now that URL is preserved
                    if parent in html_dirs_with_url:
                        continue          # sibling HTML already carries saved-from-url
            kept_pages.append(pg)
        m.pages = kept_pages

    return m


def load_dataset(root: str | Path, source: str = "organizer") -> list[Material]:
    """Each immediate sub-folder of `root` is one incident (organiser layout: do_udostępnienia/<id>/...)."""
    root = Path(root)
    subs = [p for p in sorted(root.iterdir(), key=lambda p: (len(p.name), p.name)) if p.is_dir()]
    if len(subs) == 1 and not any(f.is_file() for f in root.iterdir()):
        return load_dataset(subs[0], source)
    return [load_folder(s, source=source, name=s.name) for s in subs]


def _extract_zip_safely(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip archive while blocking zip-slip, symlinks, and zip bombs."""
    dest_root = dest_dir.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    file_count = 0
    total_bytes = 0

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not (info.flag_bits & 0x800):
                try:
                    name = name.encode("cp437").decode("utf-8")
                except UnicodeError:
                    pass

            if info.is_dir() or name.endswith("/"):
                continue

            # Reject symlinks inside zip archives
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                log.warning("Skipping symlink in zip upload: %s", name)
                continue

            target = (dest_root / name).resolve()
            if not target.is_relative_to(dest_root):
                log.warning("Skipping zip-slip entry: %s", name)
                continue

            file_count += 1
            if file_count > MAX_FILES:
                raise ValueError(f"Zip archive exceeds maximum file count ({MAX_FILES})")
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError(f"Zip entry {name!r} exceeds maximum file size ({MAX_FILE_BYTES} bytes)")

            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(info) as src, target.open("wb") as out_fh:
                while True:
                    chunk = src.read(65_536)
                    if not chunk:
                        break
                    written += len(chunk)
                    total_bytes += len(chunk)
                    if written > MAX_FILE_BYTES:
                        out_fh.close()
                        target.unlink(missing_ok=True)
                        raise ValueError(f"Zip entry {name!r} exceeded uncompressed size limit ({MAX_FILE_BYTES} bytes)")
                    if total_bytes > MAX_TOTAL_BYTES:
                        out_fh.close()
                        target.unlink(missing_ok=True)
                        raise ValueError(f"Zip archive exceeded total uncompressed size limit ({MAX_TOTAL_BYTES} bytes)")
                    out_fh.write(chunk)


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
        try:
            _extract_zip_safely(fp, ex)
        finally:
            fp.unlink(missing_ok=True)
        m = load_folder(ex, source="upload", name=Path(filename).stem)
    else:
        m = load_folder(dst, source="upload", name=Path(filename).name)

    m.id = _mid("upload", h)
    m.label = label
    return m


def from_text(text: str, name: str | None = None) -> Material:
    """Free-text hint: pasted ad copy, a product name, or a list of URLs."""
    urls: list[str] = []
    for raw in _URL_RX.findall(text):
        cleaned = raw.rstrip(_URL_TRAILING_PUNCT)
        if cleaned and cleaned not in ("http://", "https://") and cleaned not in urls:
            urls.append(cleaned)
    m = Material(id=_mid("text", text), name=name or text[:60], source="text", source_ref=text[:200])
    m.texts.append(text)
    m.urls.extend(urls)
    return m


def from_url(url: str, capture: dict | None = None) -> Material:
    """A URL (ad landing page or ad-library link). `capture` = output of `capture.capture_url()`."""
    m = Material(id=_mid("url", url), name=url[:80], source="url", source_ref=url)
    m.urls.append(url)
    if capture:
        for kind in ("html", "har"):
            if capture.get(kind):
                m.pages.append({"kind": kind, "path": capture[kind], "url": capture.get("final_url") or url})
        if capture.get("screenshot"):
            m.images.append(capture["screenshot"])
        m.meta.extend(capture.get("meta", []))
        m.notes.extend(capture.get("notes", []))
        m.videos.extend(capture.get("videos", []))
    return m


def read_meta(m: Material) -> dict:
    """Merge known metadata formats: yt-dlp .info.json, capture_manifest.json, and archiver dns/ssl JSON."""
    out: dict = {"ad_library": [], "capture": [], "dns": []}
    for p in m.meta:
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        name = Path(p).name.lower()
        if name.endswith("info.json") and ("extractor" in d or "webpage_url" in d):
            out["ad_library"].append(
                {
                    "platform": d.get("extractor_key") or d.get("extractor"),
                    "ad_id": d.get("playlist_id") or d.get("id"),
                    "advertiser": d.get("playlist_uploader") or d.get("uploader"),
                    "advertiser_id": d.get("playlist_uploader_id") or d.get("uploader_id"),
                    "title": d.get("title"),
                    "description": d.get("description"),
                    "url": d.get("webpage_url"),
                    "timestamp": d.get("epoch") or d.get("timestamp"),
                    "duration": d.get("duration"),
                    "thumbnail": d.get("thumbnail"),
                }
            )
        elif "page_url" in d or "tool" in d:
            entry = {
                "url": d.get("page_url") or d.get("url"),
                "title": d.get("title"),
                "captured_at": d.get("captured_at"),
                "tool": d.get("tool"),
                "final_url": d.get("final_url"),
                "redirects": d.get("redirects") or d.get("redirect_chain"),
            }
            for ck in ("cloaking", "cloaking_verdict", "cloaking_reasons"):
                if ck in d:
                    entry[ck] = d[ck]
            out["capture"].append(entry)
        elif "dns" in name or "ssl" in name:
            out["dns"].append(d)
        else:
            out["capture"].append(
                {k: d.get(k) for k in ("url", "final_url", "title", "timestamp", "domain") if k in d}
            )
    return out


def clean_upload_dir(m: Material) -> None:
    """Remove the entire `data/uploads/<hash>` directory for an uploaded Material."""
    if m.source != "upload" or not m.source_ref:
        return
    uploads_root = (config.DATA / "uploads").resolve()
    ref = Path(m.source_ref).resolve()
    if ref.is_relative_to(uploads_root) and ref != uploads_root:
        top_dir = uploads_root / ref.relative_to(uploads_root).parts[0]
        shutil.rmtree(top_dir, ignore_errors=True)
