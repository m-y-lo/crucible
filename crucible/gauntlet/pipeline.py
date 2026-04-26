"""Gauntlet pipeline — composes the five stages with early exit.

Threads a raw CIF through:

    parse -> composition -> geometry -> novelty -> dedup

Each stage's outcome (pass or fail) is recorded as a ``GauntletEvent`` on
the returned ``GauntletResult``. The pipeline stops at the first
rejection — later stages are more expensive (novelty does an MP lookup;
ALIGNN downstream is the GPU-bound bottleneck), so cheap rejections up
front are the whole point.

This module **does not** write to SQLite directly. The caller has the
``run_id`` and access to ``crucible.stores`` / ``crucible.core.logging``;
they walk ``result.events`` and persist as appropriate. Keeping the
pipeline storage-agnostic means it is reusable for batch testing, CLI
``crucible predict`` one-offs, and Phase 3 worker-side use.

Pure with respect to its inputs (modulo the ``Deduplicator`` whose
internal state advances on every UNIQUE verdict, by design).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pymatgen.core import Structure

from crucible.data.mp_client import MPClient
from crucible.gauntlet.composition import check_composition
from crucible.gauntlet.dedup import Deduplicator
from crucible.gauntlet.geometry import check_geometry
from crucible.gauntlet.novelty import check_novelty
from crucible.gauntlet.parse import try_parse

# Stage name constants — matches the values written to
# ``gauntlet_events.stage`` per ARCHITECTURE.md section 4. Centralized here
# so the pipeline and any consumer of events agree on spelling.
STAGE_PARSE = "parse"
STAGE_COMPOSITION = "composition"
STAGE_GEOMETRY = "geometry"
STAGE_NOVELTY = "novelty"
STAGE_DEDUP = "dedup"

ALL_STAGES = (
    STAGE_PARSE,
    STAGE_COMPOSITION,
    STAGE_GEOMETRY,
    STAGE_NOVELTY,
    STAGE_DEDUP,
)


@dataclass(frozen=True, slots=True)
class GauntletEvent:
    """One row destined for ``gauntlet_events``.

    ``structure_hash`` is None when the parse stage rejects (no Structure
    was ever produced) and may be None for any rejection that fires before
    the dedup stage computes the hash.
    """

    stage: str
    passed: bool
    reason: str | None
    structure_hash: str | None = None


@dataclass(frozen=True, slots=True)
class GauntletResult:
    """Final verdict on a CIF after all enabled stages.

    ``passed`` is True only if every stage passed. ``rejected_at`` names
    the first stage that rejected (None on a clean pass).
    """

    passed: bool
    rejected_at: str | None
    structure: Structure | None
    structure_hash: str | None
    prototype_label: str | None
    composition_formula: str | None
    events: list[GauntletEvent] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.passed


def run_gauntlet(
    cif: str,
    *,
    mp_client: MPClient | None,
    deduplicator: Deduplicator,
    skip_novelty: bool = False,
) -> GauntletResult:
    """Run ``cif`` through every enabled gauntlet stage. Never raises.

    ``mp_client`` may be None if ``skip_novelty`` is True (for offline
    smoke tests; Phase 1 prod always has a key configured).

    The ``deduplicator`` argument is a stateful accumulator. Pass the
    *same* instance across all candidates in one run; reset between runs.
    """
    events: list[GauntletEvent] = []

    # 1) parse ---------------------------------------------------------------
    parsed = try_parse(cif)
    events.append(
        GauntletEvent(
            stage=STAGE_PARSE,
            passed=parsed.ok,
            reason=parsed.reason,
            structure_hash=None,
        )
    )
    if not parsed.ok:
        return GauntletResult(
            passed=False,
            rejected_at=STAGE_PARSE,
            structure=None,
            structure_hash=None,
            prototype_label=None,
            composition_formula=None,
            events=events,
        )
    structure = parsed.structure
    assert structure is not None  # for type checkers

    # 2) composition ---------------------------------------------------------
    comp = check_composition(structure)
    events.append(
        GauntletEvent(
            stage=STAGE_COMPOSITION,
            passed=comp.ok,
            reason=comp.reason,
            structure_hash=None,
        )
    )
    if not comp.ok:
        return GauntletResult(
            passed=False,
            rejected_at=STAGE_COMPOSITION,
            structure=structure,
            structure_hash=None,
            prototype_label=None,
            composition_formula=comp.reduced_formula,
            events=events,
        )

    # 3) geometry ------------------------------------------------------------
    geom = check_geometry(structure)
    events.append(
        GauntletEvent(
            stage=STAGE_GEOMETRY,
            passed=geom.ok,
            reason=geom.reason,
            structure_hash=None,
        )
    )
    if not geom.ok:
        return GauntletResult(
            passed=False,
            rejected_at=STAGE_GEOMETRY,
            structure=structure,
            structure_hash=None,
            prototype_label=None,
            composition_formula=comp.reduced_formula,
            events=events,
        )

    # 4) novelty (optional) --------------------------------------------------
    if not skip_novelty:
        if mp_client is None:
            raise ValueError(
                "novelty stage requires an MPClient; pass mp_client=... "
                "or set skip_novelty=True."
            )
        nov = check_novelty(structure, mp_client)
        events.append(
            GauntletEvent(
                stage=STAGE_NOVELTY,
                passed=nov.ok,
                reason=nov.reason,
                structure_hash=None,
            )
        )
        if not nov.ok:
            return GauntletResult(
                passed=False,
                rejected_at=STAGE_NOVELTY,
                structure=structure,
                structure_hash=None,
                prototype_label=None,
                composition_formula=comp.reduced_formula,
                events=events,
            )

    # 5) dedup --------------------------------------------------------------
    dup = deduplicator.check(structure)
    events.append(
        GauntletEvent(
            stage=STAGE_DEDUP,
            passed=dup.ok,
            reason=dup.reason,
            structure_hash=dup.structure_hash,
        )
    )
    if not dup.ok:
        return GauntletResult(
            passed=False,
            rejected_at=STAGE_DEDUP,
            structure=structure,
            structure_hash=dup.structure_hash,
            prototype_label=dup.prototype_label,
            composition_formula=comp.reduced_formula,
            events=events,
        )

    # Survivor — every stage passed.
    return GauntletResult(
        passed=True,
        rejected_at=None,
        structure=structure,
        structure_hash=dup.structure_hash,
        prototype_label=dup.prototype_label,
        composition_formula=comp.reduced_formula,
        events=events,
    )
