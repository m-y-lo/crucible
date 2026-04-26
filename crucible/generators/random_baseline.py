"""Random-baseline ``Generator`` — perturbs a known structure.

The first concrete ``crucible.core.protocols.Generator`` plugin. Takes a
seed structure (default: NaCl rocksalt) and applies a small random
displacement to each atom to produce ``n`` "novel-looking" CIF strings.

Why bother:
- Lets us run the full pipeline end-to-end before CrystaLLM is wired in.
- Provides a control group for evaluation: if a learned generator does
  not beat random rattling on quality metrics, it has not earned its
  complexity.
- Each output is structurally close to the seed but has a distinct
  ``structure_hash``, which exercises the dedup stage.

The displacement is sampled per atom from an isotropic distribution and
rescaled to exactly ``rattle_distance_A`` magnitude. Reproducible when
``rng_seed`` is set.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

# Built-in seed structure used when the caller provides nothing else:
# NaCl rocksalt as the 8-atom conventional cubic cell. Well-known,
# charge-balanced, passes the gauntlet.
_DEFAULT_SEED_LATTICE_A = 5.64
_DEFAULT_SEED_ELEMENTS = ["Na", "Na", "Na", "Na", "Cl", "Cl", "Cl", "Cl"]
_DEFAULT_SEED_FRAC_COORDS = [
    [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
    [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
]


def _default_seed_structure() -> Structure:
    return Structure(
        Lattice.cubic(_DEFAULT_SEED_LATTICE_A),
        _DEFAULT_SEED_ELEMENTS,
        _DEFAULT_SEED_FRAC_COORDS,
    )


def _structure_to_cif(s: Structure) -> str:
    return str(CifWriter(s))


def _cif_to_structure(cif: str) -> Structure:
    return Structure.from_str(cif, fmt="cif")


class RandomBaselineGenerator:
    """Rattles a seed structure and emits the result as CIF text.

    Conforms to the ``Generator`` protocol from ``crucible.core.protocols``.
    Registered via ``pyproject.toml`` entry point ``random_baseline``;
    construct via ``registry.load("generator", "random_baseline")``.
    """

    name = "random_baseline"

    def __init__(
        self,
        seed_cif: str | None = None,
        rattle_distance_A: float = 0.1,
        rng_seed: int | None = None,
    ) -> None:
        if rattle_distance_A < 0:
            raise ValueError(f"rattle_distance_A must be >= 0, got {rattle_distance_A}")
        self._rattle_distance = float(rattle_distance_A)
        self._rng = np.random.default_rng(rng_seed)
        self._default_seed_cif = (
            seed_cif if seed_cif is not None else _structure_to_cif(_default_seed_structure())
        )

    def _seed_pool(self, conditions: dict | None) -> list[Structure]:
        """Collect every seed structure available for this call.

        Order of precedence:
          1. ``conditions["seed_structures"]`` — list of CIF strings.
          2. ``conditions["seed_cif"]`` — single CIF string.
          3. The instance's default seed (built-in NaCl unless overridden).
        """
        if conditions:
            cifs = conditions.get("seed_structures") or [conditions.get("seed_cif")]
            cifs = [c for c in cifs if c]
            if cifs:
                return [_cif_to_structure(c) for c in cifs]
        return [_cif_to_structure(self._default_seed_cif)]

    def _rattle(self, structure: Structure) -> Structure:
        """Return a copy of ``structure`` with each atom displaced by a
        random unit vector scaled to ``self._rattle_distance``.

        ``Structure.perturb`` uses pymatgen's global ``np.random`` state,
        which makes per-instance seeding finicky. We do the math directly
        against our own ``self._rng`` so reproducibility holds.
        """
        if self._rattle_distance == 0.0:
            return structure.copy()

        rattled = structure.copy()
        n = len(rattled)
        # Sample displacement directions from an isotropic Gaussian, then
        # rescale each row to length == rattle_distance.
        directions = self._rng.normal(0.0, 1.0, size=(n, 3))
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0  # avoid div-by-zero on (vanishingly rare) zero vector
        displacements_cart = directions / norms * self._rattle_distance

        # Convert displacements (Angstrom) to fractional coords for the cell.
        displacements_frac = rattled.lattice.get_fractional_coords(displacements_cart)
        new_frac_coords = rattled.frac_coords + displacements_frac

        return Structure(
            rattled.lattice,
            rattled.species,
            new_frac_coords,
            coords_are_cartesian=False,
        )

    def sample(self, n: int, conditions: dict | None = None) -> list[str]:
        """Return ``n`` rattled CIF strings.

        ``conditions`` is the standard ``Generator`` argument. Recognized
        keys: ``seed_structures`` (list of CIFs), ``seed_cif`` (single CIF).
        Any other keys are ignored.
        """
        if n <= 0:
            return []

        seeds = self._seed_pool(conditions)
        out: list[str] = []
        for i in range(n):
            seed = seeds[i % len(seeds)]
            out.append(_structure_to_cif(self._rattle(seed)))
        return out
