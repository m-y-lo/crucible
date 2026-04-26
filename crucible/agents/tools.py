"""Anthropic tool-use schemas the Claude orchestrator exposes.

Pure data. No execution happens here; this module just declares what the
orchestrator can call. Concrete implementations live in
``crucible.generators``, ``crucible.relaxers``, ``crucible.predictors``,
``crucible.rankers``, and ``crucible.stores``; the dispatcher lives in
``crucible.orchestrators.claude_tools``.

The five tools (per ARCHITECTURE.md section 6):

  generate_structures  - sample N CIFs from a Generator plugin
  relax                - run an MLP relaxer; return relaxed CIF + energy
  predict              - run a Predictor checkpoint; return props dict
  score_and_rank       - apply a Ranker; return pass/fail + score
  query_cache          - look up existing predictions/rankings

Schemas conform to Anthropic's tool-use input format: each tool is a
dict with ``name``, ``description``, and ``input_schema`` (a JSON
Schema describing the arguments). The orchestrator passes the whole
list to ``client.messages.create(tools=TOOLS, ...)``.
"""

from __future__ import annotations

from typing import Any

# Canonical tool names. Exporting these as module-level constants prevents
# the orchestrator and the dispatcher from drifting on spelling.
TOOL_GENERATE_STRUCTURES = "generate_structures"
TOOL_RELAX = "relax"
TOOL_PREDICT = "predict"
TOOL_SCORE_AND_RANK = "score_and_rank"
TOOL_QUERY_CACHE = "query_cache"


TOOLS: list[dict[str, Any]] = [
    {
        "name": TOOL_GENERATE_STRUCTURES,
        "description": (
            "Sample N candidate crystal structures (as CIF text) from a "
            "registered Generator plugin. Use early in the loop to seed "
            "candidates, and again later to generate refined batches "
            "conditioned on top survivors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "generator": {
                    "type": "string",
                    "description": (
                        "Plugin id, e.g. 'random_baseline' or 'crystallm'. "
                        "Must be a name returned by registry.list_plugins('generator')."
                    ),
                },
                "n": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of CIF strings to sample. Hard cap enforced server-side.",
                },
                "conditions": {
                    "type": "object",
                    "description": (
                        "Optional generator-specific conditioning. Recognized "
                        "keys vary by generator; common keys: 'elements', "
                        "'target_props', 'space_group', 'seed_structures' "
                        "(list of CIF strings to perturb / use as prompts)."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["generator", "n"],
        },
    },
    {
        "name": TOOL_RELAX,
        "description": (
            "Run a machine-learned interatomic-potential relaxation on a "
            "CIF and return the relaxed CIF plus its total energy in eV. "
            "Use as the cheap-energy screen before the full Predictor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cif": {
                    "type": "string",
                    "description": "Input CIF text.",
                },
                "relaxer": {
                    "type": "string",
                    "description": (
                        "Plugin id, e.g. 'alignn_ff'. Must be a name returned "
                        "by registry.list_plugins('relaxer')."
                    ),
                },
                "max_steps": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 200,
                    "description": "Max optimization steps.",
                },
            },
            "required": ["cif", "relaxer"],
        },
    },
    {
        "name": TOOL_PREDICT,
        "description": (
            "Predict properties for a CIF using one or more pretrained "
            "Predictor checkpoints. Returns a dict whose keys embed units "
            "(e.g. 'formation_energy_eV_per_atom', 'bandgap_eV') alongside "
            "model provenance. Should be called on relaxed CIFs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cif": {
                    "type": "string",
                    "description": "Input CIF text (preferably already relaxed).",
                },
                "predictor": {
                    "type": "string",
                    "description": (
                        "Plugin id, e.g. 'alignn'. Must be a name returned by "
                        "registry.list_plugins('predictor')."
                    ),
                },
                "checkpoints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional override of which checkpoints to run; "
                        "defaults to whatever the predictor was constructed with."
                    ),
                },
            },
            "required": ["cif", "predictor"],
        },
    },
    {
        "name": TOOL_SCORE_AND_RANK,
        "description": (
            "Apply a target-specific Ranker to a batch of structures. "
            "Returns one record per structure containing the hard pass/fail "
            "from criteria() and a scalar score (higher is better). Only "
            "use after predict has populated the relevant property keys."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ranker": {
                    "type": "string",
                    "description": (
                        "Plugin id, e.g. 'battery_cathode'. Must be a name "
                        "returned by registry.list_plugins('ranker')."
                    ),
                },
                "structure_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of structure_hash values whose predictions "
                        "should be loaded from the cache and scored."
                    ),
                    "minItems": 1,
                },
            },
            "required": ["ranker", "structure_hashes"],
        },
    },
    {
        "name": TOOL_QUERY_CACHE,
        "description": (
            "Look up existing predictions and/or rankings by structure_hash "
            "or run_id without re-running the model. Use to avoid duplicate "
            "compute and to read prior leaderboards."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "structure_hash": {
                    "type": "string",
                    "description": "Look up everything we have for one structure.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Look up the rankings for an entire run.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 100,
                    "description": "Max rows to return when querying a run.",
                },
            },
            # Caller must supply at least one of structure_hash or run_id;
            # JSON Schema's `oneOf` handles that, but the SDK validates
            # `required` strictly, so we leave both optional and validate
            # at dispatch time. Documented here for future reference.
            "required": [],
        },
    },
]


def tool_by_name(name: str) -> dict[str, Any]:
    """Return the schema dict for ``name``. Raises ``KeyError`` on unknown."""
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    available = ", ".join(t["name"] for t in TOOLS)
    raise KeyError(f"unknown tool {name!r}; available: {available}")


def tool_names() -> list[str]:
    """Return the canonical tool names in declaration order."""
    return [t["name"] for t in TOOLS]
