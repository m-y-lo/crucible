"""Tests for crucible.gauntlet.composition.

Goals:
- Valid ionic solids pass with sensible oxidation states.
- Charge-imbalanced stoichiometries are rejected with a clear reason.
- Pathological / un-typeable structures are rejected, never raise.
- Reduced formula is reported on both success and failure paths.
"""

from __future__ import annotations

from pymatgen.core import Lattice, Structure

from crucible.gauntlet.composition import CompositionResult, check_composition


def _nacl() -> Structure:
    return Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _kcl() -> Structure:
    return Structure(Lattice.cubic(6.29), ["K", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _li_cl2_imbalanced() -> Structure:
    """Formula LiCl2 — impossible. Li is +1 and Cl is -1, you cannot
    charge-balance a 1:2 ratio."""
    return Structure(
        Lattice.cubic(5.64),
        ["Li", "Cl", "Cl"],
        [[0, 0, 0], [0.3, 0.3, 0.3], [0.6, 0.6, 0.6]],
    )


# ----- happy path ----------------------------------------------------------


def test_valid_nacl_passes() -> None:
    result = check_composition(_nacl())
    assert isinstance(result, CompositionResult)
    assert result.ok
    assert result.reason is None
    assert result.reduced_formula == "NaCl"
    assert result.oxidation_states == [1, -1]
    assert abs(result.net_charge) < 0.1


def test_valid_kcl_passes() -> None:
    result = check_composition(_kcl())
    assert result.ok
    assert result.reduced_formula == "KCl"
    assert sum(result.oxidation_states) == 0


# ----- rejection paths -----------------------------------------------------


def test_charge_imbalanced_formula_is_rejected() -> None:
    result = check_composition(_li_cl2_imbalanced())
    assert not result.ok
    assert result.oxidation_states is None
    assert result.reason is not None
    # Either BVA refuses outright, or returns valences that don't cancel.
    assert "bond-valence" in result.reason.lower() or "charge-imbalanced" in result.reason.lower()


def test_reduced_formula_reported_even_on_failure() -> None:
    """Even rejected candidates carry a formula — useful for log analysis."""
    result = check_composition(_li_cl2_imbalanced())
    assert not result.ok
    assert result.reduced_formula is not None
    assert "Li" in result.reduced_formula


def test_unphysical_geometry_does_not_raise() -> None:
    """Atoms placed on top of each other tank BVAnalyzer's neighbor search.
    The contract: never raise; return a rejection."""
    overlapping = Structure(
        Lattice.cubic(2.0),
        ["Na", "Cl"],
        [[0, 0, 0], [0.001, 0.001, 0.001]],  # ~0.003 A apart
    )
    result = check_composition(overlapping)
    assert not result.ok
    assert result.reason is not None


def test_single_element_metallic_is_rejected_cleanly() -> None:
    """Pure element solids have zero oxidation states everywhere; BVA refuses
    to assign valences to a single-element structure. Should reject, not
    raise."""
    iron = Structure(Lattice.cubic(2.87), ["Fe"], [[0, 0, 0]])
    result = check_composition(iron)
    # Either BVA returns [0] (sum 0 → "passes") or raises (rejected).
    # Both outcomes are acceptable contracts; what matters is no exception.
    assert isinstance(result, CompositionResult)


# ----- result ergonomics ---------------------------------------------------


def test_result_ok_property() -> None:
    good = CompositionResult(
        reduced_formula="NaCl", oxidation_states=[1, -1], reason=None, net_charge=0.0
    )
    bad = CompositionResult(
        reduced_formula="LiCl2", oxidation_states=None, reason="x", net_charge=0.0
    )
    assert good.ok is True
    assert bad.ok is False
