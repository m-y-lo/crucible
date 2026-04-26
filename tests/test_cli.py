"""Tests for crucible.cli.

Each command exercised in-process via Typer's CliRunner. The orchestrator
is patched at registry-load time so no Anthropic call ever fires; the
status command runs against a tiny temp DB.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from crucible.cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# Test scaffolding: minimal crucible.yaml + minimal SQLite store
# ---------------------------------------------------------------------------


def _write_min_config(path: Path, db_path: Path) -> None:
    """Write the smallest crucible.yaml that load_config accepts."""
    text = f"""
run:
  target: battery_cathode
  budget: 5
  output_dir: ./runs

predictors:
  - name: alignn

ranker:
  name: battery_cathode

store:
  name: sqlite
  path: {db_path}

orchestrator:
  name: claude_tools
  options:
    max_iterations: 4

materials_project:
  enabled: false
  novelty_filter: false
"""
    path.write_text(text)


def _make_demo_db(db_path: Path) -> None:
    """Mirror the schema from crucible/core/_schema.py and seed enough
    rows for status to render something."""
    schema = """
    CREATE TABLE runs (run_id TEXT PRIMARY KEY, target TEXT, config_json TEXT,
      budget INTEGER, started_at TIMESTAMP, ended_at TIMESTAMP);
    CREATE TABLE structures (structure_hash TEXT PRIMARY KEY, cif TEXT,
      composition TEXT, space_group INTEGER, prototype_label TEXT,
      num_sites INTEGER, density_g_per_cm3 REAL,
      source_generator TEXT, source_run_id TEXT, created_at TIMESTAMP);
    CREATE TABLE predictions (prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
      structure_hash TEXT, model_id TEXT, checkpoint TEXT, dataset TEXT,
      version TEXT, values_json TEXT, units_json TEXT,
      latency_ms INTEGER, created_at TIMESTAMP);
    CREATE TABLE rankings (ranking_id INTEGER PRIMARY KEY AUTOINCREMENT,
      structure_hash TEXT, run_id TEXT, target TEXT,
      ranker_name TEXT, ranker_version TEXT, passes_criteria INTEGER,
      score REAL, reasoning_json TEXT, created_at TIMESTAMP);
    CREATE TABLE gauntlet_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT, stage TEXT, passed INTEGER, reason TEXT,
      structure_hash TEXT, created_at TIMESTAMP);
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
        ("run-cli", "battery_cathode", "{}", 5, now, None),
    )
    conn.execute(
        "INSERT INTO structures VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("h1", "cif1", "Li2MnO3", 12, "ABC2_mC8_12_a", 6, 4.2,
         "random_baseline", "run-cli", now),
    )
    conn.execute(
        "INSERT INTO predictions VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        ("h1", "alignn", "jv_form", "JARVIS", "1.0",
         json.dumps({"formation_energy_eV_per_atom": -1.85, "bandgap_eV": 0.7}),
         "{}", 3, now),
    )
    conn.execute(
        "INSERT INTO rankings VALUES (NULL,?,?,?,?,?,?,?,?,?)",
        ("h1", "run-cli", "battery_cathode", "battery_cathode", "1.0", 1, 2.31, "{}", now),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# `crucible plugins`
# ---------------------------------------------------------------------------


def test_plugins_lists_every_kind_section() -> None:
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0, result.output
    out = result.output
    for kind in ("generator", "relaxer", "predictor", "ranker", "orchestrator", "store", "queue"):
        assert kind in out


def test_plugins_includes_registered_plugins() -> None:
    """We registered random_baseline / battery_cathode / claude_tools earlier
    in this branch's parent commits — they must show up here."""
    result = runner.invoke(app, ["plugins"])
    out = result.output
    assert "random_baseline" in out
    assert "battery_cathode" in out
    assert "claude_tools" in out


# ---------------------------------------------------------------------------
# `crucible status`
# ---------------------------------------------------------------------------


def test_status_renders_against_a_populated_db(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    _make_demo_db(db)
    cfg = tmp_path / "crucible.yaml"
    _write_min_config(cfg, db_path=db)

    result = runner.invoke(app, ["status", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Li2MnO3" in result.output
    assert "battery_cathode" in result.output


def test_status_missing_db_exits_with_help(tmp_path: Path) -> None:
    cfg = tmp_path / "crucible.yaml"
    _write_min_config(cfg, db_path=tmp_path / "nope.db")

    result = runner.invoke(app, ["status", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "No database at" in result.output


# ---------------------------------------------------------------------------
# `crucible predict`
# ---------------------------------------------------------------------------


def test_predict_missing_cif_path_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["predict", str(tmp_path / "nope.cif")]
    )
    assert result.exit_code == 1
    assert "CIF not found" in result.output


def test_predict_unknown_predictor_name_errors(tmp_path: Path) -> None:
    """A truly-unregistered name hits the KeyError branch and prints a hint."""
    cif_path = tmp_path / "x.cif"
    cif_path.write_text("dummy")
    result = runner.invoke(
        app, ["predict", str(cif_path), "--predictor", "no_such_predictor_xyz"]
    )
    assert result.exit_code == 1
    assert "Predictor not registered" in result.output
    assert "uv sync" in result.output or "ml" in result.output.lower()


def test_predict_alignn_on_macos_surfaces_runtime_error(tmp_path: Path) -> None:
    """ALIGNN is registered, but its constructor refuses on macOS because
    DGL's prebuilt graphbolt binary is missing. The CLI must catch the
    RuntimeError and exit cleanly rather than dump a traceback.
    """
    # Skip if DGL actually works (Linux / CUDA hosts).
    try:
        import dgl  # noqa: F401
        from dgl import graphbolt  # noqa: F401
        pytest.skip("DGL is importable on this host; ALIGNN can be constructed.")
    except (ImportError, FileNotFoundError):
        pass

    cif_path = tmp_path / "x.cif"
    cif_path.write_text("dummy")
    result = runner.invoke(app, ["predict", str(cif_path)])
    assert result.exit_code == 1
    assert "Predictor unavailable" in result.output
    assert "alignn" in result.output.lower() or "dgl" in result.output.lower()


# ---------------------------------------------------------------------------
# `crucible run` (orchestrator mocked; no Anthropic call)
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_orchestrator() -> Any:
    """Return a fake plugin instance whose `.run()` returns a stub run_id."""
    inst = MagicMock()
    inst.run.return_value = "fake-run-id-1234"
    return inst


def test_run_invokes_orchestrator_and_prints_run_id(
    tmp_path: Path, mocked_orchestrator: MagicMock
) -> None:
    db = tmp_path / "fresh.db"
    cfg = tmp_path / "crucible.yaml"
    _write_min_config(cfg, db_path=db)

    with patch("crucible.cli.registry_load", return_value=mocked_orchestrator):
        result = runner.invoke(app, ["run", "--config", str(cfg)])

    assert result.exit_code == 0, result.output
    assert "fake-run-id-1234" in result.output
    mocked_orchestrator.run.assert_called_once_with("battery_cathode", 5)


def test_run_overrides_target_and_budget_via_flags(
    tmp_path: Path, mocked_orchestrator: MagicMock
) -> None:
    db = tmp_path / "fresh.db"
    cfg = tmp_path / "crucible.yaml"
    _write_min_config(cfg, db_path=db)

    with patch("crucible.cli.registry_load", return_value=mocked_orchestrator):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg), "--target", "co2_sorbent", "--budget", "12"],
        )
    assert result.exit_code == 0, result.output
    mocked_orchestrator.run.assert_called_once_with("co2_sorbent", 12)


def test_run_unknown_orchestrator_exits_cleanly(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    cfg = tmp_path / "crucible.yaml"
    _write_min_config(cfg, db_path=db)

    with patch(
        "crucible.cli.registry_load",
        side_effect=KeyError("no such plugin: claude_tools"),
    ):
        result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "Unknown orchestrator" in result.output


# ---------------------------------------------------------------------------
# Top-level help
# ---------------------------------------------------------------------------


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "run" in result.output
    assert "status" in result.output
    assert "plugins" in result.output
    assert "predict" in result.output
