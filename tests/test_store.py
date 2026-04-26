"""Tests for `crucible.stores.sqlite_store.LocalStore`."""

from __future__ import annotations

import json
import sqlite3

from crucible.core.models import ModelProvenance, Prediction, Structure
from crucible.core.protocols import ResultStore
from crucible.stores.sqlite_store import LocalStore


def _structure(
    structure_hash: str = "hash-1",
    *,
    prototype_label: str = "AB_cF8_225_ab",
    composition: str = "LiCoO2",
) -> Structure:
    return Structure(
        cif="data_test\n",
        structure_hash=structure_hash,
        prototype_label=prototype_label,
        composition=composition,
        space_group=225,
        source_generator="test",
        source_run_id="run-1",
    )


def _prediction(structure_hash: str = "hash-1") -> Prediction:
    return Prediction(
        structure_hash=structure_hash,
        provenance=ModelProvenance(
            model_id="alignn",
            checkpoint="jv_formation_energy_peratom_alignn",
            dataset="JARVIS-DFT",
            version="test-version",
            units={"formation_energy_eV_per_atom": "eV/atom"},
        ),
        values={"formation_energy_eV_per_atom": -1.23},
        latency_ms=7,
    )


def test_round_trip_structure_and_prediction(tmp_path) -> None:
    """Insert a Structure + Prediction, fetch back by hash, fields match."""
    db_path = tmp_path / "crucible.db"
    store = LocalStore(db_path)
    try:
        s = _structure()
        p = _prediction()
        store.insert_structure(s)
        store.insert_prediction(p)

        got = store.get_by_hash(s.structure_hash)
        assert got == s

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT values_json, units_json FROM predictions WHERE structure_hash = ?",
                (s.structure_hash,),
            ).fetchone()
        assert json.loads(row[0]) == p.values
        assert json.loads(row[1]) == p.provenance.units
    finally:
        store.close()


def test_predictions_unique_constraint(tmp_path) -> None:
    """Re-inserting the same (structure_hash, model_id, checkpoint, version)
    is a no-op — INSERT OR IGNORE.
    """
    db_path = tmp_path / "crucible.db"
    store = LocalStore(db_path)
    try:
        store.insert_structure(_structure())
        p = _prediction()
        store.insert_prediction(p)
        store.insert_prediction(p)

        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        assert count == 1
    finally:
        store.close()


def test_dedup_against_known_finds_match(tmp_path) -> None:
    """Same prototype_label + composition returns the existing hash."""
    store = LocalStore(tmp_path / "crucible.db")
    try:
        known = _structure("known-hash")
        candidate = _structure("candidate-hash")
        store.insert_structure(known)
        assert store.dedup_against_known(candidate) == known.structure_hash
    finally:
        store.close()


def test_localstore_implements_resultstore_protocol(tmp_path) -> None:
    """isinstance(LocalStore(...), ResultStore) is True."""
    store = LocalStore(tmp_path / "x.db")
    try:
        assert isinstance(store, ResultStore)
    finally:
        store.close()


def test_close_is_idempotent(tmp_path) -> None:
    """Calling close twice should not raise."""
    store = LocalStore(tmp_path / "crucible.db")
    store.close()
    store.close()
