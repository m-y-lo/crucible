"""Tests for crucible.agents.tools.

The tool list is data, not behavior. We verify:
- Anthropic tool-use schema shape (name / description / input_schema).
- All five canonical tools are present, exactly once each.
- Each input_schema is JSON-Schema-shaped (object with properties + required).
- Required fields name actual keys in `properties`.
- tool_by_name and tool_names accessors work.
"""

from __future__ import annotations

from typing import Any

import pytest

from crucible.agents.tools import (
    TOOL_GENERATE_STRUCTURES,
    TOOL_PREDICT,
    TOOL_QUERY_CACHE,
    TOOL_RELAX,
    TOOL_SCORE_AND_RANK,
    TOOLS,
    tool_by_name,
    tool_names,
)

CANONICAL_NAMES = {
    TOOL_GENERATE_STRUCTURES,
    TOOL_RELAX,
    TOOL_PREDICT,
    TOOL_SCORE_AND_RANK,
    TOOL_QUERY_CACHE,
}


# ----- top-level shape ----------------------------------------------------


def test_tools_is_a_list_of_dicts() -> None:
    assert isinstance(TOOLS, list)
    assert len(TOOLS) == 5
    assert all(isinstance(t, dict) for t in TOOLS)


def test_all_canonical_names_present_exactly_once() -> None:
    names = [t["name"] for t in TOOLS]
    assert set(names) == CANONICAL_NAMES
    assert len(names) == len(CANONICAL_NAMES), "names must be unique"


def test_tool_names_returns_canonical_names_in_declaration_order() -> None:
    names = tool_names()
    assert set(names) == CANONICAL_NAMES
    # Same list as TOOLS in order.
    assert names == [t["name"] for t in TOOLS]


# ----- per-tool schema shape ---------------------------------------------


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_each_tool_has_required_top_level_keys(tool: dict[str, Any]) -> None:
    assert set(tool.keys()) >= {"name", "description", "input_schema"}
    assert isinstance(tool["name"], str) and tool["name"]
    assert isinstance(tool["description"], str) and tool["description"]
    assert isinstance(tool["input_schema"], dict)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_each_input_schema_is_object_with_properties(tool: dict[str, Any]) -> None:
    schema = tool["input_schema"]
    assert schema.get("type") == "object"
    assert isinstance(schema.get("properties"), dict)
    assert "required" in schema, "must declare a required list (may be empty)"
    assert isinstance(schema["required"], list)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_required_fields_actually_exist_in_properties(tool: dict[str, Any]) -> None:
    schema = tool["input_schema"]
    properties = schema["properties"]
    for required_key in schema["required"]:
        assert required_key in properties, (
            f"tool {tool['name']!r} marks {required_key!r} required but does "
            f"not declare it in properties"
        )


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_each_property_has_a_type_or_anyOf(tool: dict[str, Any]) -> None:
    """JSON-Schema validity sniff: every declared arg gets a type."""
    properties = tool["input_schema"]["properties"]
    for prop_name, prop_spec in properties.items():
        assert "type" in prop_spec or "anyOf" in prop_spec or "oneOf" in prop_spec, (
            f"property {tool['name']}.{prop_name} has no type or schema combinator"
        )


# ----- spot-check each tool's required surface ---------------------------


def test_generate_structures_requires_generator_and_n() -> None:
    schema = tool_by_name(TOOL_GENERATE_STRUCTURES)["input_schema"]
    assert set(schema["required"]) == {"generator", "n"}
    assert schema["properties"]["n"].get("minimum") == 1


def test_relax_requires_cif_and_relaxer() -> None:
    schema = tool_by_name(TOOL_RELAX)["input_schema"]
    assert set(schema["required"]) == {"cif", "relaxer"}


def test_predict_requires_cif_and_predictor() -> None:
    schema = tool_by_name(TOOL_PREDICT)["input_schema"]
    assert set(schema["required"]) == {"cif", "predictor"}


def test_score_and_rank_requires_ranker_and_hashes() -> None:
    schema = tool_by_name(TOOL_SCORE_AND_RANK)["input_schema"]
    assert set(schema["required"]) == {"ranker", "structure_hashes"}
    assert schema["properties"]["structure_hashes"]["type"] == "array"


def test_query_cache_has_optional_args_only() -> None:
    """structure_hash and run_id are both optional at the schema level;
    dispatcher enforces 'at least one' at call time."""
    schema = tool_by_name(TOOL_QUERY_CACHE)["input_schema"]
    assert schema["required"] == []
    assert "structure_hash" in schema["properties"]
    assert "run_id" in schema["properties"]


# ----- accessors ----------------------------------------------------------


def test_tool_by_name_returns_full_dict() -> None:
    tool = tool_by_name(TOOL_PREDICT)
    assert tool["name"] == TOOL_PREDICT
    assert "input_schema" in tool


def test_tool_by_name_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError) as exc:
        tool_by_name("not_a_real_tool")
    assert "not_a_real_tool" in str(exc.value)
    # Lists what's actually available -- helps catch typos in caller code.
    for canonical in CANONICAL_NAMES:
        assert canonical in str(exc.value)
