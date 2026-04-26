"""Gauntlet stage 3 — geometric sanity.

Catches structures whose chemistry might pass but whose atom positions are
physically impossible: atoms occupying the same space, cells crushed too
small or blown up too large. Generators (CrystaLLM, MatterGen) emit these
at non-trivial rates because position sampling is statistical.

Two checks are applied (per ARCHITECTURE.md section 10):

1. **Min interatomic distance.** For every pair of sites, the
   periodic-image distance must be at least
   ``_MIN_DIST_FACTOR * (r_i + r_j)``, where ``r_i`` is the element's
   atomic radius (used as a covalent-radius proxy; pymatgen's
   ``Element.atomic_radius`` is the Slater-style bonding radius).
   ``_MIN_DIST_FACTOR = 0.7`` allows the slack metallic and ionic solids
   need without admitting overlapping atoms.

2. **Cell volume per atom.** Real condensed-matter solids sit in the
   ``5-100 angstrom^3 / atom`` band. Outside that, the cell is either
   crushed (overlapping electron clouds, unphysical pressure) or vacuum
   (atoms aren't bonded — not a solid).

Coordination-number sanity (``ARCHITECTURE.md`` mentions ``CN <= 16``) is
intentionally not implemented here: the Min-Distance check already rejects
the failure mode that would produce a high CN, and pymatgen's
``CrystalNN`` is flaky on the kinds of degenerate structures generators
produce. Add later if data shows it's needed.

Pure function. Never raises. Returns a structured ``GeometryResult``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymatgen.core import Element, Structure

# Required slack between actual interatomic distance and the sum of atomic
# radii. 0.7 was chosen in ARCHITECTURE.md section 10; it admits real ionic
# and metallic solids while rejecting hallucinated overlaps.
_MIN_DIST_FACTOR = 0.7

# Plausible cell volume per atom (angstrom^3 / atom). Lower bound rejects
# crushed cells; upper bound rejects vacuum-padded ones.
_VOLUME_PER_ATOM_MIN_A3 = 5.0
_VOLUME_PER_ATOM_MAX_A3 = 100.0

# Fallback atomic radius (angstrom) when pymatgen has none for an element.
# Conservative default; affects only obscure elements that BVA likely
# already rejected in stage 2.
_DEFAULT_RADIUS_A = 1.5


@dataclass(frozen=True, slots=True)
class GeometryResult:
    """Outcome of the geometry stage.

    Diagnostic fields are populated on success too, so the pipeline can
    log them for healthy structures (drift detection across runs).
    """

    min_distance_A: float | None
    volume_per_atom_A3: float | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None


def _radius(element: Element) -> float:
    r = element.atomic_radius
    if r is None:
        return _DEFAULT_RADIUS_A
    return float(r)


def check_geometry(structure: Structure) -> GeometryResult:
    """Verify min-distance and volume-per-atom sanity. Never raises."""
    n_sites = len(structure)
    if n_sites == 0:
        return GeometryResult(
            min_distance_A=None,
            volume_per_atom_A3=None,
            reason="empty structure",
        )

    # Volume sanity (cheap, do first).
    try:
        volume = float(structure.volume)
    except Exception as e:  # noqa: BLE001 - corrupt lattice -> reject
        return GeometryResult(
            min_distance_A=None,
            volume_per_atom_A3=None,
            reason=f"volume computation failed: {type(e).__name__}: {e}",
        )

    volume_per_atom = volume / n_sites
    if volume_per_atom < _VOLUME_PER_ATOM_MIN_A3:
        return GeometryResult(
            min_distance_A=None,
            volume_per_atom_A3=volume_per_atom,
            reason=(
                f"cell crushed: {volume_per_atom:.2f} A^3/atom "
                f"< min {_VOLUME_PER_ATOM_MIN_A3:.1f}"
            ),
        )
    if volume_per_atom > _VOLUME_PER_ATOM_MAX_A3:
        return GeometryResult(
            min_distance_A=None,
            volume_per_atom_A3=volume_per_atom,
            reason=(
                f"cell vacuum-padded: {volume_per_atom:.2f} A^3/atom "
                f"> max {_VOLUME_PER_ATOM_MAX_A3:.1f}"
            ),
        )

    # Min-distance check across all site pairs (with periodic images).
    try:
        dmat = np.asarray(structure.distance_matrix, dtype=float)
    except Exception as e:  # noqa: BLE001
        return GeometryResult(
            min_distance_A=None,
            volume_per_atom_A3=volume_per_atom,
            reason=f"distance computation failed: {type(e).__name__}: {e}",
        )

    radii = np.array(
        [_radius(site.specie.element if hasattr(site.specie, "element") else site.specie)
         for site in structure],
        dtype=float,
    )
    threshold_matrix = _MIN_DIST_FACTOR * (radii[:, None] + radii[None, :])

    # Mask the diagonal so a site's distance to itself doesn't count.
    np.fill_diagonal(dmat, np.inf)

    overall_min = float(dmat.min())

    # Find the worst (smallest distance / threshold) ratio across pairs.
    np.fill_diagonal(threshold_matrix, 1.0)  # avoid div-by-zero
    ratio = dmat / threshold_matrix
    worst_i, worst_j = np.unravel_index(np.argmin(ratio), ratio.shape)
    worst_dist = float(dmat[worst_i, worst_j])
    worst_threshold = float(threshold_matrix[worst_i, worst_j])

    if worst_dist < worst_threshold:
        sym_a = structure[int(worst_i)].specie.symbol
        sym_b = structure[int(worst_j)].specie.symbol
        return GeometryResult(
            min_distance_A=overall_min,
            volume_per_atom_A3=volume_per_atom,
            reason=(
                f"overlap: {sym_a}-{sym_b} {worst_dist:.3f} A "
                f"< {_MIN_DIST_FACTOR} * sum_radii ({worst_threshold:.3f} A)"
            ),
        )

    return GeometryResult(
        min_distance_A=overall_min,
        volume_per_atom_A3=volume_per_atom,
        reason=None,
    )
