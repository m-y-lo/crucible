"""End-to-end tests for crucible.gauntlet.pipeline.

Covers the early-exit ladder, the event log shape, and integration with
all five stages. The MP client is stubbed; no network or API key needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.gauntlet.dedup import Deduplicator
from crucible.gauntlet.pipeline import (
    ALL_STAGES,
    STAGE_COMPOSITION,
    STAGE_DEDUP,
    STAGE_GEOMETRY,
    STAGE_NOVELTY,
    STAGE_PARSE,
    GauntletEvent,
    GauntletResult,
    run_gauntlet,
)


def _cif(structure: Structure) -> str:
    return str(CifWriter(structure))


def _nacl_rocksalt() -> Structure:
    """8-atom NaCl rocksalt cube — passes every stage by default."""
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Na", "Na", "Na", "Cl", "Cl", "Cl", "Cl"],
        [
            [0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
            [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5],
        ],
    )


def _empty_mp() -> Any:
    """Stub MPClient that always returns no entries (everything is novel)."""
    fake = MagicMock()
    fake.get_entries_by_formula.return_value = []
    return fake


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------


def test_clean_cif_passes_all_stages() -> None:
    result = run_gauntlet(
        _cif(_nacl_rocksalt()),
        mp_client=_empty_mp(),
        deduplicator=Deduplicator(),
    )
    assert isinstance(result, GauntletResult)
    assert result.passed
    assert result.rejected_at is None
    assert result.structure is not None
    assert result.structure_hash is not None
    assert result.prototype_label is not None
    assert result.composition_formula == "NaCl"
    # All five stages logged.
    stages = [e.stage for e in result.events]
    assert stages == list(ALL_STAGES)
    assert all(e.passed for e in result.events)


def test_skip_novelty_runs_only_four_stages() -> None:
    result = run_gauntlet(
        _cif(_nacl_rocksalt()),
        mp_client=None,
        deduplicator=Deduplicator(),
        skip_novelty=True,
    )
    assert result.passed
    stages = [e.stage for e in result.events]
    assert STAGE_NOVELTY not in stages
    assert stages == [STAGE_PARSE, STAGE_COMPOSITION, STAGE_GEOMETRY, STAGE_DEDUP]


# --------------------------------------------------------------------------
# early-exit ladder — each stage gets its own rejection
# --------------------------------------------------------------------------


def test_parse_failure_short_circuits() -> None:
    result = run_gauntlet(
        "not a CIF",
        mp_client=_empty_mp(),
        deduplicator=Deduplicator(),
    )
    assert not result.passed
    assert result.rejected_at == STAGE_PARSE
    assert result.structure is None
    assert len(result.events) == 1
    assert result.events[0].stage == STAGE_PARSE
    assert not result.events[0].passed


def test_composition_failure_short_circuits() -> None:
    """LiCl2 is charge-imbalanced — composition rejects."""
    licl2 = Structure(
        Lattice.cubic(5.64),
        ["Li", "Cl", "Cl"],
        [[0, 0, 0], [0.3, 0.3, 0.3], [0.6, 0.6, 0.6]],
    )
    result = run_gauntlet(
        _cif(licl2),
        mp_client=_empty_mp(),
        deduplicator=Deduplicator(),
    )
    assert not result.passed
    assert result.rejected_at == STAGE_COMPOSITION
    assert result.composition_formula is not None  # set even on rejection
    assert {e.stage for e in result.events} == {STAGE_PARSE, STAGE_COMPOSITION}


def test_geometry_failure_short_circuits() -> None:
    """Vacuum-padded cell — composition passes (BVA finds valences),
    geometry rejects on volume-per-atom > 100 A^3."""
    vacuum_padded = Structure(
        Lattice.cubic(10.0),  # 500 A^3/atom
        ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    result = run_gauntlet(
        _cif(vacuum_padded),
        mp_client=_empty_mp(),
        deduplicator=Deduplicator(),
    )
    assert not result.passed
    assert result.rejected_at == STAGE_GEOMETRY
    stages = [e.stage for e in result.events]
    assert stages == [STAGE_PARSE, STAGE_COMPOSITION, STAGE_GEOMETRY]


def test_novelty_failure_short_circuits() -> None:
    """MP returns the same structure -> rediscovery -> novelty rejects."""
    nacl = _nacl_rocksalt()
    fake_mp = MagicMock()
    fake_mp.get_entries_by_formula.return_value = [("mp-22862", nacl)]
    result = run_gauntlet(
        _cif(nacl),
        mp_client=fake_mp,
        deduplicator=Deduplicator(),
    )
    assert not result.passed
    assert result.rejected_at == STAGE_NOVELTY
    assert "mp-22862" in (result.events[-1].reason or "")


def test_dedup_failure_short_circuits() -> None:
    """Same CIF run twice through the same deduplicator -> dedup rejects."""
    dedup = Deduplicator()
    cif = _cif(_nacl_rocksalt())
    first = run_gauntlet(cif, mp_client=_empty_mp(), deduplicator=dedup)
    second = run_gauntlet(cif, mp_client=_empty_mp(), deduplicator=dedup)
    assert first.passed
    assert not second.passed
    assert second.rejected_at == STAGE_DEDUP
    assert len(dedup) == 1


# --------------------------------------------------------------------------
# event-log invariants
# --------------------------------------------------------------------------


def test_events_logged_in_order_at_most_through_failing_stage() -> None:
    vacuum_padded = Structure(
        Lattice.cubic(10.0),
        ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    result = run_gauntlet(
        _cif(vacuum_padded),
        mp_client=_empty_mp(),
        deduplicator=Deduplicator(),
    )
    assert [e.stage for e in result.events] == [
        STAGE_PARSE,
        STAGE_COMPOSITION,
        STAGE_GEOMETRY,
    ]
    # Only the last event is a failure on early-exit.
    assert all(e.passed for e in result.events[:-1])
    assert not result.events[-1].passed


def test_event_dataclass_fields() -> None:
    e = GauntletEvent(stage=STAGE_PARSE, passed=False, reason="x", structure_hash=None)
    assert e.stage == "parse"
    assert e.passed is False
    assert e.reason == "x"
    assert e.structure_hash is None


# --------------------------------------------------------------------------
# integration: a chain of candidates with mixed verdicts
# --------------------------------------------------------------------------


def test_pipeline_integrates_across_a_batch() -> None:
    """Smoke test: several candidates through one shared Deduplicator."""
    dedup = Deduplicator()
    mp = _empty_mp()

    nacl_cif = _cif(_nacl_rocksalt())
    bad_cif = "garbage"
    licl2 = Structure(
        Lattice.cubic(5.64),
        ["Li", "Cl", "Cl"],
        [[0, 0, 0], [0.3, 0.3, 0.3], [0.6, 0.6, 0.6]],
    )

    r1 = run_gauntlet(nacl_cif, mp_client=mp, deduplicator=dedup)        # PASS
    r2 = run_gauntlet(bad_cif, mp_client=mp, deduplicator=dedup)         # parse
    r3 = run_gauntlet(_cif(licl2), mp_client=mp, deduplicator=dedup)     # composition
    r4 = run_gauntlet(nacl_cif, mp_client=mp, deduplicator=dedup)        # dedup

    verdicts = [(r.passed, r.rejected_at) for r in [r1, r2, r3, r4]]
    assert verdicts == [
        (True, None),
        (False, STAGE_PARSE),
        (False, STAGE_COMPOSITION),
        (False, STAGE_DEDUP),
    ]
    assert len(dedup) == 1, "only the first NaCl was unique"
