"""End-to-end smoke run for Crucible's offline pipeline.

Runs every Phase 1 plugin Ani's track shipped, in sequence, against a
Li-bearing seed. Fakes the ALIGNN predictions (no GPU / ML deps needed)
so the loop can complete on any machine. Demonstrates that:

  generator -> gauntlet -> [fake predictor] -> ranker -> leaderboard

composes correctly.

Usage:
  uv run python scripts/smoke_run.py
  uv run python scripts/smoke_run.py --n 20 --seed 7

Exits 0 on success, prints a leaderboard via rich. Imported by
``tests/test_smoke_run.py`` for CI.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make 'crucible' importable when running this file directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pymatgen.core import Lattice, Structure  # noqa: E402
from pymatgen.io.cif import CifWriter  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from crucible.core.registry import load as registry_load  # noqa: E402
from crucible.core.units import BANDGAP_KEY, FORMATION_ENERGY_KEY  # noqa: E402
from crucible.gauntlet.dedup import Deduplicator  # noqa: E402
from crucible.gauntlet.pipeline import run_gauntlet  # noqa: E402
from crucible.rankers.battery_cathode import (  # noqa: E402
    LITHIUM_FRACTION_KEY,
    lithium_fraction,
)


# ---------------------------------------------------------------------------
# Seed structure: 8-atom Li-Cl rocksalt analogue (Li sits where Na would in
# NaCl). Real Li-Cl is rocksalt; we use it as a Li-bearing seed so rattled
# variants have lithium_fraction = 0.5 and can pass the cathode ranker's
# contains-Li gate.
# ---------------------------------------------------------------------------


def _seed_cif() -> str:
    s = Structure(
        Lattice.cubic(5.13),
        ["Li", "Li", "Li", "Li", "Cl", "Cl", "Cl", "Cl"],
        [
            [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
            [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
        ],
    )
    return str(CifWriter(s))


@dataclass
class SmokeResult:
    """Summary returned by ``main`` for tests / diagnostics."""

    requested: int
    survivors: int
    rejected_counts: dict[str, int]
    passing: int
    rows: list[dict[str, Any]]


def _fake_predictions(rng: random.Random) -> dict[str, float]:
    """Plausible ALIGNN-style outputs. ~70% pass the formation-energy gate
    (-1.0 eV/atom) and ~75% pass the bandgap range, so a typical
    10-candidate run produces a few passing rows."""
    return {
        FORMATION_ENERGY_KEY: rng.uniform(-2.5, -0.5),
        BANDGAP_KEY: rng.uniform(0.0, 2.0),
    }


def _render_leaderboard(rows: list[dict[str, Any]]) -> Table:
    table = Table(title="Smoke run — top candidates")
    table.add_column("rank", justify="right")
    table.add_column("score", justify="right")
    table.add_column("formula")
    table.add_column("hash_prefix")
    table.add_column("E_form (eV/atom)", justify="right")
    table.add_column("bandgap (eV)", justify="right")
    table.add_column("Li frac", justify="right")
    table.add_column("passes", justify="right")
    for i, r in enumerate(rows, start=1):
        table.add_row(
            str(i),
            f"{r['score']:.3f}",
            r["composition"],
            r["structure_hash"][:12],
            f"{r['props'][FORMATION_ENERGY_KEY]:.3f}",
            f"{r['props'][BANDGAP_KEY]:.3f}",
            f"{r['props'][LITHIUM_FRACTION_KEY]:.3f}",
            "yes" if r["passes"] else "no",
        )
    return table


def main(
    n: int = 10,
    seed: int = 42,
    rattle_A: float = 0.15,
    console: Console | None = None,
) -> SmokeResult:
    """Drive the offline pipeline. Returns a ``SmokeResult`` summary.

    ``n`` is the number of CIFs to generate; ``seed`` controls both the
    rattle RNG inside ``random_baseline`` and the local fake-prediction
    RNG. ``rattle_A`` controls atomic displacement magnitude — too small
    and most candidates dedup-collapse to the seed; too large and the
    geometry stage rejects them as overlapping.
    """
    if console is None:
        console = Console()

    # Step 1 — generator (registry-loaded)
    generator = registry_load(
        "generator",
        "random_baseline",
        seed_cif=_seed_cif(),
        rattle_distance_A=rattle_A,
        rng_seed=seed,
    )
    raw_cifs = generator.sample(n)

    # Step 2 — gauntlet (offline mode: skip MP novelty)
    dedup = Deduplicator()
    survivors: list[tuple[str, Structure]] = []
    rejected_counts: dict[str, int] = {}
    for cif in raw_cifs:
        result = run_gauntlet(
            cif, mp_client=None, deduplicator=dedup, skip_novelty=True
        )
        if result.passed and result.structure is not None and result.structure_hash:
            survivors.append((result.structure_hash, result.structure))
        else:
            stage = result.rejected_at or "unknown"
            rejected_counts[stage] = rejected_counts.get(stage, 0) + 1

    # Step 3 — fake predictor + ranker
    ranker = registry_load("ranker", "battery_cathode")
    pred_rng = random.Random(seed + 1)
    rows: list[dict[str, Any]] = []
    for h, structure in survivors:
        props = _fake_predictions(pred_rng)
        props[LITHIUM_FRACTION_KEY] = lithium_fraction(structure)
        passes = bool(ranker.criteria(props))
        score = float(ranker.score(props)) if passes else 0.0
        rows.append(
            {
                "structure_hash": h,
                "composition": structure.composition.reduced_formula,
                "score": score,
                "passes": passes,
                "props": dict(props),
            }
        )
    rows.sort(key=lambda r: r["score"], reverse=True)

    # Step 4 — print summary + leaderboard
    console.print(
        f"[cyan]Smoke run[/cyan] generated={n} survivors={len(survivors)} "
        f"rejected={sum(rejected_counts.values())}"
    )
    if rejected_counts:
        breakdown = ", ".join(
            f"{stage}={count}" for stage, count in rejected_counts.items()
        )
        console.print(f"[dim]Gauntlet rejection histogram: {breakdown}[/dim]")
    console.print(_render_leaderboard(rows))

    passing = sum(1 for r in rows if r["passes"])
    console.print(
        f"[green]{passing} candidate(s) passed the battery_cathode "
        f"hard gates.[/green]"
    )

    return SmokeResult(
        requested=n,
        survivors=len(survivors),
        rejected_counts=rejected_counts,
        passing=passing,
        rows=rows,
    )


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crucible offline smoke run (no Anthropic, no GPU)."
    )
    parser.add_argument("--n", type=int, default=10, help="Candidates to generate.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed.")
    parser.add_argument(
        "--rattle",
        type=float,
        default=0.15,
        help="Atom displacement (Angstrom). 0.05-0.25 is the sweet spot.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":  # pragma: no cover
    args = _parse_argv()
    main(n=args.n, seed=args.seed, rattle_A=args.rattle)
