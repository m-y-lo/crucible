"""Tests for crucible.gauntlet.novelty.

The MPClient is mocked end-to-end so these tests run with no network and
no real API key. We construct a fake client whose
``get_entries_by_formula`` returns canned (mp_id, Structure) tuples.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pymatgen.core import Lattice, Structure

from crucible.gauntlet.novelty import NoveltyResult, check_novelty


def _nacl(a: float = 5.64) -> Structure:
    return Structure(Lattice.cubic(a), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _kcl() -> Structure:
    return Structure(Lattice.cubic(6.29), ["K", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _fake_client(entries_by_formula: dict[str, list[tuple[str, Structure]]]) -> Any:
    fake = MagicMock()
    fake.get_entries_by_formula.side_effect = lambda formula: entries_by_formula.get(formula, [])
    return fake


# ----- novel paths --------------------------------------------------------


def test_empty_mp_means_novel() -> None:
    fake = _fake_client({})
    result = check_novelty(_nacl(), fake)
    assert isinstance(result, NoveltyResult)
    assert result.is_novel
    assert result.ok
    assert result.mp_match_id is None
    assert result.candidates_checked == 0
    assert result.formula == "NaCl"


def test_mp_returns_unrelated_compound_means_novel() -> None:
    """MP returns entries, but none structurally match the candidate.

    The fake MP returns a CaO structure under the NaCl key — same anonymous
    prototype, but different elements. ``StructureMatcher.fit`` (not
    ``fit_anonymous``) requires matching species and returns False here.
    """
    cao = Structure(Lattice.cubic(4.81), ["Ca", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    fake = _fake_client({"NaCl": [("mp-fake", cao)]})
    result = check_novelty(_nacl(), fake)
    assert result.is_novel
    assert result.candidates_checked == 1
    assert result.mp_match_id is None


# ----- rediscovery paths --------------------------------------------------


def test_exact_match_is_rediscovery() -> None:
    fake = _fake_client({"NaCl": [("mp-22862", _nacl())]})
    result = check_novelty(_nacl(), fake)
    assert not result.is_novel
    assert not result.ok
    assert result.mp_match_id == "mp-22862"
    assert result.candidates_checked == 1
    assert "mp-22862" in (result.reason or "")


def test_match_with_slightly_relaxed_lattice_is_rediscovery() -> None:
    """StructureMatcher allows small lattice differences — same crystal."""
    fake = _fake_client({"NaCl": [("mp-22862", _nacl(a=5.7))]})
    result = check_novelty(_nacl(a=5.64), fake)
    assert not result.is_novel
    assert result.mp_match_id == "mp-22862"


def test_first_match_short_circuits() -> None:
    """Multiple MP candidates: return on the first match, but report total
    count of entries that *were available* (here we only checked enough to
    find a match)."""
    fake = _fake_client({
        "NaCl": [
            ("mp-aaa", _nacl()),       # matches first
            ("mp-bbb", _nacl(a=10.0)),  # never reached
        ]
    })
    result = check_novelty(_nacl(), fake)
    assert not result.is_novel
    assert result.mp_match_id == "mp-aaa"


# ----- error paths --------------------------------------------------------


def test_mp_outage_treated_as_novel_with_reason() -> None:
    """Network failure must not silently drop candidates."""
    fake = MagicMock()
    fake.get_entries_by_formula.side_effect = ConnectionError("MP unreachable")

    result = check_novelty(_nacl(), fake)
    assert result.is_novel  # conservative: don't reject on network blip
    assert result.reason is not None
    assert "MP lookup failed" in result.reason
    assert "ConnectionError" in result.reason


def test_structure_matcher_failure_does_not_raise() -> None:
    """If StructureMatcher chokes on one entry, keep going to the next."""

    class BombStruct:
        """Forces StructureMatcher.fit to raise."""

        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("StructureMatcher blew up on this entry")

    fake = _fake_client({"NaCl": [("mp-broken", BombStruct())]})  # type: ignore[arg-type]
    result = check_novelty(_nacl(), fake)
    assert isinstance(result, NoveltyResult)
    # No match found (matcher raised) -> falls through to novel.
    assert result.is_novel
    assert result.candidates_checked == 1


# ----- ergonomics ---------------------------------------------------------


def test_novelty_result_ok_property() -> None:
    novel = NoveltyResult(is_novel=True, formula="X", mp_match_id=None)
    rediscovery = NoveltyResult(
        is_novel=False, formula="X", mp_match_id="mp-1", reason="rediscovery of mp-1"
    )
    assert novel.ok is True
    assert rediscovery.ok is False
