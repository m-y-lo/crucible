"""Gauntlet stage 2 — composition and charge-balance sanity.

Runs after ``parse``. Takes a parsed ``pymatgen.Structure`` and asks: is
the chemistry physically possible? CrystaLLM-style generators happily emit
formulas like ``LiCl2`` or ``Fe2O5`` that cannot exist as charge-neutral
solids. ``BVAnalyzer`` (Bond Valence Analysis) infers per-site oxidation
states from bonded-neighbor distances and returns a self-consistent
charge-neutral assignment, or raises ``ValueError`` if no such assignment
exists.

Charge balance is therefore *implicit* in BVAnalyzer succeeding — when
``get_valences()`` returns, the sum of (valence x site count) is
guaranteed to be zero. We still verify the sum is within
``_CHARGE_TOLERANCE`` of zero as paranoia against future API drift.

Pure function, never raises. Returns a structured ``CompositionResult``
the gauntlet pipeline writes into ``gauntlet_events``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pymatgen.core import Structure
from pymatgen.core.bond_valence import BVAnalyzer

# Numerical wiggle room when checking that summed valences cancel. BVA
# returns integers, so this only catches future floating-point drift.
_CHARGE_TOLERANCE = 0.1


@dataclass(frozen=True, slots=True)
class CompositionResult:
    """Outcome of the composition stage.

    On success: ``reduced_formula`` and ``oxidation_states`` are set,
    ``reason`` is None.
    On failure: ``reduced_formula`` may still be set (computing it can't
    fail on a parsed Structure), ``oxidation_states`` is None,
    ``reason`` is a short human-readable string.
    """

    reduced_formula: str | None
    oxidation_states: list[int] | None
    reason: str | None = None
    net_charge: float = field(default=0.0)

    @property
    def ok(self) -> bool:
        return self.oxidation_states is not None and self.reason is None


def check_composition(structure: Structure) -> CompositionResult:
    """Validate composition and charge balance for a parsed Structure.

    Returns a ``CompositionResult``. Never raises. Rejection reasons:

    - BVAnalyzer cannot assign self-consistent oxidation states
      (charge-imbalanced formula, broken geometry, or species outside
      the BVA reference table)
    - The implied net charge is not within tolerance of zero
    """
    reduced_formula = structure.composition.reduced_formula

    try:
        valences = BVAnalyzer().get_valences(structure)
    except ValueError as e:
        return CompositionResult(
            reduced_formula=reduced_formula,
            oxidation_states=None,
            reason=f"bond-valence assignment failed: {e}",
        )
    except Exception as e:  # noqa: BLE001 - any other failure rejects this candidate
        return CompositionResult(
            reduced_formula=reduced_formula,
            oxidation_states=None,
            reason=f"unexpected BVAnalyzer error: {type(e).__name__}: {e}",
        )

    net_charge = float(sum(valences))
    if abs(net_charge) > _CHARGE_TOLERANCE:
        return CompositionResult(
            reduced_formula=reduced_formula,
            oxidation_states=None,
            reason=f"charge-imbalanced: net charge {net_charge:+.3f}",
            net_charge=net_charge,
        )

    return CompositionResult(
        reduced_formula=reduced_formula,
        oxidation_states=list(valences),
        reason=None,
        net_charge=net_charge,
    )
