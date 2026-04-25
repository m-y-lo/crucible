"""Tests for `crucible.stores.sqlite_store.LocalStore` — Wave 2."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2 implementation pending")
def test_round_trip_structure_and_prediction(tmp_path) -> None:
    """Insert a Structure + Prediction, fetch back by hash, fields match."""
    # TODO:
    #   store = LocalStore(tmp_path / "crucible.db")
    #   store.insert_structure(s); store.insert_prediction(p)
    #   got = store.get_by_hash(s.structure_hash)
    #   assert got.composition == s.composition
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
def test_predictions_unique_constraint(tmp_path) -> None:
    """Re-inserting the same (structure_hash, model_id, checkpoint, version)
    is a no-op — INSERT OR IGNORE.
    """
    # TODO: insert same Prediction twice; SELECT COUNT(*) == 1.
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
def test_dedup_against_known_finds_match(tmp_path) -> None:
    """Same prototype_label + composition returns the existing hash."""
    # TODO:
    #   - insert s1 with prototype="X", composition="LiCoO2"
    #   - build s2 with same prototype + composition, different cif/hash
    #   - assert dedup_against_known(s2) == s1.structure_hash
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
def test_localstore_implements_resultstore_protocol(tmp_path) -> None:
    """isinstance(LocalStore(...), ResultStore) is True."""
    # TODO:
    #   from crucible.core.protocols import ResultStore
    #   assert isinstance(LocalStore(tmp_path / "x.db"), ResultStore)
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
def test_close_is_idempotent(tmp_path) -> None:
    """Calling close twice should not raise."""
    # TODO
    ...
