"""`LocalStore` — SQLite-backed `ResultStore` for solo and Phase-1 runs.

Applies the schema from ARCHITECTURE.md §4 in `__init__`. Six tables:
runs, structures, predictions, rankings, jobs, gauntlet_events. The
predictions UNIQUE on `(structure_hash, model_id, checkpoint, version)` is
load-bearing — see playbook §F.

Wave 2 work. The Protocol it implements lives in
`crucible.core.protocols.ResultStore`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from crucible.core.models import Prediction, Structure


# Full DDL for ARCHITECTURE.md §4. Applied via executescript with
# CREATE TABLE IF NOT EXISTS so re-opening an existing store is a no-op.
_SCHEMA = """
-- TODO Wave 2: paste exact DDL from ARCHITECTURE.md §4 here, including:
--   runs, structures, predictions (UNIQUE constraint!),
--   rankings, jobs, gauntlet_events; plus all CREATE INDEX statements.
"""


class LocalStore:
    """Synchronous `ResultStore` backed by a single SQLite file."""

    def __init__(self, path: Path | str) -> None:
        # TODO Wave 2:
        #   1. Path(path).parent.mkdir(parents=True, exist_ok=True).
        #   2. self._conn = sqlite3.connect(str(path), isolation_level=None)
        #      for autocommit semantics. Set row_factory = sqlite3.Row.
        #   3. self._conn.execute("PRAGMA foreign_keys = ON")
        #   4. self._conn.execute("PRAGMA journal_mode = WAL")
        #   5. self._conn.executescript(_SCHEMA)
        raise NotImplementedError

    def insert_structure(self, s: Structure) -> None:
        # TODO Wave 2:
        #   INSERT OR IGNORE INTO structures(structure_hash, cif, composition,
        #     space_group, prototype_label, num_sites, density_g_per_cm3,
        #     source_generator, source_run_id, created_at) VALUES (...)
        # OR IGNORE handles dup hashes from re-runs naturally.
        raise NotImplementedError

    def insert_prediction(self, p: Prediction) -> None:
        # TODO Wave 2:
        #   Serialize p.values and p.provenance.units as JSON.
        #   INSERT OR IGNORE INTO predictions(structure_hash, model_id, checkpoint,
        #     dataset, version, values_json, units_json, latency_ms, created_at)
        #   VALUES (...). UNIQUE constraint handles re-runs.
        raise NotImplementedError

    def get_by_hash(self, structure_hash: str) -> Structure | None:
        # TODO Wave 2:
        #   SELECT * FROM structures WHERE structure_hash = ? LIMIT 1.
        #   If row None, return None; else rebuild Structure from row.
        raise NotImplementedError

    def list_by_target(self, target: str, limit: int = 100) -> list[dict]:
        # TODO Wave 2:
        #   JOIN rankings + structures + (best prediction per checkpoint).
        #   ORDER BY rankings.score DESC LIMIT ?.
        #   Return list of dicts (one per surviving structure) with keys:
        #     structure_hash, composition, score, properties (dict), ranker_name.
        raise NotImplementedError

    def dedup_against_known(self, s: Structure) -> str | None:
        # TODO Wave 2:
        #   1. SELECT structure_hash FROM structures
        #      WHERE prototype_label = ? AND composition = ?
        #      LIMIT 1.   # coarse pre-filter
        #   2. If found, return that hash; the gauntlet/dedup module decides
        #      whether to escalate to a full StructureMatcher comparison.
        raise NotImplementedError

    def materialize_view(self, name: str) -> None:
        # TODO Wave 2:
        #   CREATE TABLE IF NOT EXISTS view_<name> AS SELECT ...; or a real VIEW.
        #   For 'top_battery_cathodes': join rankings + structures + best
        #   alignn predictions, filter passes_criteria=1, order by score DESC.
        raise NotImplementedError

    def close(self) -> None:
        """Close the SQLite connection. Safe to call multiple times."""
        # TODO Wave 2:
        #   if self._conn is not None: self._conn.close(); self._conn = None
        raise NotImplementedError
