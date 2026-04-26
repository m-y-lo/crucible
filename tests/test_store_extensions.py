"""Tests for the LocalStore extensions added in Phase 1.5:

- ``insert_run`` / ``mark_run_ended``
- ``insert_ranking``
- ``insert_gauntlet_event``

Ming's existing ``insert_structure`` / ``insert_prediction`` tests live in
``tests/test_store.py`` and stay untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from crucible.stores.sqlite_store import LocalStore


def _query(store: LocalStore, sql: str, *params) -> list[dict]:
    rows = store._require_open().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# insert_run + mark_run_ended
# --------------------------------------------------------------------------


def test_insert_run_records_started_at_and_no_end(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    rows = _query(store, "SELECT * FROM runs WHERE run_id = ?", "r1")
    assert len(rows) == 1
    assert rows[0]["target"] == "battery_cathode"
    assert rows[0]["budget"] == 50
    assert rows[0]["started_at"]
    assert rows[0]["ended_at"] is None
    store.close()


def test_insert_run_is_idempotent(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_run("r1", "battery_cathode", 50)  # second call no-ops
    rows = _query(store, "SELECT * FROM runs WHERE run_id = ?", "r1")
    assert len(rows) == 1
    store.close()


def test_mark_run_ended_sets_timestamp(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.mark_run_ended("r1")
    rows = _query(store, "SELECT ended_at FROM runs WHERE run_id = ?", "r1")
    assert rows[0]["ended_at"]
    store.close()


# --------------------------------------------------------------------------
# insert_ranking
# --------------------------------------------------------------------------


def test_insert_ranking_round_trips(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_ranking(
        structure_hash="abc",
        run_id="r1",
        target="battery_cathode",
        ranker_name="battery_cathode",
        ranker_version="1.0",
        passes_criteria=True,
        score=2.5,
        reasoning_json="{}",
    )
    rows = _query(store, "SELECT * FROM rankings WHERE run_id = ?", "r1")
    assert len(rows) == 1
    assert rows[0]["structure_hash"] == "abc"
    assert rows[0]["passes_criteria"] == 1
    assert rows[0]["score"] == 2.5
    store.close()


def test_insert_ranking_idempotent_under_unique_key(tmp_path: Path) -> None:
    """UNIQUE (structure_hash, run_id, target, ranker_name, ranker_version)."""
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    for score in (1.0, 2.0, 3.0):
        store.insert_ranking(
            "abc", "r1", "battery_cathode", "battery_cathode", "1.0", True, score
        )
    rows = _query(store, "SELECT * FROM rankings WHERE run_id = ?", "r1")
    assert len(rows) == 1
    # First write wins under INSERT OR IGNORE.
    assert rows[0]["score"] == 1.0
    store.close()


def test_insert_ranking_passes_false_score_nullable(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_ranking(
        "abc", "r1", "battery_cathode", "battery_cathode", "1.0",
        passes_criteria=False, score=None,
    )
    rows = _query(store, "SELECT score, passes_criteria FROM rankings")
    assert rows[0]["passes_criteria"] == 0
    assert rows[0]["score"] is None
    store.close()


# --------------------------------------------------------------------------
# insert_gauntlet_event
# --------------------------------------------------------------------------


def test_insert_gauntlet_event_appends_each_call(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_gauntlet_event("r1", "parse", True)
    store.insert_gauntlet_event("r1", "parse", False, reason="bad numerics")
    store.insert_gauntlet_event(
        "r1", "geometry", False, reason="overlap", structure_hash="hxx"
    )
    rows = _query(
        store, "SELECT stage, passed, reason, structure_hash FROM gauntlet_events ORDER BY event_id"
    )
    assert len(rows) == 3
    assert rows[0] == {"stage": "parse", "passed": 1, "reason": None, "structure_hash": None}
    assert rows[1]["reason"] == "bad numerics"
    assert rows[2]["structure_hash"] == "hxx"
    store.close()


def test_insert_gauntlet_event_passes_int_coercion(tmp_path: Path) -> None:
    """`passed` must be stored as int 0/1 regardless of how callers pass it."""
    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_gauntlet_event("r1", "parse", passed=True)
    store.insert_gauntlet_event("r1", "parse", passed=False)
    rows = _query(store, "SELECT passed FROM gauntlet_events ORDER BY event_id")
    assert [r["passed"] for r in rows] == [1, 0]
    store.close()


# --------------------------------------------------------------------------
# Foreign-key sanity (the schema wires rankings -> runs and -> structures)
# --------------------------------------------------------------------------


def test_status_query_pattern_executes(tmp_path: Path) -> None:
    """Smoke-check that ``reports.status``-style joins succeed against a DB
    populated entirely through the new write API."""
    from datetime import datetime, timezone

    from crucible.core.models import Structure as CoreStructure

    store = LocalStore(tmp_path / "x.db")
    store.insert_run("r1", "battery_cathode", 50)
    store.insert_structure(
        CoreStructure(
            cif="dummy_cif",
            structure_hash="abc",
            prototype_label="AB_cF8_225_ab",
            composition="LiCl",
            space_group=225,
            source_generator="random_baseline",
            source_run_id="r1",
            created_at=datetime.now(timezone.utc),
        )
    )
    store.insert_ranking("abc", "r1", "battery_cathode", "battery_cathode",
                         "1.0", True, 2.5)
    store.insert_gauntlet_event("r1", "parse", True)
    store.mark_run_ended("r1")

    rows = _query(
        store,
        """
        SELECT s.composition, r.score
        FROM rankings r
        JOIN structures s USING (structure_hash)
        WHERE r.run_id = ? AND r.passes_criteria = 1
        ORDER BY r.score DESC
        """,
        "r1",
    )
    assert rows == [{"composition": "LiCl", "score": 2.5}]
    store.close()
