"""Tests for crucible.orchestrators.claude_tools.

The Anthropic API is mocked end-to-end. Tests verify dispatcher correctness,
budget enforcement, plugin-error handling, and per-tool handler behavior
without ever calling out to a real Claude.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from crucible.agents.tools import (
    TOOL_GENERATE_STRUCTURES,
    TOOL_PREDICT,
    TOOL_QUERY_CACHE,
    TOOL_RELAX,
    TOOL_SCORE_AND_RANK,
)
from crucible.orchestrators.claude_tools import ClaudeOrchestrator


# ---------------------------------------------------------------------------
# Fake Anthropic-SDK response builders
# ---------------------------------------------------------------------------


class _Block:
    """Stand-in for a content block emitted by the SDK."""

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


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_requires_key_or_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ClaudeOrchestrator(skip_novelty=True)


def test_constructor_requires_mp_client_when_novelty_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with pytest.raises(ValueError):
        ClaudeOrchestrator(client=MagicMock(), skip_novelty=False, mp_client=None)


# ---------------------------------------------------------------------------
# end-to-end loop with stubbed Anthropic
# ---------------------------------------------------------------------------


def _orch(client: Any) -> ClaudeOrchestrator:
    return ClaudeOrchestrator(client=client, skip_novelty=True, max_iterations=4)


def test_run_returns_a_run_id_and_terminates_on_end_turn() -> None:
    client = _fake_client(_resp("end_turn", [_text("done")]))
    orch = _orch(client)
    run_id = orch.run("battery_cathode", budget=1)
    assert isinstance(run_id, str) and len(run_id) >= 16
    assert client.messages.create.call_count == 1


def test_run_loops_through_a_tool_use_then_stops() -> None:
    """Two-turn loop: tool_use -> tool_result -> end_turn."""
    client = _fake_client(
        _resp(
            "tool_use",
            [_tool_use(TOOL_GENERATE_STRUCTURES, {"generator": "random_baseline", "n": 1})],
        ),
        _resp("end_turn", [_text("ok")]),
    )
    orch = _orch(client)
    orch.run("battery_cathode", budget=1)
    assert client.messages.create.call_count == 2

    # The second messages.create call must include a tool_result block in
    # the user message.
    second_call_kwargs = client.messages.create.call_args_list[1].kwargs
    msgs = second_call_kwargs["messages"]
    last_user = next(m for m in reversed(msgs) if m["role"] == "user")
    contents = last_user["content"]
    assert isinstance(contents, list)
    assert any(c.get("type") == "tool_result" for c in contents)


def test_run_rejects_non_positive_budget() -> None:
    orch = _orch(_fake_client(_resp("end_turn", [_text("x")])))
    with pytest.raises(ValueError):
        orch.run("battery_cathode", budget=0)


def test_run_stops_on_max_iterations_when_loop_does_not_terminate() -> None:
    """If Claude keeps emitting tool_use forever, the orchestrator must
    stop at max_iterations rather than spin."""
    bottomless = [
        _resp(
            "tool_use",
            [_tool_use(TOOL_QUERY_CACHE, {"structure_hash": "abc"})],
        )
        for _ in range(20)
    ]
    client = _fake_client(*bottomless)
    orch = _orch(client)
    orch.run("battery_cathode", budget=999)
    assert client.messages.create.call_count == 4  # max_iterations


# ---------------------------------------------------------------------------
# dispatcher: error paths surface to Claude as tool_result text
# ---------------------------------------------------------------------------


def test_unknown_generator_becomes_tool_error_not_crash() -> None:
    client = _fake_client(
        _resp(
            "tool_use",
            [_tool_use(TOOL_GENERATE_STRUCTURES, {"generator": "does_not_exist", "n": 1})],
        ),
        _resp("end_turn", [_text("noted")]),
    )
    orch = _orch(client)
    orch.run("battery_cathode", budget=1)

    # Inspect the tool_result we sent back. It must contain an "error".
    second_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
    last_user = [m for m in second_msgs if m["role"] == "user"][-1]
    tool_results = [c for c in last_user["content"] if c.get("type") == "tool_result"]
    assert tool_results
    payload = json.loads(tool_results[0]["content"])
    assert "error" in payload


def test_predict_with_missing_predictor_plugin_becomes_error() -> None:
    """Predictors are not yet registered (ALIGNN blocked on ML deps).
    The orchestrator must report a tool error, not crash."""
    client = _fake_client(
        _resp(
            "tool_use",
            [_tool_use(TOOL_PREDICT, {"predictor": "alignn", "cif": "irrelevant"})],
        ),
        _resp("end_turn", [_text("noted")]),
    )
    orch = _orch(client)
    orch.run("battery_cathode", budget=1)
    second_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
    last_user = [m for m in second_msgs if m["role"] == "user"][-1]
    payload = json.loads(last_user["content"][0]["content"])
    assert "error" in payload


# ---------------------------------------------------------------------------
# generate_structures handler integration with random_baseline + gauntlet
# ---------------------------------------------------------------------------


def test_generate_structures_returns_survivors_through_random_baseline() -> None:
    client = _fake_client(
        _resp(
            "tool_use",
            [
                _tool_use(
                    TOOL_GENERATE_STRUCTURES,
                    {"generator": "random_baseline", "n": 3},
                )
            ],
        ),
        _resp("end_turn", [_text("ok")]),
    )
    orch = _orch(client)
    orch.run("battery_cathode", budget=1)

    second_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
    last_user = [m for m in second_msgs if m["role"] == "user"][-1]
    payload = json.loads(last_user["content"][0]["content"])
    assert payload["generator"] == "random_baseline"
    assert payload["requested"] == 3
    assert "survivors" in payload
    # Some survivors expected since 0.1A rattled NaCl passes the gauntlet
    # and skip_novelty is True for tests.
    assert len(payload["survivors"]) >= 1
    for entry in payload["survivors"]:
        assert "structure_hash" in entry
        assert "cif" in entry


# ---------------------------------------------------------------------------
# score_and_rank handler integration with battery_cathode + cached predictions
# ---------------------------------------------------------------------------


def test_score_and_rank_uses_in_memory_predictions() -> None:
    """End-to-end: generate -> hand-feed predictions into state -> score_and_rank
    pulls them and applies the ranker."""
    nacl_with_li = Structure(
        Lattice.cubic(5.64),
        ["Li", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    cif = str(CifWriter(nacl_with_li))
    from crucible.core.hashing import hash_structure
    h = hash_structure(nacl_with_li)

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
    orch = _orch(client)

    # Pre-populate run state so score_and_rank has something to find.
    # We do this by intercepting the dispatch call's state argument: the
    # cleanest way is to monkey-patch _dispatch's state mid-run, but the
    # simpler path is to seed via a dummy generate call -- below we just
    # poke the in-memory dicts via a dedicated test seam:
    orig_dispatch = orch._dispatch

    def seeded_dispatch(name: str, args: dict[str, Any], state: Any) -> str:
        if name == TOOL_SCORE_AND_RANK:
            state.cifs[h] = cif
            state.structures[h] = nacl_with_li
            state.predictions[h] = {
                "formation_energy_eV_per_atom": -1.7,
                "bandgap_eV": 0.7,
            }
        return orig_dispatch(name, args, state)

    orch._dispatch = seeded_dispatch  # type: ignore[method-assign]
    orch.run("battery_cathode", budget=1)

    second_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
    last_user = [m for m in second_msgs if m["role"] == "user"][-1]
    payload = json.loads(last_user["content"][0]["content"])
    assert payload["ranker"] == "battery_cathode"
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["passes"] is True
    assert result["score"] > 0
    # lithium_fraction was computed from the structure and added to props.
    assert result["props_used"]["lithium_fraction"] == 0.5


# ---------------------------------------------------------------------------
# query_cache handler
# ---------------------------------------------------------------------------


def test_query_cache_requires_at_least_one_arg() -> None:
    client = _fake_client(
        _resp("tool_use", [_tool_use(TOOL_QUERY_CACHE, {})]),
        _resp("end_turn", [_text("ok")]),
    )
    orch = _orch(client)
    orch.run("battery_cathode", budget=1)
    second_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
    payload = json.loads(
        [m for m in second_msgs if m["role"] == "user"][-1]["content"][0]["content"]
    )
    assert "error" in payload
