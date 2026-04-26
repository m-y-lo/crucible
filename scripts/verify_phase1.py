"""Verify Phase 1's implemented modules and confirm scaffolds still raise.

Single-command sanity check for the state of Ming's track. Run from the
repo root:

    uv run python scripts/verify_phase1.py

Exits 0 if everything is in the expected state, 1 if any check fails.
Useful as a pre-merge gate and for catching accidental regressions while
filling in the rest of Wave 1 / Wave 2.
"""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError

_OK = "OK"
_FAIL = "FAIL"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = _OK if ok else _FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    return ok


def main() -> int:
    all_ok = True

    # ------------------------------------------------------------------
    print("\n[1/4] Imports load cleanly (implemented and scaffolded modules)")
    for modname in [
        "crucible",
        "crucible.core.models",
        "crucible.core.protocols",
        "crucible.core.registry",
        "crucible.core.config",
        "crucible.core.logging",
        "crucible.stores.sqlite_store",
        "crucible.queues.local_queue",
    ]:
        try:
            __import__(modname)
            all_ok &= _check(modname, True)
        except Exception as e:
            all_ok &= _check(modname, False, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    print("\n[2/4] Dataclass invariants (frozen guards, tz-aware timestamps, slots)")
    from crucible.core.models import Job, ModelProvenance, Structure

    mp = ModelProvenance(
        model_id="alignn",
        checkpoint="jv_form_e",
        dataset="JARVIS-DFT",
        version="2026.5",
        units={"formation_energy_eV_per_atom": "eV/atom"},
    )
    s = Structure(
        cif="dummy",
        structure_hash="abc",
        prototype_label="AB_oP4",
        composition="LiCoO2",
        space_group=166,
        source_generator="crystallm",
        source_run_id="r1",
    )

    all_ok &= _check("Structure.created_at is tz-aware (UTC)", s.created_at.tzinfo is not None)

    try:
        s.cif = "mutated"
        all_ok &= _check("Structure rejects mutation (frozen)", False, "no exception raised")
    except FrozenInstanceError:
        all_ok &= _check("Structure rejects mutation (frozen)", True)

    try:
        s.bogus = "x"
        all_ok &= _check("Structure rejects undeclared attrs (slots)", False)
    except (AttributeError, TypeError):
        all_ok &= _check("Structure rejects undeclared attrs (slots)", True)

    j = Job(job_id="j1", kind="predict", payload={}, run_id="r1")
    j.attempts += 1
    all_ok &= _check("Job is mutable (attempts increments)", j.attempts == 1)

    all_ok &= _check("ModelProvenance carries units mapping",
                     mp.units == {"formation_energy_eV_per_atom": "eV/atom"})

    # ------------------------------------------------------------------
    print("\n[3/4] Protocols — runtime_checkable accepts/rejects by shape")
    from crucible.core.protocols import Ranker

    class _GoodRanker:
        name = "good"
        target = "demo"
        def criteria(self, props): return True
        def score(self, props): return 1.0

    class _BadRanker:
        name = "bad"
        # missing target, criteria, score on purpose

    all_ok &= _check("isinstance(GoodRanker(), Ranker) is True",
                     isinstance(_GoodRanker(), Ranker))
    all_ok &= _check("isinstance(BadRanker(), Ranker) is False",
                     not isinstance(_BadRanker(), Ranker))

    # ------------------------------------------------------------------
    print("\n[4/5] Registry — implemented")
    from crucible.core.registry import GROUPS, list_plugins

    all_ok &= _check("GROUPS has 7 plugin kinds", len(GROUPS) == 7,
                     f"kinds: {sorted(GROUPS)}")
    all_ok &= _check("list_plugins('ranker') == [] (none registered yet)",
                     list_plugins("ranker") == [])

    try:
        list_plugins("not_a_kind")
        all_ok &= _check("list_plugins('not_a_kind') raises KeyError", False)
    except KeyError:
        all_ok &= _check("list_plugins('not_a_kind') raises KeyError", True)

    # ------------------------------------------------------------------
    print("\n[5/5] Logging + Config + Store + Queue — implemented")
    import asyncio
    import json
    import logging as _stdlib_logging
    import tempfile
    from pathlib import Path

    from crucible.core.config import CrucibleConfig, load_config
    from crucible.core.logging import log_event, setup_logging

    # config: real load against the committed example
    repo_root = Path(__file__).resolve().parent.parent
    example_yaml = repo_root / "crucible.yaml.example"
    cfg = load_config(example_yaml)
    all_ok &= _check("load_config(crucible.yaml.example) returns CrucibleConfig",
                     isinstance(cfg, CrucibleConfig))
    all_ok &= _check(f"  config.run.target == 'battery_cathode'",
                     cfg.run.target == "battery_cathode")
    all_ok &= _check(f"  config.orchestrator.options['model'] == 'claude-sonnet-4-6'",
                     cfg.orchestrator.options["model"] == "claude-sonnet-4-6")

    # logging: write a smoke event to a tmp dir, parse it back as JSON
    with tempfile.TemporaryDirectory() as td:
        # Reset shared 'crucible' logger so this run is isolated.
        _logger = _stdlib_logging.getLogger("crucible")
        for h in list(_logger.handlers):
            h.close(); _logger.removeHandler(h)

        logger = setup_logging("verify_smoke", td)
        log_event(logger, stage="smoke", structure_hash="abc", passed=True)
        events = Path(td) / "verify_smoke" / "events.jsonl"
        all_ok &= _check("setup_logging created events.jsonl", events.exists())
        rec = json.loads(events.read_text().splitlines()[-1])
        all_ok &= _check("event has required envelope fields",
                         {"ts", "level", "logger", "run_id", "stage"}.issubset(rec))
        all_ok &= _check("event['stage'] round-trips", rec["stage"] == "smoke")
        # cleanup
        for h in list(logger.handlers):
            h.close(); logger.removeHandler(h)

    # store + queue: smoke their concrete implementations
    from crucible.core.models import Prediction, Result
    from crucible.queues.local_queue import LocalQueue
    from crucible.stores.sqlite_store import LocalStore

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "crucible.db"
        store = LocalStore(db_path)
        try:
            store.insert_structure(s)
            store.insert_prediction(Prediction(
                structure_hash=s.structure_hash,
                provenance=mp,
                values={"formation_energy_eV_per_atom": -1.0},
                latency_ms=1,
            ))
            all_ok &= _check("stores.LocalStore round-trips Structure",
                             store.get_by_hash(s.structure_hash) == s)
            all_ok &= _check("stores.LocalStore dedup finds known structure",
                             store.dedup_against_known(s) == s.structure_hash)
        finally:
            store.close()

    async def _queue_smoke() -> bool:
        with tempfile.TemporaryDirectory() as td:
            queue = LocalQueue(Path(td) / "crucible.db")
            try:
                await queue.enqueue(Job(job_id="jq1", kind="predict", payload={"x": 1}, run_id="r1"))
                got = await queue.dequeue(["predict"])
                if got is None or got.job_id != "jq1" or got.payload != {"x": 1}:
                    return False
                await queue.mark_done("jq1", Result(job_id="jq1", ok=True, payload={"ok": True}))
                result = await queue.get_result("jq1")
                return result is not None and result.ok and result.payload == {"ok": True}
            finally:
                await queue.close()

    all_ok &= _check("queues.LocalQueue enqueue/dequeue/result smoke",
                     asyncio.run(_queue_smoke()))

    # ------------------------------------------------------------------
    print()
    if all_ok:
        print("All Phase 1 checks passed.")
        return 0
    print("FAILURES detected — see [FAIL] lines above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
