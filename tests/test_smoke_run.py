"""End-to-end smoke test for Crucible's offline pipeline.

Imports scripts/smoke_run.py and runs main() in-process. Verifies the
component chain composes correctly: generator -> gauntlet -> fake
predictor -> ranker -> leaderboard.

This is the closest pytest equivalent of phase1.md's stated criterion
("`crucible run --budget 20` produces >= 1 row in `rankings`"). The
orchestrator-to-store persistence is a Phase 2 concern; this test
establishes that every component on the offline path works together
today.
"""

from __future__ import annotations

import importlib.util
import sys
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console


# Load scripts/smoke_run.py as a module without it being on sys.path
# permanently. The script also prepends the repo root, but that is fine.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SMOKE_PATH = _REPO_ROOT / "scripts" / "smoke_run.py"


@pytest.fixture(scope="module")
def smoke_module():
    spec = importlib.util.spec_from_file_location("crucible_smoke_run", _SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["crucible_smoke_run"] = mod
    spec.loader.exec_module(mod)
    return mod


def _silent_console() -> Console:
    """Console that captures output to a StringIO so tests do not flood
    pytest's stdout."""
    return Console(file=StringIO(), force_terminal=False, width=120)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def test_smoke_run_completes_without_error(smoke_module) -> None:
    result = smoke_module.main(n=10, seed=42, console=_silent_console())
    assert result.requested == 10


def test_smoke_run_produces_at_least_one_survivor(smoke_module) -> None:
    """The Li-bearing seed + small (0.05 A) rattle yields lots of survivors
    -- the gauntlet thresholds are forgiving by design."""
    result = smoke_module.main(n=10, seed=42, console=_silent_console())
    assert result.survivors >= 1
    # Each survivor row carries a structure_hash and a composition.
    for row in result.rows:
        assert row["structure_hash"]
        assert row["composition"]


def test_smoke_run_produces_at_least_one_passing_candidate(smoke_module) -> None:
    """Per phase1.md validation criterion: >= 1 candidate must pass the
    full chain (gauntlet + ranker hard gates)."""
    result = smoke_module.main(n=20, seed=42, console=_silent_console())
    assert result.passing >= 1, (
        f"smoke run produced no passing candidates; rows={result.rows!r}"
    )


def test_smoke_run_leaderboard_is_sorted_by_score_desc(smoke_module) -> None:
    result = smoke_module.main(n=20, seed=42, console=_silent_console())
    scores = [r["score"] for r in result.rows]
    assert scores == sorted(scores, reverse=True)


def test_smoke_run_props_include_lithium_fraction(smoke_module) -> None:
    result = smoke_module.main(n=5, seed=42, console=_silent_console())
    for row in result.rows:
        assert "lithium_fraction" in row["props"]
        # Li-Cl seed -> rattled variants -> lithium_fraction == 0.5.
        assert row["props"]["lithium_fraction"] == pytest.approx(0.5)


def test_smoke_run_is_reproducible_with_same_seed(smoke_module) -> None:
    a = smoke_module.main(n=10, seed=7, console=_silent_console())
    b = smoke_module.main(n=10, seed=7, console=_silent_console())
    assert a.survivors == b.survivors
    assert a.passing == b.passing
    # Rows in the same order with the same hashes.
    assert [r["structure_hash"] for r in a.rows] == [r["structure_hash"] for r in b.rows]


def test_smoke_run_emits_leaderboard_table_text(smoke_module) -> None:
    """The console output must contain a leaderboard the user can read."""
    file = StringIO()
    console = Console(file=file, force_terminal=False, width=120, record=True)
    smoke_module.main(n=10, seed=42, console=console)
    text = console.export_text()
    assert "Smoke run" in text
    assert "rank" in text
    assert "score" in text
    assert "formula" in text


# ---------------------------------------------------------------------------
# CLI argv parser
# ---------------------------------------------------------------------------


def test_argv_parser_defaults(smoke_module) -> None:
    args = smoke_module._parse_argv([])
    assert args.n == 10
    assert args.seed == 42


def test_argv_parser_overrides(smoke_module) -> None:
    args = smoke_module._parse_argv(["--n", "5", "--seed", "99"])
    assert args.n == 5
    assert args.seed == 99
