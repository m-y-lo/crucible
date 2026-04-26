"""Tests for crucible.reports.status.

Build a temp SQLite DB matching the project schema, populate it with a
small fixture, and assert that the rendered report contains the right
formulas, scores, and pass-rates. Tests are formatter tests; the SQL
shape is canonical (mirrors crucible/core/_schema.py).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crucible.reports.status import (
    render_gauntlet_histogram,
    render_leaderboard,
    render_run_summary,
    render_status,
)


# ---------------------------------------------------------------------------
# Fixture: minimal DB matching crucible/core/_schema.py
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, target TEXT NOT NULL, config_json TEXT NOT NULL,
  budget INTEGER NOT NULL, started_at TIMESTAMP NOT NULL, ended_at TIMESTAMP);
CREATE TABLE structures (
  structure_hash TEXT PRIMARY KEY, cif TEXT NOT NULL, composition TEXT NOT NULL,
  space_group INTEGER NOT NULL, prototype_label TEXT NOT NULL,
  num_sites INTEGER, density_g_per_cm3 REAL,
  source_generator TEXT NOT NULL, source_run_id TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL);
CREATE TABLE predictions (
  prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash TEXT NOT NULL, model_id TEXT NOT NULL, checkpoint TEXT NOT NULL,
  dataset TEXT NOT NULL, version TEXT NOT NULL,
  values_json TEXT NOT NULL, units_json TEXT NOT NULL,
  latency_ms INTEGER, created_at TIMESTAMP NOT NULL);
CREATE TABLE rankings (
  ranking_id INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash TEXT NOT NULL, run_id TEXT NOT NULL, target TEXT NOT NULL,
  ranker_name TEXT NOT NULL, ranker_version TEXT NOT NULL,
  passes_criteria INTEGER NOT NULL, score REAL, reasoning_json TEXT,
  created_at TIMESTAMP NOT NULL);
CREATE TABLE gauntlet_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL, stage TEXT NOT NULL, passed INTEGER NOT NULL,
  reason TEXT, structure_hash TEXT, created_at TIMESTAMP NOT NULL);
"""


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "crucible.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
        ("run-abc", "battery_cathode", "{}", 100, now, None),
    )
    # Two structures, both Li-cathode-shaped.
    conn.execute(
        "INSERT INTO structures VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("hash-AAAA", "cif-A", "Li2MnO3", 12, "ABC2_mC8_12_a", 6, 4.2,
         "random_baseline", "run-abc", now),
    )
    conn.execute(
        "INSERT INTO structures VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("hash-BBBB", "cif-B", "LiFePO4", 62, "ABCD4_oP24_62_a", 24, 3.5,
         "random_baseline", "run-abc", now),
    )
    conn.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (None, "hash-AAAA", "alignn", "jv_form_e", "JARVIS-DFT", "1.0",
         json.dumps({"formation_energy_eV_per_atom": -1.85, "bandgap_eV": 0.7}),
         json.dumps({"formation_energy_eV_per_atom": "eV/atom", "bandgap_eV": "eV"}),
         3, now),
    )
    conn.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (None, "hash-BBBB", "alignn", "jv_form_e", "JARVIS-DFT", "1.0",
         json.dumps({"formation_energy_eV_per_atom": -1.91, "bandgap_eV": 1.1}),
         json.dumps({"formation_energy_eV_per_atom": "eV/atom", "bandgap_eV": "eV"}),
         3, now),
    )
    conn.execute(
        "INSERT INTO rankings VALUES (?,?,?,?,?,?,?,?,?,?)",
        (None, "hash-AAAA", "run-abc", "battery_cathode",
         "battery_cathode", "1.0", 1, 2.31, "{}", now),
    )
    conn.execute(
        "INSERT INTO rankings VALUES (?,?,?,?,?,?,?,?,?,?)",
        (None, "hash-BBBB", "run-abc", "battery_cathode",
         "battery_cathode", "1.0", 1, 2.18, "{}", now),
    )
    # Gauntlet histogram seed: parse 4/6, composition 3/4, geometry 3/3,
    # novelty 2/3, dedup 2/2 -- some passes, some rejections for each.
    events = [
        ("parse", 1, 4), ("parse", 0, 2),
        ("composition", 1, 3), ("composition", 0, 1),
        ("geometry", 1, 3),
        ("novelty", 1, 2), ("novelty", 0, 1),
        ("dedup", 1, 2),
    ]
    for stage, passed, count in events:
        for _ in range(count):
            conn.execute(
                "INSERT INTO gauntlet_events VALUES (?,?,?,?,?,?,?)",
                (None, "run-abc", stage, passed, None, None, now),
            )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# render_status (full report)
