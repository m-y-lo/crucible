"""Tests for crucible.core.units.

Tiny module, tiny tests. Goals:
- Constants are the exact strings other modules will key on.
- Converters round-trip and reject zero/negative atom counts.
"""

from __future__ import annotations

import pytest

from crucible.core import units


def test_unit_string_constants() -> None:
    assert units.EV == "eV"
    assert units.EV_PER_ATOM == "eV/atom"
    assert units.MEV_PER_ATOM == "meV/atom"
    assert units.GPA == "GPa"
    assert units.KJ_PER_MOL == "kJ/mol"


def test_canonical_property_keys() -> None:
    assert units.FORMATION_ENERGY_KEY == "formation_energy_eV_per_atom"
    assert units.BANDGAP_KEY == "bandgap_eV"
    assert units.BULK_MODULUS_KEY == "bulk_modulus_GPa"
    assert units.SHEAR_MODULUS_KEY == "shear_modulus_GPa"
    assert units.TOTAL_ENERGY_KEY == "total_energy_eV"


def test_ev_kj_per_mol_round_trip() -> None:
    assert units.ev_to_kj_per_mol(1.0) == pytest.approx(96.485, rel=1e-4)
    # round-trip
    assert units.kj_per_mol_to_ev(units.ev_to_kj_per_mol(2.5)) == pytest.approx(2.5)


def test_ev_mev_round_trip() -> None:
    assert units.ev_to_mev(1.0) == 1000.0
    assert units.mev_to_ev(1000.0) == 1.0
    assert units.mev_to_ev(units.ev_to_mev(0.123)) == pytest.approx(0.123)


def test_per_atom_total_round_trip() -> None:
    # an 8-atom cell at -1.5 eV/atom totals -12.0 eV
    assert units.per_atom_to_total(-1.5, 8) == pytest.approx(-12.0)
    assert units.total_to_per_atom(-12.0, 8) == pytest.approx(-1.5)


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_per_atom_converters_reject_nonpositive_atoms(bad: int) -> None:
    with pytest.raises(ValueError):
        units.per_atom_to_total(1.0, bad)
    with pytest.raises(ValueError):
        units.total_to_per_atom(1.0, bad)
