"""Tests for crucible.agents.prompts.

The prompt strings are content; we don't assert exact wording. We do
assert the prompts are *consistent* with the rest of the system: the
system prompt mentions the actual tool names, and the battery-cathode
target prompt mentions the actual ranker thresholds. If someone changes
either side, these tests force them to update both in lockstep.
"""

from __future__ import annotations

import pytest

from crucible.agents.prompts import (
    SYSTEM_PROMPT,
    TARGET_PROMPTS,
    available_targets,
    initial_user_message,
    system_prompt,
    target_prompt,
)
from crucible.agents.tools import tool_names


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def test_system_prompt_is_non_empty_string() -> None:
    s = system_prompt()
    assert isinstance(s, str)
    assert len(s) > 100  # longer than a one-liner


def test_system_prompt_mentions_every_tool_name() -> None:
    """If a tool name changes in tools.py, this test forces an update here."""
    s = system_prompt()
    for name in tool_names():
        assert name in s, f"system prompt does not mention tool {name!r}"


def test_system_prompt_covers_operating_rules() -> None:
    s = system_prompt().lower()
    # The four operating rules: vocabulary, cache, budget, units.
    assert "tool" in s
    assert "cache" in s or "query_cache" in s
    assert "budget" in s
    assert "unit" in s or "ev" in s


# ---------------------------------------------------------------------------
# Target prompts
# ---------------------------------------------------------------------------


def test_target_prompts_contains_battery_cathode() -> None:
    assert "battery_cathode" in TARGET_PROMPTS
    assert "battery_cathode" in available_targets()


def test_battery_cathode_prompt_mentions_lithium() -> None:
    p = target_prompt("battery_cathode").lower()
    assert "lithium" in p or "li " in p or "li+" in p


def test_battery_cathode_prompt_mentions_formation_energy_threshold() -> None:
    """The prompt must spell out the same -1.0 eV/atom threshold the ranker
    uses; otherwise Claude will optimize against the wrong gate."""
    p = target_prompt("battery_cathode")
    assert "-1.0" in p
    assert "eV/atom" in p or "ev/atom" in p.lower()


def test_battery_cathode_prompt_mentions_bandgap_threshold() -> None:
    p = target_prompt("battery_cathode")
    assert "1.5" in p
    assert "bandgap" in p.lower()


def test_target_prompt_unknown_target_raises_keyerror_with_help() -> None:
    with pytest.raises(KeyError) as exc:
        target_prompt("not_a_real_target")
    msg = str(exc.value)
    assert "not_a_real_target" in msg
    # Lists what IS available so callers can typo-correct themselves.
    assert "battery_cathode" in msg


# ---------------------------------------------------------------------------
# Kickoff message
# ---------------------------------------------------------------------------


def test_initial_user_message_includes_target_framing_and_budget() -> None:
    msg = initial_user_message("battery_cathode", budget=42)
    assert "lithium" in msg.lower() or "Li" in msg
    assert "42" in msg
    assert "Budget" in msg or "budget" in msg


def test_initial_user_message_rejects_zero_or_negative_budget() -> None:
    for bad in (0, -1, -1000):
        with pytest.raises(ValueError):
            initial_user_message("battery_cathode", budget=bad)


def test_initial_user_message_passes_through_target_lookup_error() -> None:
    """Unknown target should still raise KeyError, not silently produce a
    confusing 'Budget: ...' string with no framing."""
    with pytest.raises(KeyError):
        initial_user_message("not_a_real_target", budget=10)


# ---------------------------------------------------------------------------
# Sanity: SYSTEM_PROMPT is the same constant the accessor returns
# ---------------------------------------------------------------------------


def test_system_prompt_constant_matches_accessor() -> None:
    assert system_prompt() == SYSTEM_PROMPT
