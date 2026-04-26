"""Ranker for Li-ion battery cathodes.

Conforms to ``crucible.core.protocols.Ranker``. Hard gates and score
formula are spelled out in code rather than a config because that is the
playbook rule for target-specific scoring (no magic numbers buried in
helpers).

Hard gates (see :meth:`BatteryCathodeRanker.criteria`):

- ``lithium_fraction > 0`` — must host Li+. No Li, not a Li cathode.
- ``formation_energy_eV_per_atom < -1.0`` — must be thermodynamically
  stable enough to plausibly synthesize and survive cycling.
- ``0 <= bandgap_eV <= 1.5`` — semiconductor-ish; metallic = self-
  discharge, insulator = electrons cannot reach Li+ sites.

Score (higher is better; only meaningful when criteria() is True):

  score = stability_term + 0.5 * bandgap_term + 0.5 * lithium_term

where:

  stability_term = -formation_energy_eV_per_atom        # more negative -> bigger
  bandgap_term   = max(0, 1 - |bandgap_eV - 0.7|/0.7)   # peaks at 0.7 eV
  lithium_term   = lithium_fraction                     # already in [0, 1]

The weights are uncalibrated MVP defaults. Phase 2 can replace this with
a fitted model or multi-objective Pareto front per ARCHITECTURE.md §14.

The ``Ranker`` protocol passes only ``dict[str, float]``, so the
"contains Li" check is encoded as a float: ``props["lithium_fraction"]``,
the count of Li sites divided by total sites. Use the
:func:`lithium_fraction` helper to compute it from a Structure.
"""

from __future__ import annotations

from pymatgen.core import Element, Structure

from crucible.core.units import (
    BANDGAP_KEY,
    FORMATION_ENERGY_KEY,
)

# Hard gate thresholds. Documented at module level so a reader can see the
# numbers without descending into method bodies.
_FORMATION_ENERGY_MAX_EV_PER_ATOM = -1.0
_BANDGAP_MIN_EV = 0.0
_BANDGAP_MAX_EV = 1.5

# Score-shape parameters.
_BANDGAP_SWEET_SPOT_EV = 0.7
_BANDGAP_TOLERANCE_EV = 0.7  # half-width of the triangular kernel
_BANDGAP_WEIGHT = 0.5
_LITHIUM_WEIGHT = 0.5

# Property key for the lithium-fraction signal. Lives here (not in
# core/units) because it is a target-specific descriptor, not a unit.
LITHIUM_FRACTION_KEY = "lithium_fraction"


def lithium_fraction(structure: Structure) -> float:
    """Fraction of sites in ``structure`` occupied by Li.

    Returns 0.0 for empty or non-Li-containing structures, never raises.
    """
    n = len(structure)
    if n == 0:
        return 0.0
    li = Element("Li")
    li_count = sum(1 for site in structure if site.specie == li)
    return li_count / n


class BatteryCathodeRanker:
    """Hard-gate + scalar-score ranker for Li-ion cathode candidates."""

    name = "battery_cathode"
    target = "battery_cathode"

    def criteria(self, props: dict[str, float]) -> bool:
        """Pass/fail gate. False on missing-key, NaN, or out-of-range.

        Required keys in ``props``:

        - :data:`crucible.core.units.FORMATION_ENERGY_KEY`
        - :data:`crucible.core.units.BANDGAP_KEY`
        - :data:`LITHIUM_FRACTION_KEY`
        """
        e_form = props.get(FORMATION_ENERGY_KEY)
        bandgap = props.get(BANDGAP_KEY)
        li_frac = props.get(LITHIUM_FRACTION_KEY)

        if e_form is None or bandgap is None or li_frac is None:
            return False
        for v in (e_form, bandgap, li_frac):
            if not _is_finite(v):
                return False

        if li_frac <= 0:
            return False
        if e_form >= _FORMATION_ENERGY_MAX_EV_PER_ATOM:
            return False
        if not (_BANDGAP_MIN_EV <= bandgap <= _BANDGAP_MAX_EV):
            return False
        return True

    def score(self, props: dict[str, float]) -> float:
        """Higher is better. Result is meaningful only when criteria()
        returned True; calling it on a failing candidate is allowed but
        the value is not comparable to passing candidates' scores.
        """
        e_form = float(props.get(FORMATION_ENERGY_KEY, 0.0))
        bandgap = float(props.get(BANDGAP_KEY, 0.0))
        li_frac = float(props.get(LITHIUM_FRACTION_KEY, 0.0))

        stability_term = -e_form
        bandgap_term = max(
            0.0,
            1.0 - abs(bandgap - _BANDGAP_SWEET_SPOT_EV) / _BANDGAP_TOLERANCE_EV,
        )
        lithium_term = li_frac

        return stability_term + _BANDGAP_WEIGHT * bandgap_term + _LITHIUM_WEIGHT * lithium_term


def _is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
