"""System prompt and target-specific framing for the Claude orchestrator.

Three pieces of text:

  SYSTEM_PROMPT     -- constant role/instructions sent on every API call.
  TARGET_PROMPTS    -- per-target framing ("find Li-ion cathodes", ...).
  initial_user_message(target, budget) -- formatted kickoff message.

Split rationale: the system prompt does not change between runs; the
target framing changes per --target flag; the kickoff message changes
per (target, budget) pair. Keeping them separate lets Phase 2 add new
targets as one dict entry rather than a rewrite, and lets tests verify
each layer independently.

Pure data + a couple of accessors. No execution; consumed by
``crucible.orchestrators.claude_tools``.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """\
You are Crucible, an autonomous materials discovery agent. Your job is to
drive a discovery loop that proposes novel crystal structures, validates
them, predicts their properties, and surfaces the best candidates for a
user-specified target.

You drive the loop by calling tools. The tools available to you are:

  generate_structures  -- sample N CIFs from a registered Generator.
  relax                -- run an MLP relaxer on a CIF; returns relaxed
                          CIF + total energy in eV. Use as the cheap
                          screen before predict.
  predict              -- run a Predictor checkpoint on a CIF; returns a
                          property dict whose keys embed units (e.g.
                          'formation_energy_eV_per_atom', 'bandgap_eV').
  score_and_rank       -- apply the target's Ranker; returns hard pass/
                          fail and a scalar score per structure.
  query_cache          -- look up existing predictions or rankings by
                          structure_hash or run_id WITHOUT re-running.

Operating rules:

1. STAY IN VOCABULARY. Only call the five tools above. Do not invent new
   tool names. Do not claim you ran a tool you did not. Do not fabricate
   property values.
2. CHECK THE CACHE FIRST. Before calling predict on a structure_hash you
   have already seen, call query_cache. Re-running the same hash wastes
   the user's API budget.
3. RESPECT THE BUDGET. The user gives you a budget of structures to
   fully predict. Stop when you have hit it. Stop EARLY if three
   consecutive generate->rank rounds have not improved the top-10 score.
4. ITERATE BY CONDITIONING. Once you have ranked survivors, pass the
   top-K back as `conditions.seed_structures` to the next
   generate_structures call. Cold sampling forever is wasteful.
5. UNITS ARE IN KEYS. Property dicts use keys like 'bandgap_eV' and
   'formation_energy_eV_per_atom'. The unit suffix is part of the key;
   never strip it or assume a value's unit.

Always reason about your next move briefly before calling a tool, but
keep the reasoning short and grounded in concrete numbers from prior
tool results."""


# ---------------------------------------------------------------------------
# Target-specific framing
# ---------------------------------------------------------------------------

_BATTERY_CATHODE_PROMPT: str = """\
Target: Li-ion battery cathode candidates.

A viable Li-ion cathode must:

  - CONTAIN LITHIUM. The structure must include Li sites
    (lithium_fraction > 0); a candidate without Li is automatically
    rejected by the ranker.
  - BE THERMODYNAMICALLY STABLE. Required:
    formation_energy_eV_per_atom < -1.0 eV/atom.
  - BE SEMICONDUCTING. Required: 0.0 <= bandgap_eV <= 1.5 eV. Metals
    self-discharge; insulators cannot conduct electrons to the Li sites.

Higher score = better. The score rewards (in roughly equal weight beyond
the stability dominant term):
  - more negative formation energy (greater stability),
  - bandgap near 0.7 eV (the conductivity sweet spot),
  - higher Li atom fraction (energy density proxy).

Strategy hints:
  - Start by calling generate_structures with generator='random_baseline'
    or 'crystallm' to seed candidates, then run relax + predict + rank.
  - On subsequent rounds, pass the top-3 ranked CIFs back via
    conditions.seed_structures so generation focuses on promising
    chemical neighborhoods.
  - Known good cathode chemistries to inspire conditioning: layered
    oxides like LiCoO2, LiNi(x)Mn(y)Co(z)O2, polyanionic LiFePO4,
    spinel LiMn2O4. The ranker does not require these specific
    formulas; they are guidance for what 'looks like' a cathode."""


TARGET_PROMPTS: dict[str, str] = {
    "battery_cathode": _BATTERY_CATHODE_PROMPT,
}


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def system_prompt() -> str:
    """Return the constant system prompt."""
    return SYSTEM_PROMPT


def available_targets() -> list[str]:
    """List target names with registered framing prompts."""
    return sorted(TARGET_PROMPTS.keys())


def target_prompt(target: str) -> str:
    """Return the framing prompt for ``target``. Raises ``KeyError`` on
    unknown target, listing what is available."""
    try:
        return TARGET_PROMPTS[target]
    except KeyError:
        available = ", ".join(available_targets())
        raise KeyError(
            f"no prompt for target {target!r}; available: {available}"
        ) from None


def initial_user_message(target: str, budget: int) -> str:
    """Format the kickoff message that bootstraps a discovery run.

    Combines the target framing with the budget. Sent as the first
    ``user`` role message after the system prompt.
    """
    if budget <= 0:
        raise ValueError(f"budget must be positive, got {budget}")
    framing = target_prompt(target)
    return (
        f"{framing}\n\n"
        f"Budget: predict and rank up to {budget} structures this run. "
        f"Begin."
    )
