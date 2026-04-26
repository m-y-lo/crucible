"""End-to-end persistence tests.

Run the orchestrator with a real ``LocalStore`` against a stubbed Claude
client and verify the database has the expected rows in runs / structures
/ rankings / gauntlet_events. This is the closest pytest equivalent of
phase1.md's stated criterion ("`crucible run --budget 20` produces >= 1
row in `rankings`").

The Anthropic client is stubbed; no network. The dispatcher and store
writes are real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.agents.tools import (
    TOOL_GENERATE_STRUCTURES,
    TOOL_SCORE_AND_RANK,
)
from crucible.core.hashing import hash_structure
from crucible.orchestrators.claude_tools import ClaudeOrchestrator
from crucible.stores.sqlite_store import LocalStore


# ---------------------------------------------------------------------------
# Anthropic stub
# ---------------------------------------------------------------------------


class _Block:
    def __init__(self, type_: str, **kwargs: Any) -> None:
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


def _tool_use(name: str, args: dict, id_: str = "t1") -> _Block:
    return _Block("tool_use", id=id_, name=name, input=args)


def _text(text: str) -> _Block:
    return _Block("text", text=text)


def _resp(stop_reason: str, content: list[_Block]) -> Any:
    r = MagicMock()
    r.stop_reason = stop_reason
    r.content = content
    return r


def _fake_client(*responses: Any) -> Any:
    client = MagicMock()
    client.messages.create.side_effect = list(responses)
    return client


def _li_seed_cif() -> str:
    s = Structure(
        Lattice.cubic(5.13),
        ["Li", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    return str(CifWriter(s))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    s = LocalStore(tmp_path / "run.db")
    yield s
    s.close()


def _query(store: LocalStore, sql: str, *params) -> list[dict]:
    return [
        dict(r)
        for r in store._require_open().execute(sql, params).fetchall()
    ]


def test_run_records_runs_table_row_with_started_and_ended(store: LocalStore) -> None:
    client = _fake_client(_resp("end_turn", [_text("done")]))
    orch = ClaudeOrchestrator(
        client=client, skip_novelty=True, max_iterations=4, store=store
    )
    run_id = orch.run("battery_cathode", budget=1)

    rows = _query(store, "SELECT * FROM runs WHERE run_id = ?", run_id)
    assert len(rows) == 1
    assert rows[0]["target"] == "battery_cathode"
    assert rows[0]["budget"] == 1
    assert rows[0]["started_at"]
    assert rows[0]["ended_at"]


def test_generate_structures_writes_gauntlet_events_and_structures(
    store: LocalStore,
) -> None:
    """A single generate_structures tool call must populate gauntlet_events
    for every stage outcome and structures for every survivor."""
    client = _fake_client(
        _resp(
            "tool_use",
            [
                _tool_use(
                    TOOL_GENERATE_STRUCTURES,
                    {"generator": "random_baseline", "n": 5},
                )
            ],
        ),
        _resp("end_turn", [_text("ok")]),
    )
    orch = ClaudeOrchestrator(
        client=client, skip_novelty=True, max_iterations=4, store=store
    )
    run_id = orch.run("battery_cathode", budget=1)

    events = _query(
        store, "SELECT * FROM gauntlet_events WHERE run_id = ?", run_id
    )
    assert len(events) >= 1, "generate_structures must log at least one event"
    # Stage labels match the canonical names.
    stage_set = {e["stage"] for e in events}
    assert "parse" in stage_set

    structures = _query(
        store, "SELECT * FROM structures WHERE source_run_id = ?", run_id
    )
    # random_baseline outputs are valid Li-bearing CIFs, so >=1 should
    # have made it through the gauntlet's first three (offline) stages.
    assert len(structures) >= 1
    for row in structures:
        assert row["composition"]
        assert row["prototype_label"]
        assert row["space_group"] >= 1
        assert row["source_generator"] == "random_baseline"


def test_score_and_rank_writes_rankings_table_row(store: LocalStore) -> None:
    """End-to-end: generate -> seed predictions -> score_and_rank -> verify
    rankings table has a passing row.
    """
    li_cl = Structure(
        Lattice.cubic(5.13), ["Li", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    h = hash_structure(li_cl)

    client = _fake_client(
        _resp(
            "tool_use",
            [
                _tool_use(
                    TOOL_SCORE_AND_RANK,
                    {"ranker": "battery_cathode", "structure_hashes": [h]},
                )
            ],
        ),
        _resp("end_turn", [_text("ok")]),
    )
    orch = ClaudeOrchestrator(
        client=client, skip_novelty=True, max_iterations=4, store=store
    )
    # Pre-seed run state so the ranker has props + a structure to look at.
    orig_dispatch = orch._dispatch

    def seeded_dispatch(name: str, args: dict, state) -> str:
        if name == TOOL_SCORE_AND_RANK:
            cif = str(CifWriter(li_cl))
            state.cifs[h] = cif
            state.structures[h] = li_cl
            state.predictions[h] = {
                "formation_energy_eV_per_atom": -1.7,
                "bandgap_eV": 0.7,
            }
            # Persist the structure first so the ranking row's FK target
            # exists. (In a real run, generate_structures would have
            # already inserted it.)
            orch._persist_structure(
                h, cif, li_cl, None, None, "random_baseline", state.run_id
            )
        return orig_dispatch(name, args, state)

    orch._dispatch = seeded_dispatch  # type: ignore[method-assign]
    run_id = orch.run("battery_cathode", budget=1)

    rankings = _query(
        store, "SELECT * FROM rankings WHERE run_id = ?", run_id
    )
    assert len(rankings) == 1, "phase1.md criterion: >=1 row in rankings"
    row = rankings[0]
    assert row["structure_hash"] == h
    assert row["target"] == "battery_cathode"
    assert row["ranker_name"] == "battery_cathode"
    assert row["passes_criteria"] == 1
    assert row["score"] is not None and row["score"] > 0
    reasoning = json.loads(row["reasoning_json"])
    assert "props_used" in reasoning


def test_orchestrator_without_store_does_not_break(tmp_path: Path) -> None:
    """Backwards-compat: the in-memory-only path still works."""
    client = _fake_client(_resp("end_turn", [_text("done")]))
    orch = ClaudeOrchestrator(
        client=client, skip_novelty=True, max_iterations=4, store=None
    )
    run_id = orch.run("battery_cathode", budget=1)
    assert isinstance(run_id, str) and len(run_id) >= 16


def test_status_command_renders_persisted_run(
    store: LocalStore, tmp_path: Path
) -> None:
    """After a real run finishes, render_status should show the run_id +
    leaderboard entries that came out of the loop."""
    from crucible.reports.status import render_status

    li_cl = Structure(
        Lattice.cubic(5.13), ["Li", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    h = hash_structure(li_cl)
    client = _fake_client(
        _resp(
            "tool_use",
            [
                _tool_use(
                    TOOL_SCORE_AND_RANK,
                    {"ranker": "battery_cathode", "structure_hashes": [h]},
                )
            ],
        ),
        _resp("end_turn", [_text("ok")]),
    )
    orch = ClaudeOrchestrator(
        client=client, skip_novelty=True, max_iterations=4, store=store
    )
    orig = orch._dispatch

    def seeded(name, args, state):
        if name == TOOL_SCORE_AND_RANK:
            cif = str(CifWriter(li_cl))
            state.cifs[h] = cif
            state.structures[h] = li_cl
            state.predictions[h] = {
                "formation_energy_eV_per_atom": -1.7,
                "bandgap_eV": 0.7,
            }
            orch._persist_structure(
                h, cif, li_cl, None, None, "random_baseline", state.run_id
            )
        return orig(name, args, state)

    orch._dispatch = seeded  # type: ignore[method-assign]
    run_id = orch.run("battery_cathode", budget=1)

    db_path = store._path  # connection still open; reader uses URI mode=ro
    out = render_status(db_path, run_id=run_id, top_n=5)
    assert run_id in out
    assert "LiCl" in out
    assert "battery_cathode" in out
