"""Default ``Orchestrator`` — Anthropic tool-use loop on Claude Sonnet 4.6.

Drives the discovery loop by:

  1. Sending Claude the system prompt + tool schemas + initial framing.
  2. On each ``tool_use`` response, dispatching the call to a registry-
     loaded plugin (or in-memory query for ``query_cache``).
  3. Feeding the result back as a ``tool_result`` block.
  4. Looping until Claude says ``end_turn``, the predict-budget is
     exhausted, or ``max_iterations`` is hit.

This is the canonical Phase 1 orchestrator. Volunteers in Phase 3 will
use ``RuleBasedOrchestrator`` instead so they do not need an Anthropic
key. Both implementations satisfy the same protocol; nothing else in the
code base cares which is in use (per playbook §G).

Per-run state is held in-memory (not persisted to ``LocalStore``) for
the MVP: a hash -> CIF map, hash -> Structure map, and hash ->
predictions map. The store integration lands in Phase 2 once the
predictor stack stabilizes.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from crucible.agents.prompts import initial_user_message, system_prompt
from crucible.agents.tools import (
    TOOLS,
    TOOL_GENERATE_STRUCTURES,
    TOOL_PREDICT,
    TOOL_QUERY_CACHE,
    TOOL_RELAX,
    TOOL_SCORE_AND_RANK,
)
from crucible.core.hashing import hash_structure, prototype_label_of
from crucible.core.models import (
    ModelProvenance,
    Prediction as CorePrediction,
    Structure as CoreStructure,
)
from crucible.core.registry import load as registry_load
from crucible.data.mp_client import MPClient
from crucible.gauntlet.dedup import Deduplicator
from crucible.gauntlet.pipeline import GauntletResult, run_gauntlet
from crucible.rankers.battery_cathode import (
    LITHIUM_FRACTION_KEY,
    lithium_fraction,
)
from crucible.stores.sqlite_store import LocalStore


# ---------------------------------------------------------------------------
# Per-run state
# ---------------------------------------------------------------------------


@dataclass
class _RunState:
    """In-memory bookkeeping for one ``run`` invocation."""

    run_id: str
    target: str
    budget: int
    cifs: dict[str, str] = field(default_factory=dict)              # hash -> cif
    structures: dict[str, Structure] = field(default_factory=dict)  # hash -> Structure
    predictions: dict[str, dict[str, float]] = field(default_factory=dict)
    rankings: list[dict[str, Any]] = field(default_factory=list)
    predict_count: int = 0
    deduplicator: Deduplicator = field(default_factory=Deduplicator)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ClaudeOrchestrator:
    """Anthropic tool-use orchestrator.

    Construct with explicit deps for testability; call :meth:`run` to
    drive a discovery loop.
    """

    name = "claude_tools"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_iterations: int = 20,
        max_tokens: int = 4096,
        mp_client: MPClient | None = None,
        skip_novelty: bool = False,
        client: Any | None = None,
        store: LocalStore | None = None,
    ) -> None:
        # ``client`` injection makes the orchestrator testable without a
        # real Anthropic key. When None, we construct one from
        # ANTHROPIC_API_KEY (set explicitly here so the failure message
        # is ours, not the SDK's).
        self._client = client
        if self._client is None:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not key:
                # Defer the import so unit tests with an injected client
                # do not require ``anthropic`` to read a real key at
                # construction time.
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set and no client injected; "
                    "either export the key or construct with client=..."
                )
            from anthropic import Anthropic
            self._client = Anthropic(api_key=key)

        self._model = model
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._mp_client = mp_client
        self._skip_novelty = skip_novelty
        if not skip_novelty and mp_client is None:
            raise ValueError(
                "novelty stage enabled but no mp_client passed; "
                "either provide one or set skip_novelty=True"
            )
        # Optional persistent store. When None, the orchestrator runs in
        # the in-memory-only Phase 1 mode (no SQLite writes); when set,
        # every gauntlet event, structure, prediction, and ranking is
        # persisted alongside the run row.
        self._store = store

    # ------------------------------------------------------------------ run

    def run(self, target: str, budget: int) -> str:
        """Drive a full discovery loop. Returns a generated ``run_id``."""
        if budget <= 0:
            raise ValueError(f"budget must be positive, got {budget}")

        state = _RunState(run_id=uuid.uuid4().hex, target=target, budget=budget)
        if self._store is not None:
            self._store.insert_run(
                run_id=state.run_id, target=target, budget=budget
            )

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": initial_user_message(target, budget)}
        ]

        for _ in range(self._max_iterations):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt(),
                tools=TOOLS,
                messages=messages,
            )

            # Persist Claude's reply unconditionally so the next turn has
            # the conversation context.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self._dispatch(block.name, block.input or {}, state)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

            if state.predict_count >= state.budget:
                # Budget reached. Tell Claude to wrap up; if it issues
                # more tool_use after this, we stop on the next iteration
                # check anyway via max_iterations.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Budget exhausted ({state.predict_count}/"
                            f"{state.budget} predictions used). Produce a "
                            "final summary of the top candidates and stop."
                        ),
                    }
                )

        if self._store is not None:
            self._store.mark_run_ended(state.run_id)
        return state.run_id

    # ----------------------------------------------------------- dispatcher

    def _dispatch(self, name: str, args: dict[str, Any], state: _RunState) -> str:
        """Route a tool_use block to its handler. Returns a JSON string
        suitable for use as a ``tool_result.content`` value.

        Errors from plugins are caught and returned as JSON
        ``{"error": "..."}`` so the loop survives missing plugins,
        malformed inputs, and transient failures.
        """
        try:
            if name == TOOL_GENERATE_STRUCTURES:
                payload = self._handle_generate_structures(args, state)
            elif name == TOOL_RELAX:
                payload = self._handle_relax(args, state)
            elif name == TOOL_PREDICT:
                payload = self._handle_predict(args, state)
            elif name == TOOL_SCORE_AND_RANK:
                payload = self._handle_score_and_rank(args, state)
            elif name == TOOL_QUERY_CACHE:
                payload = self._handle_query_cache(args, state)
            else:
                payload = {"error": f"unknown tool {name!r}"}
        except Exception as e:  # noqa: BLE001 - surface to Claude, do not crash the loop
            payload = {"error": f"{type(e).__name__}: {e}"}
        return json.dumps(payload, default=str)

    # ------------------------------------------------------------ handlers

    def _handle_generate_structures(
        self, args: dict[str, Any], state: _RunState
    ) -> dict[str, Any]:
        generator_name = args["generator"]
        n = int(args["n"])
        conditions = args.get("conditions")

        gen = registry_load("generator", generator_name)
        raw_cifs = gen.sample(n, conditions=conditions)

        survivors: list[dict[str, str]] = []
        rejection_counts: dict[str, int] = {}
        for cif in raw_cifs:
            result: GauntletResult = run_gauntlet(
                cif,
                mp_client=self._mp_client,
                deduplicator=state.deduplicator,
                skip_novelty=self._skip_novelty,
            )

            # Persist every stage outcome so `crucible status` can render
            # the rejection histogram.
            if self._store is not None:
                for ev in result.events:
                    self._store.insert_gauntlet_event(
                        run_id=state.run_id,
                        stage=ev.stage,
                        passed=ev.passed,
                        reason=ev.reason,
                        structure_hash=ev.structure_hash,
                    )

            if result.passed:
                # ``GauntletResult.structure_hash`` is set when dedup ran;
                # fall back to recomputing if a future stage shifts that.
                h = result.structure_hash or hash_structure(result.structure)
                state.cifs[h] = cif
                if result.structure is not None:
                    state.structures[h] = result.structure
                survivors.append({"structure_hash": h, "cif": cif})

                # Persist the survivor as a structures-table row so
                # rankings have a foreign-key target.
                if self._store is not None and result.structure is not None:
                    self._persist_structure(
                        h,
                        cif,
                        result.structure,
                        result.prototype_label,
                        result.composition_formula,
                        generator_name,
                        state.run_id,
                    )
            else:
                stage = result.rejected_at or "unknown"
                rejection_counts[stage] = rejection_counts.get(stage, 0) + 1

        return {
            "generator": generator_name,
            "requested": n,
            "survivors": survivors,
            "rejected_counts": rejection_counts,
        }

    def _persist_structure(
        self,
        structure_hash: str,
        cif: str,
        pmg_structure: Structure,
        prototype: str | None,
        composition: str | None,
        source_generator: str,
        run_id: str,
    ) -> None:
        """Build a ``crucible.core.models.Structure`` and persist it.

        Computes any missing metadata (prototype label, composition,
        space group) from the pymatgen Structure on the fly. Idempotent
        via the store's ``INSERT OR IGNORE``.
        """
        if self._store is None:
            return
        try:
            sg = SpacegroupAnalyzer(pmg_structure, symprec=1e-3).get_space_group_number()
        except Exception:
            sg = 0
        proto = prototype or prototype_label_of(pmg_structure)
        comp = composition or pmg_structure.composition.reduced_formula
        record = CoreStructure(
            cif=cif,
            structure_hash=structure_hash,
            prototype_label=proto,
            composition=comp,
            space_group=int(sg),
            source_generator=source_generator,
            source_run_id=run_id,
        )
        self._store.insert_structure(record)

    def _handle_relax(self, args: dict[str, Any], state: _RunState) -> dict[str, Any]:
        relaxer_name = args["relaxer"]
        cif = args["cif"]
        max_steps = int(args.get("max_steps", 200))

        relaxer = registry_load("relaxer", relaxer_name)
        relaxed_cif, total_energy_eV = relaxer.relax(cif, max_steps=max_steps)
        return {
            "relaxer": relaxer_name,
            "relaxed_cif": relaxed_cif,
            "total_energy_eV": float(total_energy_eV),
        }

    def _handle_predict(
        self, args: dict[str, Any], state: _RunState
    ) -> dict[str, Any]:
        predictor_name = args["predictor"]
        cif = args["cif"]

        predictor = registry_load("predictor", predictor_name)
        props = predictor.predict(cif)
        provenance: ModelProvenance | None = getattr(predictor, "provenance", None)

        # Cache by structure_hash so score_and_rank can find them later.
        try:
            structure = Structure.from_str(cif, fmt="cif")
            h = hash_structure(structure)
            state.cifs.setdefault(h, cif)
            state.structures.setdefault(h, structure)
            existing = state.predictions.setdefault(h, {})
            existing.update({k: float(v) for k, v in props.items()})
        except Exception:
            # Hashing failed; report the predictions but skip caching.
            h = None

        # Persist the prediction. We need the structure row to exist
        # already (FK target). If predict was called on a CIF the
        # gauntlet has not yet seen, we lazily insert a stub structures
        # row first.
        if self._store is not None and h is not None and provenance is not None:
            self._persist_structure(
                h,
                cif,
                state.structures[h],
                None,
                None,
                source_generator="predict_call",
                run_id=state.run_id,
            )
            self._store.insert_prediction(
                CorePrediction(
                    structure_hash=h,
                    provenance=provenance,
                    values={k: float(v) for k, v in props.items()},
                    latency_ms=0,
                )
            )

        state.predict_count += 1
        return {
            "predictor": predictor_name,
            "structure_hash": h,
            "predictions": {k: float(v) for k, v in props.items()},
        }

    def _handle_score_and_rank(
        self, args: dict[str, Any], state: _RunState
    ) -> dict[str, Any]:
        ranker_name = args["ranker"]
        hashes = args.get("structure_hashes") or []

        ranker = registry_load("ranker", ranker_name)
        # Ranker plugins may carry a `version` attribute; default if not.
        ranker_version = str(getattr(ranker, "version", "1.0"))
        out = []
        for h in hashes:
            props = dict(state.predictions.get(h, {}))
            structure = state.structures.get(h)
            if structure is not None and LITHIUM_FRACTION_KEY not in props:
                props[LITHIUM_FRACTION_KEY] = lithium_fraction(structure)

            passes = bool(ranker.criteria(props))
            score_value = float(ranker.score(props)) if passes else 0.0
            row = {
                "structure_hash": h,
                "passes": passes,
                "score": score_value,
                "props_used": props,
            }
            out.append(row)
            if passes:
                state.rankings.append({**row, "ranker": ranker_name})

            if self._store is not None:
                self._store.insert_ranking(
                    structure_hash=h,
                    run_id=state.run_id,
                    target=state.target,
                    ranker_name=ranker_name,
                    ranker_version=ranker_version,
                    passes_criteria=passes,
                    score=score_value if passes else None,
                    reasoning_json=json.dumps({"props_used": props}),
                )
        return {"ranker": ranker_name, "results": out}

    def _handle_query_cache(
        self, args: dict[str, Any], state: _RunState
    ) -> dict[str, Any]:
        h = args.get("structure_hash")
        run_id = args.get("run_id")
        limit = int(args.get("limit", 100))
        if not h and not run_id:
            return {"error": "supply structure_hash or run_id"}

        if h:
            return {
                "structure_hash": h,
                "have_cif": h in state.cifs,
                "predictions": state.predictions.get(h, {}),
            }
        # run_id branch: only the current run is cached in-memory in MVP.
        if run_id == state.run_id:
            ranked = sorted(
                state.rankings, key=lambda r: r["score"], reverse=True
            )
            return {"run_id": run_id, "rankings": ranked[:limit]}
        return {"run_id": run_id, "rankings": []}
