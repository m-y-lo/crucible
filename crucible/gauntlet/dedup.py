"""Gauntlet stage 5 — within-run deduplication.

Generators sample stochastically and re-emit the same structure within a
single run. This stage rejects exact duplicates so ALIGNN does not score
the same candidate twice and the leaderboard stays unique.

Distinct from ``novelty``: novelty asks "is this in MP?" (global, network,
cached on disk). Dedup asks "have we already seen this in *this* run?"
(local, in-memory, scoped to one ``Deduplicator`` instance).

Three-tier algorithm:

1. **Hash exact match** — O(1) ``set`` lookup. ``hashing.hash_structure``
   produces the same digest for the same crystal regardless of cell
   choice or atom ordering, so this catches almost all duplicates.
2. **Prototype + composition coarse** — O(1) dict lookup narrows to a
   bucket of ≤K candidates with the same skeletal pattern and formula.
3. **StructureMatcher fallback** — runs only against the bucket.
   Catches structures that produce different hashes due to
   floating-point noise but are equivalent under matcher tolerances.

State is held by the ``Deduplicator`` instance. The pipeline creates one
per run and reuses it for every candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from pymatgen.core import Structure
from pymatgen.core.structure_matcher import StructureMatcher

from crucible.core.hashing import hash_structure, prototype_label_of


@dataclass(frozen=True, slots=True)
class DedupResult:
    """Outcome of the dedup stage.

    On unique: ``is_unique=True``, ``structure_hash`` is populated, others
    are None.
    On duplicate: ``is_unique=False``, all fields populated; ``reason``
    summarizes which tier triggered the rejection.
    """

    is_unique: bool
    structure_hash: str | None
    prototype_label: str | None
    matched_hash: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.is_unique


class Deduplicator:
    """In-memory accumulator that detects within-run duplicates.

    Not thread-safe by design: one ``Deduplicator`` per run, called
    serially from the gauntlet pipeline.
    """

    def __init__(self) -> None:
        self._seen_hashes: set[str] = set()
        # Bucket key is f"{prototype_label}|{reduced_formula}". Value is
        # a list of (structure_hash, Structure) we have already accepted
        # with that bucket key. List-of-tuples (not a dict) so we can run
        # StructureMatcher against each in turn.
        self._by_bucket: dict[str, list[tuple[str, Structure]]] = {}
        self._matcher = StructureMatcher()

    def reset(self) -> None:
        """Clear all accumulated state. Useful for tests / new runs."""
        self._seen_hashes.clear()
        self._by_bucket.clear()

    def __len__(self) -> int:
        return len(self._seen_hashes)

    def __iter__(self) -> Iterator[str]:
        return iter(self._seen_hashes)

    def check(self, structure: Structure) -> DedupResult:
        """Return a ``DedupResult`` for ``structure``. Never raises.

        On a UNIQUE verdict the structure is added to internal state.
        On a DUPLICATE verdict state is unchanged.
        """
        try:
            cand_hash = hash_structure(structure)
        except Exception as e:  # noqa: BLE001 - degenerate structure -> reject
            return DedupResult(
                is_unique=False,
                structure_hash=None,
                prototype_label=None,
                reason=f"hash failed: {type(e).__name__}: {e}",
            )

        # Tier 1: exact hash match.
        if cand_hash in self._seen_hashes:
            return DedupResult(
                is_unique=False,
                structure_hash=cand_hash,
                prototype_label=None,
                matched_hash=cand_hash,
                reason="duplicate (hash exact match)",
            )

        try:
            proto = prototype_label_of(structure)
        except Exception as e:  # noqa: BLE001
            return DedupResult(
                is_unique=False,
                structure_hash=cand_hash,
                prototype_label=None,
                reason=f"prototype label failed: {type(e).__name__}: {e}",
            )

        formula = structure.composition.reduced_formula
        bucket_key = f"{proto}|{formula}"
        bucket = self._by_bucket.get(bucket_key)

        # Tier 2 + 3: prototype-bucket coarse + StructureMatcher fallback.
        if bucket:
            for prior_hash, prior_struct in bucket:
                try:
                    matches = self._matcher.fit(structure, prior_struct)
                except Exception:  # noqa: BLE001 - skip degenerate prior
                    continue
                if matches:
                    return DedupResult(
                        is_unique=False,
                        structure_hash=cand_hash,
                        prototype_label=proto,
                        matched_hash=prior_hash,
                        reason=f"duplicate (StructureMatcher vs {prior_hash[:12]})",
                    )

        # Unique. Commit to state.
        self._seen_hashes.add(cand_hash)
        self._by_bucket.setdefault(bucket_key, []).append((cand_hash, structure))

        return DedupResult(
            is_unique=True,
            structure_hash=cand_hash,
            prototype_label=proto,
            matched_hash=None,
            reason=None,
        )
