"""Tests for crucible.gauntlet.geometry.

Goals:
- Real solids pass with sensible diagnostics.
- Atoms placed too close are rejected with a clear reason.
- Crushed and vacuum-padded cells are rejected.
- Empty structures are rejected, never raise.
"""

from __future__ import annotations

from pymatgen.core import Lattice, Structure

from crucible.gauntlet.geometry import GeometryResult, check_geometry


def _nacl_rocksalt() -> Structure:
    """NaCl rocksalt — well-spaced, normal volume per atom (~22 A^3)."""
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Na", "Na", "Na", "Cl", "Cl", "Cl", "Cl"],
        [
            [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
            [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
        ],
    )


def _overlapping() -> Structure:
    """Two atoms ~0.05 A apart in a normal-sized cell."""
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0, 0, 0], [0.01, 0, 0]],  # ~0.056 A apart
    )


def _crushed_cell() -> Structure:
    """Reasonable atom layout in an absurdly tiny cell."""
    return Structure(
        Lattice.cubic(1.5),  # 3.375 A^3 total -> 1.7 A^3/atom
        ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def _vacuum_padded_cell() -> Structure:
    """Two atoms in a giant box."""
    return Structure(
        Lattice.cubic(20.0),  # 8000 A^3 -> 4000 A^3/atom
        ["Na", "Cl"],
        [[0, 0, 0], [0.05, 0.05, 0.05]],
    )


# ----- happy path ----------------------------------------------------------


def test_rocksalt_passes() -> None:
    result = check_geometry(_nacl_rocksalt())
    assert isinstance(result, GeometryResult)
    assert result.ok
    assert result.reason is None
    assert result.min_distance_A is not None
    # NaCl nearest-neighbor is a/2 = 2.82 A
    assert 2.5 < result.min_distance_A < 3.0
    assert result.volume_per_atom_A3 is not None
    assert 5.0 < result.volume_per_atom_A3 < 100.0


# ----- rejection paths -----------------------------------------------------


def test_overlapping_atoms_rejected() -> None:
    result = check_geometry(_overlapping())
    assert not result.ok
    assert result.reason is not None
    assert "overlap" in result.reason.lower()
    assert result.min_distance_A is not None
    assert result.min_distance_A < 0.5  # actually ~0.056


def test_crushed_cell_rejected() -> None:
    result = check_geometry(_crushed_cell())
    assert not result.ok
    assert "crushed" in result.reason.lower()
    assert result.volume_per_atom_A3 is not None
    assert result.volume_per_atom_A3 < 5.0


def test_vacuum_cell_rejected() -> None:
    result = check_geometry(_vacuum_padded_cell())
    assert not result.ok
    assert "vacuum" in result.reason.lower() or "padded" in result.reason.lower()
    assert result.volume_per_atom_A3 is not None
    assert result.volume_per_atom_A3 > 100.0


# ----- diagnostics on success ---------------------------------------------


def test_diagnostics_populated_on_success() -> None:
    """min_distance_A and volume_per_atom_A3 must be set even when ok=True
    so the pipeline can log them."""
    result = check_geometry(_nacl_rocksalt())
    assert result.ok
    assert result.min_distance_A is not None
    assert result.volume_per_atom_A3 is not None


# ----- ergonomics ----------------------------------------------------------


def test_geometry_result_ok_property() -> None:
    good = GeometryResult(min_distance_A=2.8, volume_per_atom_A3=22.0, reason=None)
    bad = GeometryResult(min_distance_A=0.05, volume_per_atom_A3=22.0, reason="overlap")
    assert good.ok is True
    assert bad.ok is False
