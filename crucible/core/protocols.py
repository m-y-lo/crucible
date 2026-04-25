"""Typed Protocol contracts every Crucible plugin must satisfy.

See ARCHITECTURE.md §3. Every plugin is loaded via `crucible.core.registry`
and must satisfy one of the Protocols below. `runtime_checkable` is set so
tests and tool dispatchers can use `isinstance(obj, Predictor)`; static
type-checking via pyright is the primary gate.

Convention for the `name` (and `target`) attributes: declare here as an
instance attribute, define on concrete plugins as a class variable so it
travels with the class without forcing an `__init__`. Example:

    class BatteryCathodeRanker:
        name = "battery_cathode"
        target = "battery_cathode"
        def criteria(self, props): ...
        def score(self, props): ...

This module imports from `crucible.core.models`; the reverse is forbidden.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from crucible.core.models import Job, ModelProvenance, Prediction, Result, Structure


@runtime_checkable
class Generator(Protocol):
    """Proposes novel crystal structures as raw CIF strings.

    Implementations: `generators/crystallm.py`, `generators/random_baseline.py`,
    `generators/mattergen_*.py`.
    """

    name: str

    def sample(self, n: int, conditions: dict | None = None) -> list[str]:
        """Return up to n CIF strings.

        `conditions` is a free-form dict; well-known keys include `elements`
        (list[str]), `target_props` (dict[str, float]), `space_group` (int),
        `seed_structures` (list[Structure]). Implementations document which
        keys they respect.
        """
        ...


@runtime_checkable
class Relaxer(Protocol):
    """Relaxes a CIF using an ML potential and returns relaxed CIF + energy."""

    name: str
    provenance: ModelProvenance

    def relax(self, cif: str, max_steps: int = 200) -> tuple[str, float]:
        """Return `(relaxed_cif, total_energy_eV)`. Total energy in eV — NOT eV/atom."""
        ...


@runtime_checkable
class Predictor(Protocol):
    """Predicts properties for a (preferably relaxed) CIF.

    Per playbook §F: result keys MUST embed units, e.g.
    `'formation_energy_eV_per_atom'`, `'bandgap_eV'`, `'bulk_modulus_GPa'`.
    """

    name: str
    provenance: ModelProvenance

    def predict(self, cif: str) -> dict[str, float]:
        ...


@runtime_checkable
class Ranker(Protocol):
    """Maps predicted props to (a) a hard pass/fail and (b) a scalar score."""

    name: str
    target: str

    def criteria(self, props: dict[str, float]) -> bool:
        """Hard gates. Examples: contains-Li, bandgap < threshold, charge balance."""
        ...

    def score(self, props: dict[str, float]) -> float:
        """Higher is better; only meaningful when `criteria()` returns True."""
        ...


@runtime_checkable
class Orchestrator(Protocol):
    """Drives the discovery loop: when to generate, predict, rank, stop."""

    name: str

    def run(self, target: str, budget: int) -> str:
        """Drive a full discovery loop. Returns the run_id.

        Implementations may use asyncio internally (most will, since
        `JobQueue` is async); the public boundary stays sync to keep the CLI
        simple.
        """
        ...


@runtime_checkable
class JobQueue(Protocol):
    """Durable async queue. `LocalQueue` (aiosqlite) and `HTTPQueue` both implement this."""

    async def enqueue(self, job: Job) -> None: ...

    async def dequeue(self, kinds: list[str]) -> Job | None:
        """Block until a job of one of the given kinds is available, or None on shutdown."""
        ...

    async def mark_done(self, job_id: str, result: Result) -> None: ...

    async def get_result(self, job_id: str) -> Result | None: ...


@runtime_checkable
class ResultStore(Protocol):
    """Synchronous persistence layer.

    `LocalStore` (SQLite) is sync because SQLite writes are fast and many
    call sites in the gauntlet pipeline aren't async. Phase-3 `RemoteStore`
    bridges sync→async with httpx internally.
    """

    def insert_structure(self, s: Structure) -> None: ...

    def insert_prediction(self, p: Prediction) -> None: ...

    def get_by_hash(self, structure_hash: str) -> Structure | None: ...

    def list_by_target(self, target: str, limit: int = 100) -> list[dict]: ...

    def dedup_against_known(self, s: Structure) -> str | None:
        """Return the hash of an existing match in the store, or None if novel."""
        ...

    def materialize_view(self, name: str) -> None:
        """Refresh a named denormalized view (e.g. 'top_battery_cathodes')."""
        ...