# ---------------------------------------------------------------------------


def test_render_status_full_report_contains_every_section(db: Path) -> None:
    out = render_status(db, run_id="run-abc")
    assert "run-abc" in out
    assert "battery_cathode" in out
    # Top candidates by score: Li2MnO3 (2.310) above LiFePO4 (2.180)
    assert "Li2MnO3" in out
    assert "LiFePO4" in out
    li2mno3_pos = out.index("Li2MnO3")
    lifepo4_pos = out.index("LiFePO4")
    assert li2mno3_pos < lifepo4_pos, "leaderboard must be sorted by score desc"

    # Gauntlet histogram has all five stages.
    for stage in ("parse", "composition", "geometry", "novelty", "dedup"):
        assert stage in out

    # Pass rates: parse 4/6 = 66.7%
    assert "66.7%" in out


def test_render_status_latest_run_when_run_id_omitted(db: Path) -> None:
    out = render_status(db, run_id=None)
    assert "run-abc" in out


def test_render_status_missing_db_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        render_status(tmp_path / "nope.db")


# ---------------------------------------------------------------------------
# render_run_summary
# ---------------------------------------------------------------------------


def test_render_run_summary_with_data() -> None:
    out = render_run_summary(
        {
            "run_id": "run-xyz",
            "target": "battery_cathode",
            "budget": 50,
            "started_at": "2026-04-25T00:00:00Z",
            "ended_at": None,
        }
    )
    assert "run-xyz" in out
    assert "battery_cathode" in out
    assert "50" in out
    assert "in progress" in out


def test_render_run_summary_no_run() -> None:
    assert "No run record" in render_run_summary(None)


# ---------------------------------------------------------------------------
# render_leaderboard
# ---------------------------------------------------------------------------


def test_render_leaderboard_empty_shows_placeholder() -> None:
    out = render_leaderboard([], top_n=10)
    assert "Top 10 candidates" in out
    # Empty -> placeholder em-dash row.
    assert "—" in out


def test_render_leaderboard_truncates_to_top_n() -> None:
    rows = [
        {
            "score": float(i),
            "composition": f"X{i}",
            "space_group": 1,
            "prototype_label": "stub",
            "structure_hash": f"h{i:032d}",
            "values_json": "{}",
        }
        for i in range(20, 0, -1)
    ]
    out = render_leaderboard(rows, top_n=3)
    # Three composition cells X20, X19, X18 expected; X17 should not appear.
    assert "X20" in out and "X19" in out and "X18" in out
    assert "X17" not in out


# ---------------------------------------------------------------------------
# render_gauntlet_histogram
# ---------------------------------------------------------------------------


def test_render_gauntlet_histogram_zero_data_shows_em_dash_rate() -> None:
    out = render_gauntlet_histogram([])
    # All five canonical stages still rendered, all with 0/0 -> em-dash rate.
    for stage in ("parse", "composition", "geometry", "novelty", "dedup"):
        assert stage in out
    assert "—" in out


def test_render_gauntlet_histogram_pass_rate_math() -> None:
    summary = [
        {"stage": "parse", "passed": 1, "count": 8},
        {"stage": "parse", "passed": 0, "count": 2},
    ]
    out = render_gauntlet_histogram(summary)
    # 8 / (8+2) = 80.0%
    assert "80.0%" in out
    assert "8" in out and "2" in out
