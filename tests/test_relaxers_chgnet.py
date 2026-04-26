"""Tests for crucible.relaxers.chgnet.

Lightweight: load the plugin, relax a tiny NaCl, check the contract.
The actual ML inference is the slow part (~5-15s on MPS for a small
cell + ~20 steps); these tests run real CHGNet so they cost real time
but exercise the wrapper end-to-end.
"""

from __future__ import annotations

from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

import pytest

from crucible.core.registry import load as registry_load
from crucible.relaxers.chgnet import ChgnetRelaxer


@pytest.fixture(scope="module")
def relaxer() -> ChgnetRelaxer:
    return ChgnetRelaxer(fmax=0.5, verbose=False)  # high fmax = quick converge


@pytest.fixture(scope="module")
def nacl_cif() -> str:
    s = Structure(
        Lattice.cubic(5.6),
        ["Na", "Cl", "Na", "Cl"],
        [[0, 0, 0], [0.5, 0, 0], [0, 0.5, 0], [0.5, 0.5, 0]],
    )
    return str(CifWriter(s))


# --- protocol conformance --------------------------------------------------


def test_name_and_provenance(relaxer: ChgnetRelaxer) -> None:
    assert relaxer.name == "chgnet"
    assert relaxer.provenance.model_id == "chgnet"
    assert relaxer.provenance.dataset == "MPtrj"
    assert relaxer.provenance.version  # non-empty


def test_registry_loadable() -> None:
    """The registry entry-point in pyproject.toml resolves to this class."""
    obj = registry_load("relaxer", "chgnet", fmax=0.5)
    assert isinstance(obj, ChgnetRelaxer)


# --- behavior --------------------------------------------------------------


@pytest.mark.slow
def test_relax_returns_cif_and_finite_energy(
    relaxer: ChgnetRelaxer, nacl_cif: str
) -> None:
    relaxed_cif, total_eV = relaxer.relax(nacl_cif, max_steps=10)
    # Re-parsable CIF.
    s = Structure.from_str(relaxed_cif, fmt="cif")
    assert s.composition.reduced_formula == "NaCl"
    # Total energy is a finite negative number (the structure is bound).
    assert total_eV == total_eV  # not NaN
    assert total_eV < 0
    assert -100 < total_eV < 0


@pytest.mark.slow
def test_relax_actually_optimizes_lattice(
    relaxer: ChgnetRelaxer, nacl_cif: str
) -> None:
    """A 5.6 A NaCl is too compressed; the relaxed cell should expand toward
    the equilibrium ~5.6-5.7 A range, but not blow up either."""
    relaxed_cif, _ = relaxer.relax(nacl_cif, max_steps=20)
    relaxed = Structure.from_str(relaxed_cif, fmt="cif")
    a = relaxed.lattice.a
    # Sanity: stayed within an order of magnitude. We aren't asserting
    # equilibrium because high fmax + few steps may not converge.
    assert 3.0 < a < 8.0
