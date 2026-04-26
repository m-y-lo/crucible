"""Tests for crucible.rankers.battery_cathode.

Coverage:
- Ranker protocol conformance (name, target, criteria, score).
- criteria() rejects missing keys, NaN, and each out-of-range threshold.
- criteria() accepts a realistic Li-cathode prop bundle.
- score() is monotonic in stability, lithium content, and bandgap-near-sweet-spot.
- lithium_fraction helper handles empty / no-Li / partial-Li structures.
"""

from __future__ import annotations

import math

import pytest
from pymatgen.core import Lattice, Structure

from crucible.core.units import BANDGAP_KEY, FORMATION_ENERGY_KEY
from crucible.rankers.battery_cathode import (
    LITHIUM_FRACTION_KEY,
    BatteryCathodeRanker,
    lithium_fraction,
)


def _good_props(**overrides: float) -> dict[str, float]:
    """A baseline prop bundle that comfortably passes all gates."""
    base = {
        FORMATION_ENERGY_KEY: -1.7,
        BANDGAP_KEY: 0.7,
        LITHIUM_FRACTION_KEY: 0.25,
    }
    base.update(overrides)
    return base


# ----- Ranker protocol attributes -----------------------------------------


def test_ranker_has_name_and_target() -> None:
    r = BatteryCathodeRanker()
    assert r.name == "battery_cathode"
    assert r.target == "battery_cathode"


# ----- criteria(): happy path --------------------------------------------


def test_realistic_cathode_passes_criteria() -> None:
    r = BatteryCathodeRanker()
    assert r.criteria(_good_props()) is True


# ----- criteria(): rejection paths ---------------------------------------


def test_missing_key_rejected() -> None:
    r = BatteryCathodeRanker()
    for missing_key in (FORMATION_ENERGY_KEY, BANDGAP_KEY, LITHIUM_FRACTION_KEY):
        props = _good_props()
        del props[missing_key]
        assert r.criteria(props) is False, f"missing {missing_key} should reject"


def test_nan_inf_rejected() -> None:
    r = BatteryCathodeRanker()
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert r.criteria(_good_props(**{FORMATION_ENERGY_KEY: bad})) is False
        assert r.criteria(_good_props(**{BANDGAP_KEY: bad})) is False
        assert r.criteria(_good_props(**{LITHIUM_FRACTION_KEY: bad})) is False


def test_no_lithium_rejected() -> None:
    r = BatteryCathodeRanker()
    assert r.criteria(_good_props(**{LITHIUM_FRACTION_KEY: 0.0})) is False


def test_unstable_formation_energy_rejected() -> None:
    r = BatteryCathodeRanker()
    # Above the -1.0 eV/atom gate -> rejected
    assert r.criteria(_good_props(**{FORMATION_ENERGY_KEY: -0.99})) is False
    assert r.criteria(_good_props(**{FORMATION_ENERGY_KEY: 0.5})) is False


def test_bandgap_too_high_rejected() -> None:
    r = BatteryCathodeRanker()
    assert r.criteria(_good_props(**{BANDGAP_KEY: 1.51})) is False
    assert r.criteria(_good_props(**{BANDGAP_KEY: 5.0})) is False


def test_bandgap_negative_rejected() -> None:
    r = BatteryCathodeRanker()
    assert r.criteria(_good_props(**{BANDGAP_KEY: -0.1})) is False


# ----- score() monotonicity ----------------------------------------------


def test_score_increases_with_stability() -> None:
    """More-negative formation energy must produce a larger score."""
    r = BatteryCathodeRanker()
    less_stable = r.score(_good_props(**{FORMATION_ENERGY_KEY: -1.1}))
    more_stable = r.score(_good_props(**{FORMATION_ENERGY_KEY: -2.5}))
    assert more_stable > less_stable


def test_score_increases_with_lithium_content() -> None:
    r = BatteryCathodeRanker()
    little_li = r.score(_good_props(**{LITHIUM_FRACTION_KEY: 0.1}))
    lots_of_li = r.score(_good_props(**{LITHIUM_FRACTION_KEY: 0.5}))
    assert lots_of_li > little_li


def test_score_peaks_near_bandgap_sweet_spot() -> None:
    r = BatteryCathodeRanker()
    sweet = r.score(_good_props(**{BANDGAP_KEY: 0.7}))
    too_low = r.score(_good_props(**{BANDGAP_KEY: 0.0}))
    too_high = r.score(_good_props(**{BANDGAP_KEY: 1.4}))
    assert sweet > too_low
    assert sweet > too_high


def test_score_finite_on_extreme_inputs() -> None:
    r = BatteryCathodeRanker()
    s = r.score(_good_props(**{FORMATION_ENERGY_KEY: -1000.0}))
    assert math.isfinite(s)


# ----- lithium_fraction helper -------------------------------------------


def test_lithium_fraction_empty_structure_returns_zero() -> None:
    s = Structure(Lattice.cubic(3.0), [], [])
    assert lithium_fraction(s) == 0.0


def test_lithium_fraction_no_li() -> None:
    s = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    assert lithium_fraction(s) == 0.0


def test_lithium_fraction_partial_li() -> None:
    # Li2MnO3-style 1:1:3 from a generic 4-atom cell with 1 Li, 1 Mn, 2 O.
    s = Structure(
        Lattice.cubic(5.0),
        ["Li", "Mn", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.25, 0.25, 0.25], [0.75, 0.75, 0.75]],
    )
    assert lithium_fraction(s) == pytest.approx(0.25)


def test_lithium_fraction_pure_lithium() -> None:
    s = Structure(Lattice.cubic(3.5), ["Li", "Li"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    assert lithium_fraction(s) == 1.0
