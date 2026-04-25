"""`LocalStore` — synchronous SQLite-backed `ResultStore` for Phase 1.

<<<<<<< Updated upstream
Applies the schema from ARCHITECTURE.md §4 in `__init__`. Six tables:
runs, structures, predictions, rankings, jobs, gauntlet_events. The
predictions UNIQUE on `(structure_hash, model_id, checkpoint, version)` is
load-bearing — see playbook §F.

Wave 2 work. The Protocol it implements lives in
`crucible.core.protocols.ResultStore`.
=======
Applies the shared schema in `__init__` and implements every method on
the `ResultStore` Protocol. The orchestrator and gauntlet are sync at
this layer; the async queue (`LocalQueue`) shares the same SQLite file.

Phase-3 `RemoteStore` will implement the same Protocol against an HTTP
server with no caller-side changes.
>>>>>>> Stashed changes
"""

from __future__ import annotations

<<<<<<< Updated upstream
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
=======
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from crucible.core._schema import SCHEMA
from crucible.core.models import Prediction, Structure


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStore:
    """Synchronous `ResultStore` backed by a single SQLite file.

    Construct with a path; the parent directory is created if missing,
    schema is applied (idempotently). Call `close()` when finished —
    safe to call twice.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(
            str(self._path), isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # ResultStore Protocol implementation
    # ------------------------------------------------------------------

    def insert_structure(self, s: Structure) -> None:
        """Insert a structure; duplicate hash is a no-op (INSERT OR IGNORE)."""
        self._require_open().execute(
            """
            INSERT OR IGNORE INTO structures
                (structure_hash, cif, composition, space_group,
                 prototype_label, source_generator, source_run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.structure_hash,
                s.cif,
                s.composition,
                s.space_group,
                s.prototype_label,
                s.source_generator,
                s.source_run_id,
                s.created_at.isoformat(),
            ),
        )

    def insert_prediction(self, p: Prediction) -> None:
        """Insert a prediction; UNIQUE on (hash, model, checkpoint, version)
        means re-running the same predictor is a no-op.
        """
        self._require_open().execute(
            """
            INSERT OR IGNORE INTO predictions
                (structure_hash, model_id, checkpoint, dataset, version,
                 values_json, units_json, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.structure_hash,
                p.provenance.model_id,
                p.provenance.checkpoint,
                p.provenance.dataset,
                p.provenance.version,
                json.dumps(p.values),
                json.dumps(p.provenance.units),
                p.latency_ms,
                p.created_at.isoformat(),
            ),
        )

    def get_by_hash(self, structure_hash: str) -> Structure | None:
        row = self._require_open().execute(
            """
            SELECT cif, structure_hash, prototype_label, composition,
                   space_group, source_generator, source_run_id, created_at
            FROM structures WHERE structure_hash = ?
            LIMIT 1
            """,
            (structure_hash,),
        ).fetchone()
        if row is None:
            return None
        return Structure(
            cif=row["cif"],
            structure_hash=row["structure_hash"],
            prototype_label=row["prototype_label"],
            composition=row["composition"],
            space_group=row["space_group"],
            source_generator=row["source_generator"],
            source_run_id=row["source_run_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_by_target(self, target: str, limit: int = 100) -> list[dict]:
        """Top-N ranked structures for a target with their predicted properties.

        Each row dict has: `structure_hash`, `composition`, `score`,
        `ranker_name`, `passes_criteria`, `properties` (a
        `{checkpoint: {prop_name: value}}` mapping aggregated from the
        `predictions` table).
        """
        rows = self._require_open().execute(
            """
            SELECT s.structure_hash, s.composition, s.space_group,
                   r.score, r.ranker_name, r.passes_criteria,
                   (SELECT json_group_object(p.checkpoint, p.values_json)
                    FROM predictions p
                    WHERE p.structure_hash = s.structure_hash) AS predictions_json
            FROM structures s
            JOIN rankings r ON r.structure_hash = s.structure_hash
            WHERE r.target = ?
            ORDER BY r.score DESC
            LIMIT ?
            """,
            (target, limit),
        ).fetchall()
        results: list[dict] = []
        for row in rows:
            preds_outer = (
                json.loads(row["predictions_json"]) if row["predictions_json"] else {}
            )
            properties = {
                checkpoint: json.loads(values_json)
                for checkpoint, values_json in preds_outer.items()
            }
            results.append({
                "structure_hash": row["structure_hash"],
                "composition": row["composition"],
                "space_group": row["space_group"],
                "score": row["score"],
                "ranker_name": row["ranker_name"],
                "passes_criteria": bool(row["passes_criteria"]),
                "properties": properties,
            })
        return results

    def dedup_against_known(self, s: Structure) -> str | None:
        """Coarse pre-filter: same prototype_label + composition.

        Returns the matching `structure_hash` (which may equal `s`'s own)
        or None if novel. The gauntlet's full StructureMatcher comparison
        is escalated only when this returns a hit.
        """
        row = self._require_open().execute(
            """
            SELECT structure_hash FROM structures
            WHERE prototype_label = ? AND composition = ?
            LIMIT 1
            """,
            (s.prototype_label, s.composition),
        ).fetchone()
        return row["structure_hash"] if row else None

    def materialize_view(self, name: str) -> None:
        """Refresh a denormalized view table for a ranker target.

        `name` must be alphanumeric+underscore (used as both the table
        suffix `view_<name>` and the `rankings.target` filter value). Only
        rankings with `passes_criteria = 1` are included. Replaces any
        existing view table with the same name.
        """
        if not name or not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(
                f"View name {name!r} must be non-empty and alphanumeric+underscore"
            )
        view_table = f"view_{name}"
        conn = self._require_open()
        conn.execute(f"DROP TABLE IF EXISTS {view_table}")
        conn.execute(
            f"""
            CREATE TABLE {view_table} AS
            SELECT s.structure_hash, s.composition, s.space_group,
                   r.score, r.ranker_name,
                   (SELECT json_group_object(p.checkpoint, p.values_json)
                    FROM predictions p
                    WHERE p.structure_hash = s.structure_hash) AS predictions_json
            FROM structures s
            JOIN rankings r ON r.structure_hash = s.structure_hash
            WHERE r.target = ? AND r.passes_criteria = 1
            ORDER BY r.score DESC
            """,
            (name,),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the connection. Safe to call twice."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_open(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("LocalStore is closed")
        return self._conn
>>>>>>> Stashed changes
