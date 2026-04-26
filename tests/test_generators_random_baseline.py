"""Tests for crucible.generators.random_baseline.

Coverage:
- Generator-protocol conformance (`name`, `sample`).
- Output count matches ``n``; each output parses as CIF.
- Rattled output is *near* the seed but not identical.
- Reproducibility with ``rng_seed`` set.
- ``conditions["seed_structures"]`` overrides the built-in seed.
- Rattle distance == 0 returns the seed unchanged.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.generators.random_baseline import RandomBaselineGenerator


def _kcl_cif() -> str:
    s = Structure(Lattice.cubic(6.29), ["K", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    return str(CifWriter(s))


# ----- protocol conformance -----------------------------------------------


def test_generator_has_name_attribute() -> None:
    g = RandomBaselineGenerator()
    assert g.name == "random_baseline"


def test_sample_returns_list_of_strings() -> None:
    g = RandomBaselineGenerator(rng_seed=0)
    out = g.sample(3)
    assert isinstance(out, list)
    assert len(out) == 3
    assert all(isinstance(c, str) for c in out)


def test_zero_n_returns_empty() -> None:
    g = RandomBaselineGenerator(rng_seed=0)
    assert g.sample(0) == []


# ----- output is valid CIF that parses ------------------------------------


def test_each_output_parses_as_cif() -> None:
    g = RandomBaselineGenerator(rng_seed=0)
    for cif in g.sample(5):
        parsed = Structure.from_str(cif, fmt="cif")
        assert len(parsed) == 8  # default NaCl is 8 atoms
        assert parsed.composition.reduced_formula == "NaCl"


# ----- rattle behavior ----------------------------------------------------


def test_rattled_output_differs_from_seed() -> None:
    """With a non-zero rattle distance, output frac_coords drift from the
    pristine seed."""
    g = RandomBaselineGenerator(rattle_distance_A=0.1, rng_seed=42)
    cif = g.sample(1)[0]
    out = Structure.from_str(cif, fmt="cif")

    seed_coords = np.array(
        [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
         [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]]
    )
    out_coords = np.array(out.frac_coords) % 1.0
    seed_coords = seed_coords % 1.0

    # At least one coordinate has moved (per-axis tolerance accounts for
    # CIF round-trip's finite precision).
    deltas = np.abs(out_coords - seed_coords)
    assert np.max(deltas) > 1e-3


def test_rattle_distance_zero_returns_seed_unchanged() -> None:
    g = RandomBaselineGenerator(rattle_distance_A=0.0, rng_seed=0)
    cif = g.sample(1)[0]
    out = Structure.from_str(cif, fmt="cif")
    assert out.composition.reduced_formula == "NaCl"
    # No site has moved beyond CIF round-trip noise.
    seed_frac = [
        [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
        [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
    ]
    out_sorted = sorted([tuple(round(x, 6) for x in s.frac_coords) for s in out])
    seed_sorted = sorted([tuple(round(x, 6) for x in c) for c in seed_frac])
    assert out_sorted == seed_sorted


def test_rattle_magnitude_matches_request() -> None:
    """Each atom should be displaced by ~rattle_distance Angstrom from
    its pristine seed position."""
    rattle_A = 0.2
    g = RandomBaselineGenerator(rattle_distance_A=rattle_A, rng_seed=7)
    cif = g.sample(1)[0]
    out = Structure.from_str(cif, fmt="cif")

    # Compare each atom's Cartesian displacement from the matching seed
    # site (matching by element + initial fractional position).
    seed = Structure(
        Lattice.cubic(5.64),
        ["Na", "Na", "Na", "Na", "Cl", "Cl", "Cl", "Cl"],
        [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
         [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
    )
    # Sites may have been reordered by CIF write/read; find each atom's
    # nearest seed-site partner. CartCoords subtraction respects PBC.
    for site in out:
        nearest_dist = min(
            site.distance(seed_site) for seed_site in seed if seed_site.specie == site.specie
        )
        # Allow ±20% tolerance: CIF round-trip rounds to ~6 decimals
        # and pymatgen's frac<->cart conversion is sometimes off by a
        # few times 1e-3 A.
        assert math.isclose(nearest_dist, rattle_A, abs_tol=rattle_A * 0.2 + 0.01)


# ----- reproducibility ----------------------------------------------------


def test_same_seed_produces_same_output() -> None:
    g1 = RandomBaselineGenerator(rng_seed=123)
    g2 = RandomBaselineGenerator(rng_seed=123)
    assert g1.sample(3) == g2.sample(3)


def test_different_seeds_produce_different_output() -> None:
    g1 = RandomBaselineGenerator(rng_seed=1)
    g2 = RandomBaselineGenerator(rng_seed=2)
    assert g1.sample(3) != g2.sample(3)


# ----- conditions overrides ----------------------------------------------


def test_conditions_seed_structures_overrides_default() -> None:
    g = RandomBaselineGenerator(rng_seed=0)
    out = g.sample(2, conditions={"seed_structures": [_kcl_cif()]})
    for cif in out:
        parsed = Structure.from_str(cif, fmt="cif")
        assert parsed.composition.reduced_formula == "KCl"


def test_conditions_seed_cif_singular_form_works() -> None:
    g = RandomBaselineGenerator(rng_seed=0)
    out = g.sample(1, conditions={"seed_cif": _kcl_cif()})
    parsed = Structure.from_str(out[0], fmt="cif")
    assert parsed.composition.reduced_formula == "KCl"


# ----- input validation ---------------------------------------------------


def test_negative_rattle_distance_rejected() -> None:
    with pytest.raises(ValueError):
        RandomBaselineGenerator(rattle_distance_A=-0.1)
