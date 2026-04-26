"""Tests for crucible.predictors.alignn.

Same DGL-availability gating as ``test_relaxers_alignn_ff``: the guard
fires today on macOS Apple Silicon, so we assert it produces a clean
``RuntimeError``. When DGL ships, the skipped tests light up and
exercise the real predictor.
"""

from __future__ import annotations

import pytest


def _dgl_actually_works() -> bool:
    try:
        import dgl  # noqa: F401
        from dgl import graphbolt  # noqa: F401
        return True
    except (ImportError, FileNotFoundError):
        return False


DGL_OK = _dgl_actually_works()


def test_construction_raises_clean_runtimeerror_when_dgl_missing() -> None:
    if DGL_OK:
        pytest.skip("DGL is importable; this test asserts the failure path.")

    from crucible.predictors.alignn import AlignnPredictor

    with pytest.raises(RuntimeError) as exc:
        AlignnPredictor()
    msg = str(exc.value).lower()
    assert "alignn" in msg
    assert "dgl" in msg or "graphbolt" in msg


def test_registry_load_surfaces_the_runtimeerror() -> None:
    if DGL_OK:
        pytest.skip("DGL is importable; not exercising the failure path.")

    from crucible.core.registry import load as registry_load

    with pytest.raises(RuntimeError):
        registry_load("predictor", "alignn")


@pytest.mark.skipif(not DGL_OK, reason="DGL/graphbolt not importable on this platform")
def test_real_predictor_loads_with_default_checkpoints() -> None:
    from crucible.predictors.alignn import AlignnPredictor

    predictor = AlignnPredictor()
    assert predictor.name == "alignn"
    assert predictor.provenance.model_id == "alignn"
    assert predictor.provenance.dataset == "JARVIS-DFT"
    # Default property keys are the unit-suffixed ones the ranker expects.
    assert "formation_energy_eV_per_atom" in predictor._checkpoints
    assert "bandgap_eV" in predictor._checkpoints
