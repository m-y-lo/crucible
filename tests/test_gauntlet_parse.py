"""Tests for crucible.gauntlet.parse.

The contract is "never raise; always return a ParseResult." Tests cover
each rejection reason path plus a happy-path round trip.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.gauntlet.parse import ParseResult, try_parse


def _valid_nacl_cif() -> str:
    s = Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    return str(CifWriter(s))


# ----- happy path ----------------------------------------------------------


def test_valid_cif_parses_successfully() -> None:
    result = try_parse(_valid_nacl_cif())
    assert isinstance(result, ParseResult)
    assert result.ok
    assert result.reason is None
    assert result.structure is not None
    assert len(result.structure) == 2
    assert result.structure.composition.reduced_formula == "NaCl"


# ----- rejection paths -----------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   \n\t  ", "\n"])
def test_empty_cif_is_rejected(bad: str) -> None:
    result = try_parse(bad)
    assert not result.ok
    assert result.structure is None
    assert "empty" in result.reason.lower()


def test_oversized_cif_is_rejected_without_parsing() -> None:
    huge = "data_x\n" + ("# " + "x" * 80 + "\n") * 20_000  # >1 MB
    result = try_parse(huge)
    assert not result.ok
    assert "too large" in result.reason.lower()


def test_garbage_text_is_rejected() -> None:
    result = try_parse("this is definitely not a CIF file at all")
    assert not result.ok
    assert "parse error" in result.reason.lower() or "empty" in result.reason.lower()


def test_truncated_cif_is_rejected() -> None:
    """A CIF chopped mid-loop must not crash the parser."""
    truncated = """data_x
_cell_length_a 5.64
_cell_length_b 5.64
_cell_length_c 5.64
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
Na1 0.0 0.0
"""
    result = try_parse(truncated)
    assert not result.ok
    assert result.reason  # something was reported


def test_invalid_numerics_are_rejected() -> None:
    bad = """data_x
_cell_length_a NOT_A_NUMBER
_cell_length_b 5.64
_cell_length_c 5.64
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
"""
    result = try_parse(bad)
    assert not result.ok


def test_try_parse_never_raises_on_arbitrary_input() -> None:
    """Property-style check: a pile of weird inputs must each return a
    ParseResult, never an exception."""
    weird_inputs = [
        "\x00\x01\x02",
        "data_\n" * 100,
        "💎🔬⚗️",
        "{'json': 'not cif'}",
        "<xml>still not cif</xml>",
    ]
    for inp in weird_inputs:
        result = try_parse(inp)
        assert isinstance(result, ParseResult)
        assert not result.ok or result.structure is not None  # tautology, but proves no raise


# ----- ParseResult ergonomics ---------------------------------------------


def test_parse_result_ok_property() -> None:
    good = ParseResult(structure=Structure(Lattice.cubic(3), ["H"], [[0, 0, 0]]), reason=None)
    bad = ParseResult(structure=None, reason="x")
    assert good.ok is True
    assert bad.ok is False
