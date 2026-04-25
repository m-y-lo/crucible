"""Cached pymatgen MPRester wrapper.

Single chokepoint for every Materials Project query made anywhere in the
codebase. Used by ``gauntlet.novelty``, and (Phase 2) ``data.calibration``
and ``data.seeds``.

Why caching matters: a discovery run may issue thousands of "is this
formula in MP?" queries. MP rate-limits and queries cost ~hundreds of ms
each. The MP database itself updates roughly monthly, so caching forever
locally is safe — delete the cache file if you suspect it's stale.

The cache backend is SQLite. Each query is keyed by
``(method_name, frozen_kwargs_hash)`` and stores the JSON-serializable
``Structure.as_dict()`` form of each result, which is robust to pymatgen
upgrades in a way that pickle is not.

Requires ``MP_API_KEY`` in the environment (load via python-dotenv from
``.env`` at the application entry point — this module does not call
``load_dotenv`` itself).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.core import Structure


# Default cache location. Lives outside of `runs/` so it survives between
# discovery runs.
_DEFAULT_CACHE_PATH = Path(".cache") / "mp_cache.sqlite"

# Schema version. Bump if we change the cache layout so old caches are
# rebuilt rather than misread.
_SCHEMA_VERSION = 1


def _make_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS mp_cache (
            query_key   TEXT PRIMARY KEY,
            payload     TEXT NOT NULL,
            cached_at   TEXT NOT NULL,
            schema_ver  INTEGER NOT NULL DEFAULT {_SCHEMA_VERSION}
        );
        """
    )


def _query_key(method: str, **kwargs: Any) -> str:
    """Stable hash key for a (method, kwargs) pair."""
    canonical = json.dumps({"m": method, "k": kwargs}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class MPClient:
    """Cached client for the small slice of Materials Project we use.

    Construct directly with an explicit api_key + cache_path, or call
    ``MPClient.from_env()`` to read ``MP_API_KEY`` from the environment.

    Methods always return ``pymatgen.Structure`` objects, never raw MP
    response docs — keeps callers free of mp-api version coupling.
    """

    def __init__(self, api_key: str, cache_path: Path | None = None) -> None:
        if not api_key:
            raise ValueError("MPClient requires a non-empty api_key.")
        self._api_key = api_key
        self._cache_path = Path(cache_path) if cache_path else _DEFAULT_CACHE_PATH
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            _make_schema(conn)

    @classmethod
    def from_env(cls, cache_path: Path | None = None) -> "MPClient":
        """Construct from ``MP_API_KEY``. Raises ``RuntimeError`` if unset."""
        key = os.environ.get("MP_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "MP_API_KEY not set. Add it to .env or export it before "
                "constructing MPClient."
            )
        return cls(api_key=key, cache_path=cache_path)

    # -------------------------------------------------------------- internals

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._cache_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _cache_get(self, key: str) -> list[dict] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM mp_cache WHERE query_key = ? AND schema_ver = ?",
                (key, _SCHEMA_VERSION),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def _cache_put(self, key: str, structures_as_dicts: list[dict]) -> None:
        payload = json.dumps(structures_as_dicts, separators=(",", ":"))
        cached_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mp_cache "
                "(query_key, payload, cached_at, schema_ver) VALUES (?, ?, ?, ?)",
                (key, payload, cached_at, _SCHEMA_VERSION),
            )

    def _open_rester(self):  # pragma: no cover - thin import shim
        # Imported lazily so tests that monkeypatch `MPClient._open_rester`
        # never touch the real network client.
        from mp_api.client import MPRester
        return MPRester(self._api_key)

    # ------------------------------------------------------------------ API

    def get_structures_by_formula(self, formula: str) -> list[Structure]:
        """Return every MP structure with this reduced formula.

        Empty list if none. Cached by formula. The returned ``Structure``
        objects are reconstituted from cached ``as_dict()`` payloads.
        """
        key = _query_key("get_structures_by_formula", formula=formula)
        cached = self._cache_get(key)
        if cached is not None:
            return [Structure.from_dict(d) for d in cached]

        with self._open_rester() as mpr:
            docs = mpr.materials.summary.search(
                formula=formula, fields=["material_id", "structure"]
            )
        structures = [doc.structure for doc in docs if doc.structure is not None]
        self._cache_put(key, [s.as_dict() for s in structures])
        return structures

    def get_structure_by_mp_id(self, mp_id: str) -> Structure | None:
        """Fetch a specific MP entry by id (e.g. ``"mp-19009"``).

        Returns None if the id is not in MP. Cached.
        """
        key = _query_key("get_structure_by_mp_id", mp_id=mp_id)
        cached = self._cache_get(key)
        if cached is not None:
            return Structure.from_dict(cached[0]) if cached else None

        with self._open_rester() as mpr:
            docs = mpr.materials.summary.search(
                material_ids=[mp_id], fields=["material_id", "structure"]
            )
        if not docs or docs[0].structure is None:
            self._cache_put(key, [])
            return None
        structure = docs[0].structure
        self._cache_put(key, [structure.as_dict()])
        return structure
