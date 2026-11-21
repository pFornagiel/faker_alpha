"""SQLite persistence of materials, features and vectors (the "previously analysed set")."""
from __future__ import annotations

import io
import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

from . import config
from .ingest import Material

_LOCK = threading.RLock()


def _np_to_blob(a) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.asarray(a), allow_pickle=False)
    return buf.getvalue()


def _blob_to_np(b: bytes):
    return np.load(io.BytesIO(b), allow_pickle=False)


class Store:
    def __init__(self, path: str | Path = config.STORE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY, name TEXT, source TEXT, label TEXT,
            created_at TEXT, material TEXT, features TEXT);
        CREATE TABLE IF NOT EXISTS vectors(material_id TEXT, kind TEXT, data BLOB, PRIMARY KEY(material_id, kind));
        CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS events(ts TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, payload TEXT);
        """)
        self._cache: dict[str, tuple[dict, dict]] | None = None

    # ------------------------------------------------------------------ materials
    def upsert(self, m: Material, features: dict, vectors: dict) -> None:
        with _LOCK:
            self.db.execute("INSERT OR REPLACE INTO materials VALUES(?,?,?,?,?,?,?)",
                            (m.id, m.name, m.source, m.label, m.created_at, json.dumps(m.to_dict(), ensure_ascii=False),
                             json.dumps(features, ensure_ascii=False, default=str)))
            self.db.execute("DELETE FROM vectors WHERE material_id=?", (m.id,))
            for k, v in vectors.items():
                if v is None or (hasattr(v, "__len__") and len(v) == 0):
                    continue
                self.db.execute("INSERT INTO vectors VALUES(?,?,?)", (m.id, k, _np_to_blob(v)))
            self.db.commit()
            self._cache = None

    def delete(self, mid: str) -> None:
        with _LOCK:
            self.db.execute("DELETE FROM materials WHERE id=?", (mid,))
            self.db.execute("DELETE FROM vectors WHERE material_id=?", (mid,))
            self.db.commit()
            self._cache = None

    def set_label(self, mid: str, label: str | None) -> None:
        with _LOCK:
            self.db.execute("UPDATE materials SET label=? WHERE id=?", (label, mid))
            row = self.db.execute("SELECT material FROM materials WHERE id=?", (mid,)).fetchone()
            if row:
                d = json.loads(row[0]); d["label"] = label
                self.db.execute("UPDATE materials SET material=? WHERE id=?", (json.dumps(d, ensure_ascii=False), mid))
            self.db.commit()
            self._cache = None

    def has(self, mid: str) -> bool:
        with _LOCK:
            return self.db.execute("SELECT 1 FROM materials WHERE id=?", (mid,)).fetchone() is not None

    def all(self) -> dict[str, tuple[dict, dict]]:
        """id -> (features (with material + label), vectors)"""
        with _LOCK:
            if self._cache is not None:
                return self._cache
            out = {}
            for mid, name, source, label, created, mat, feats in self.db.execute(
                    "SELECT id,name,source,label,created_at,material,features FROM materials ORDER BY created_at, name"):
                f = json.loads(feats)
                f["_material"] = json.loads(mat)
                f["_label"] = label
                out[mid] = (f, {})
            for mid, kind, blob in self.db.execute("SELECT material_id, kind, data FROM vectors"):
                if mid in out:
                    out[mid][1][kind] = _blob_to_np(blob)
            self._cache = out
            return out

    def count(self) -> int:
        with _LOCK:
            return self.db.execute("SELECT COUNT(*) FROM materials").fetchone()[0]

    # ------------------------------------------------------------------ kv / events
    def put(self, key: str, value) -> None:
        with _LOCK:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False, default=str)))
            self.db.commit()

    def get(self, key: str, default=None):
        with _LOCK:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def log(self, kind: str, payload) -> None:
        with _LOCK:
            self.db.execute("INSERT INTO events(kind,payload) VALUES(?,?)", (kind, json.dumps(payload, ensure_ascii=False, default=str)))
            self.db.commit()

    def events(self, limit: int = 200) -> list[dict]:
        with _LOCK:
            return [{"ts": ts, "kind": k, "payload": json.loads(p)} for ts, k, p in
                    self.db.execute("SELECT ts, kind, payload FROM events ORDER BY rowid DESC LIMIT ?", (limit,))]
