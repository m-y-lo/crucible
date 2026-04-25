# Phase 1 — Two-Person Split

Coordination doc for Ming and Ani working Phase 1 in parallel. **Both agents (Ming's and Ani's) should read this before claiming a file.** See `ARCHITECTURE.md` for the design and `TODO.md` for the master task list. This file determines *who* writes *what*, in *what order*.

## Principle (from `playbook.md` §1)

Do not edit the same file concurrently. Branch off `main` per task, merge as soon as it works locally with a test, pull `main` before starting the next branch.

---

## The blocker — write first, unblock everything

Almost every Phase 1 file imports from these two modules, so Ming writes them first while Ani works on no-dependency files:

1. `crucible/core/models.py` — dataclasses (`Structure`, `Prediction`, `Job`, `Result`, `ModelProvenance`). Spec in `ARCHITECTURE.md` §3.
2. `crucible/core/protocols.py` — Protocol contracts (`Generator`, `Relaxer`, `Predictor`, `Ranker`, `Orchestrator`, `JobQueue`, `ResultStore`). Spec in `ARCHITECTURE.md` §3.

**Sync point:** Ming pings Ani when both land on `main`. Ani then unlocks the dependent items in their track.

---

## Ming's track — foundation / infrastructure

Owned files (in order). Ming's agent does not touch any file outside this list.

1. `crucible/core/models.py` — **write first, push, ping Ani**
2. `crucible/core/protocols.py` — **write second, push, ping Ani**
3. `crucible/core/registry.py` — `importlib.metadata` entry-point loader. Spec in `ARCHITECTURE.md` §5.
4. `crucible/core/config.py` — pydantic schema for `crucible.yaml`. Reference: `crucible.yaml.example`.
5. `crucible/core/logging.py` — JSON-line logger to `runs/{run_id}/events.jsonl` + rich console.
6. `crucible/stores/sqlite_store.py` — `LocalStore`. Schema in `ARCHITECTURE.md` §4.
7. `crucible/queues/local_queue.py` — `LocalQueue` over the `jobs` table + `asyncio.Event`.
8. `tests/test_registry.py` — entry-point discovery test.

---

## Ani's track — domain / gauntlet

Ani's agent does not touch any file outside this list.

**Start immediately (zero deps on Ming's foundation):**

1. `crucible/core/units.py` — eV, eV/atom, GPa, Å constants + safe converters. Pure constants.
2. `crucible/core/hashing.py` — canonical primitive-cell sha256 + AFLOW prototype label via pymatgen.
3. `crucible/data/mp_client.py` — cached `pymatgen.MPRester` (mp-api) wrapper. Requires `MP_API_KEY`.
4. `crucible/gauntlet/parse.py` — CIF → `pymatgen.Structure`.
5. `crucible/gauntlet/composition.py` — reduced formula + `BVAnalyzer` charge balance.
6. `crucible/gauntlet/geometry.py` — nearest-neighbor and volume sanity.
7. `tests/test_units.py`, `tests/test_hashing.py`, `tests/test_gauntlet.py`.

**Pick up after Ming's blocker lands** (these need `Structure` from `models.py`):

8. `crucible/gauntlet/novelty.py` — Materials Project novelty filter (uses `mp_client.py` from above).
9. `crucible/gauntlet/dedup.py` — coarse + `StructureMatcher` fallback.
10. `crucible/gauntlet/pipeline.py` — composes stages with early exit + `gauntlet_events` writes.

---

## Defer until both tracks merge

Single-person work after Ming's track and Ani's track both land. Whoever finishes first picks up:

- `predictors/alignn.py`, `relaxers/alignn_ff.py`
- `generators/crystallm.py`, `generators/random_baseline.py`
- `rankers/battery_cathode.py`
- `agents/tools.py`, `agents/prompts.py`
- `orchestrators/claude_tools.py`
- `cli.py` (wire subcommands), `reports/status.py`
- End-to-end smoke test: `crucible run --budget 20` produces ≥1 row in `rankings`.

---

## Files to coordinate on (single-edit)

These are touched by both tracks. **Before editing, pull `main`. After editing, push immediately and tell the other person.**

- `pyproject.toml` — every new plugin adds a `[project.entry-points."crucible.<kind>"]` line.
- `TODO.md` — both will tick items off as they land.
- `phase1.md` — this file. Update if scope shifts.

If a conflict appears, it's a signal someone violated the file-ownership rule above. Resolve by hand and re-state the boundary.

---

## Branching cadence

One feature branch per file or tightly-related pair:

- Ming: `feature/core-models`, `feature/core-protocols`, `feature/core-registry`, `feature/sqlite-store`, …
- Ani: `feature/units`, `feature/hashing`, `feature/mp-client`, `feature/gauntlet-parse`, …

Merge to `main` as soon as it works locally + has a test. Don't let a branch live longer than a few hours.

---

## Daily sync surface

A 30-second status check via chat or in-person:

- What did I just merge?
- What am I picking up next?
- Anything blocking me on the other person?

That's it. Avoid scope creep into the other track without renegotiating this file.
