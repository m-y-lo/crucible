"""Tests for crucible.core.hashing.

The hash and prototype label must be invariant to representation choices
that do not change the underlying crystal: cell choice (primitive vs
conventional), atom ordering, lattice scale within a tolerance band, and
small floating-point noise. They must differ for genuinely different
crystals.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.core import hashing


def _cif(structure: Structure) -> str:
    return str(CifWriter(structure))


def _nacl_conventional() -> Structure:
    """NaCl rocksalt as the 8-atom conventional cubic cell (Fm-3m, 225)."""
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Na", "Na", "Na", "Cl", "Cl", "Cl", "Cl"],
        [
            [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
            [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
        ],
    )


def _kcl_conventional() -> Structure:
    """KCl rocksalt — same prototype as NaCl, different elements."""
    return Structure(
        Lattice.cubic(6.29),
        ["K", "K", "K", "K", "Cl", "Cl", "Cl", "Cl"],
        [
            [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
            [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
        ],
    )


def _cscl_primitive() -> Structure:
    """CsCl-type — distinct prototype from NaCl (Pm-3m vs Fm-3m)."""
    return Structure(
        Lattice.cubic(4.12),
        ["Cs", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


# --------------------------------------------------------------------------
# structure_hash
# --------------------------------------------------------------------------


def test_hash_is_hex_sha256() -> None:
    h = hashing.structure_hash(_cif(_nacl_conventional()))
    assert len(h) == 64
    int(h, 16)  # must be hex


def test_hash_invariant_to_atom_ordering() -> None:
    """Same crystal, atoms listed in shuffled order -> same hash."""
    s1 = _nacl_conventional()
    s2 = Structure(
        s1.lattice,
        list(reversed(s1.species)),
        list(reversed(s1.frac_coords)),
    )
    assert hashing.structure_hash(_cif(s1)) == hashing.structure_hash(_cif(s2))


def test_hash_distinguishes_different_compositions() -> None:
    nacl = hashing.structure_hash(_cif(_nacl_conventional()))
    kcl = hashing.structure_hash(_cif(_kcl_conventional()))
    assert nacl != kcl


def test_hash_distinguishes_different_prototypes() -> None:
    """NaCl (rocksalt, sg 225) and CsCl (sg 221) are not the same crystal."""
    assert hashing.structure_hash(_cif(_nacl_conventional())) != hashing.structure_hash(
        _cif(_cscl_primitive())
    )


# --------------------------------------------------------------------------
# prototype_label
# --------------------------------------------------------------------------


def test_prototype_label_format() -> None:
    label = hashing.prototype_label(_cif(_nacl_conventional()))
    parts = label.split("_")
    assert len(parts) == 4
    stoich, pearson, sg_num_str, wyckoff = parts
    assert stoich == "AB"
    assert sg_num_str == "225"
    assert pearson.startswith("c")  # cubic
    assert wyckoff  # non-empty
    assert wyckoff == "".join(sorted(wyckoff))  # sorted letters


def test_prototype_label_shared_across_same_prototype() -> None:
    """NaCl and KCl are both rocksalts -> same prototype label."""
    nacl = hashing.prototype_label(_cif(_nacl_conventional()))
    kcl = hashing.prototype_label(_cif(_kcl_conventional()))
    assert nacl == kcl


def test_prototype_label_differs_across_prototypes() -> None:
    nacl = hashing.prototype_label(_cif(_nacl_conventional()))
    cscl = hashing.prototype_label(_cif(_cscl_primitive()))
    assert nacl != cscl


# --------------------------------------------------------------------------
# stoichiometry edge cases
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "elements, expected_prefix",
    [
        (["Na", "Cl"], "AB"),               # 1:1 binary
        (["Cs", "Cl"], "AB"),
        (["Fe", "Fe", "O", "O", "O"], "A3B2"),  # 3:2, sorted desc by count
    ],
)
def test_stoichiometry_label_shape(elements: list[str], expected_prefix: str) -> None:
    """The first segment of the prototype label is anonymized stoichiometry."""
    s = Structure(
        Lattice.cubic(5.0),
        elements,
        [[i / len(elements), 0, 0] for i in range(len(elements))],
        coords_are_cartesian=False,
    )
    label = hashing.prototype_label(_cif(s))
    assert label.split("_")[0] == expected_prefix


# --------------------------------------------------------------------------
# Structure-input variants (used by the gauntlet pipeline to skip CIF
# round-trip).
# --------------------------------------------------------------------------


def test_hash_structure_matches_cif_wrapper() -> None:
    s = _nacl_conventional()
    via_cif = hashing.structure_hash(_cif(s))
    direct = hashing.hash_structure(s)
    assert via_cif == direct


def test_prototype_label_of_matches_cif_wrapper() -> None:
    s = _nacl_conventional()
    via_cif = hashing.prototype_label(_cif(s))
    direct = hashing.prototype_label_of(s)
    assert via_cif == direct
