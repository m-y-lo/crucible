"""Gauntlet stage 4 — Materials Project rediscovery filter.

The product promise is "invent new materials." A candidate that matches
something already in Materials Project is a rediscovery, not a discovery.
This stage rejects those before ALIGNN wastes GPU time on them.

Two-step filter:

1. Query MP by reduced formula (cheap, cached on disk by ``MPClient``).
2. Run ``pymatgen.core.structure_matcher.StructureMatcher`` against each
   returned entry. ``StructureMatcher`` aligns crystals across cell choice,
   atom ordering, and small lattice noise; ``fit(a, b)`` is True when they
   are the same material.

Composition-prefilter cuts the comparisons from 150,000 (full MP) to
typically ≤10. The MP query cost is amortized by the disk cache.

Per ``ARCHITECTURE.md`` §10 rediscoveries can be log-only, demoted, or
dropped depending on config. Phase 1 default: drop. Pipeline can override.

Pure function (modulo the MP HTTP call hidden behind ``MPClient``). Never
raises.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure
from pymatgen.core.structure_matcher import StructureMatcher

from crucible.data.mp_client import MPClient


@dataclass(frozen=True, slots=True)
class NoveltyResult:
    """Outcome of the novelty stage.

    Diagnostics are populated on both novel and rediscovery paths so the
    pipeline can log them uniformly.
    """

    is_novel: bool
    formula: str
    mp_match_id: str | None = None
    candidates_checked: int = 0
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.is_novel


def check_novelty(structure: Structure, mp_client: MPClient) -> NoveltyResult:
    """Return a ``NoveltyResult`` for ``structure``. Never raises.

    Rejection (``is_novel=False``) happens when ``StructureMatcher``
    matches the candidate to any MP entry of the same reduced formula.
    """
    formula = structure.composition.reduced_formula

    try:
        entries = mp_client.get_entries_by_formula(formula)
    except Exception as e:  # noqa: BLE001 - MP outage / network error
        # Conservative fallback: treat as novel, log the reason. The
        # pipeline can decide to demote or retry; we don't want a network
        # blip to silently drop candidates.
        return NoveltyResult(
            is_novel=True,
            formula=formula,
            mp_match_id=None,
            candidates_checked=0,
            reason=f"MP lookup failed, treating as novel: {type(e).__name__}: {e}",
        )

    if not entries:
        return NoveltyResult(
            is_novel=True,
            formula=formula,
            mp_match_id=None,
            candidates_checked=0,
            reason=None,
        )

    matcher = StructureMatcher()
    for mp_id, mp_struct in entries:
        try:
            if matcher.fit(structure, mp_struct):
                return NoveltyResult(
                    is_novel=False,
                    formula=formula,
                    mp_match_id=mp_id,
                    candidates_checked=len(entries),
                    reason=f"rediscovery of {mp_id}",
                )
        except Exception as e:  # noqa: BLE001 - matcher choked on degenerate input
            # Skip this candidate, keep checking others. If the candidate
            # is so degenerate that every comparison raises, we'll fall
            # through to "novel" with no match — which is fine, geometry
            # would have rejected it earlier in a real pipeline.
            continue  # noqa: F841 -- e is the reason but we just continue

    return NoveltyResult(
        is_novel=True,
        formula=formula,
        mp_match_id=None,
        candidates_checked=len(entries),
        reason=None,
    )
