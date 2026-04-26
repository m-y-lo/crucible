"""Tests for crucible.relaxers.alignn_ff.

ALIGNN-FF requires DGL, whose prebuilt graphbolt binary is missing on
macOS Apple Silicon for the torch versions we use. We therefore verify
the *guard* fires cleanly — the registry must surface a useful
RuntimeError rather than crash with a low-level import error.

When DGL ships proper macOS wheels (or on Linux/CUDA), the
``@pytest.mark.skipif`` block lights up and exercises the real wrapper.
"""

from __future__ import annotations

import importlib

import pytest


def _dgl_actually_works() -> bool:
    """Return True iff dgl (with graphbolt) is importable on this machine."""
    try:
        import dgl  # noqa: F401
        from dgl import graphbolt  # noqa: F401
        return True
    except (ImportError, FileNotFoundError):
        return False


DGL_OK = _dgl_actually_works()


def test_construction_raises_clean_runtimeerror_when_dgl_missing() -> None:
    """The guard in __init__ converts the underlying ImportError into a
    user-actionable RuntimeError naming chgnet as the alternative."""
    if DGL_OK:
        pytest.skip("DGL is importable on this machine; this test asserts the guard.")

    from crucible.relaxers.alignn_ff import AlignnFFRelaxer

    with pytest.raises(RuntimeError) as exc:
        AlignnFFRelaxer()
    msg = str(exc.value).lower()
    assert "alignn-ff" in msg or "alignn" in msg
    assert "chgnet" in msg


def test_registry_load_surfaces_the_runtimeerror_too() -> None:
    """The orchestrator's _dispatch catches Exception, so the loop survives;
    we just need the message to be informative."""
    if DGL_OK:
        pytest.skip("DGL is importable; not exercising the failure path.")

    from crucible.core.registry import load as registry_load

    with pytest.raises(RuntimeError):
        registry_load("relaxer", "alignn_ff")


@pytest.mark.skipif(not DGL_OK, reason="DGL/graphbolt not importable on this platform")
def test_real_relaxer_loads() -> None:
    from crucible.relaxers.alignn_ff import AlignnFFRelaxer

    relaxer = AlignnFFRelaxer()
    assert relaxer.name == "alignn_ff"
    assert relaxer.provenance.model_id == "alignn"
