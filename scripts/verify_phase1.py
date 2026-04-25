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
    print("\n[4/4] Registry implemented; logging+config still scaffolded")
    from crucible.core import config as cfg
    from crucible.core import logging as crl
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

    try:
        cfg.load_config("anything")
        all_ok &= _check("config.load_config raises NotImplementedError", False,
                         "silently succeeded — implementation slipped through")
    except NotImplementedError:
        all_ok &= _check("config.load_config raises NotImplementedError", True)

    try:
        crl.setup_logging("r1", "./runs")
        all_ok &= _check("logging.setup_logging raises NotImplementedError", False)
    except NotImplementedError:
        all_ok &= _check("logging.setup_logging raises NotImplementedError", True)

    # ------------------------------------------------------------------
    print()
    if all_ok:
        print("All Phase 1 checks passed.")
        return 0
    print("FAILURES detected — see [FAIL] lines above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
