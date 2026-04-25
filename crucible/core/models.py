"""Dataclasses crossing module boundaries with explicit units.

See ARCHITECTURE.md §3 for the contract. Key invariants:

- Every prediction carries a `ModelProvenance` (model_id, checkpoint, dataset,
  version, units). The SQLite UNIQUE constraint
  `(structure_hash, model_id, checkpoint, version)` depends on `version`
  changing whenever the model's behavior changes (bug fix, retrained
  checkpoint, library bump).
- Property keys MUST embed units (`'formation_energy_eV_per_atom'`,
  `'bandgap_eV'`, `'bulk_modulus_GPa'`). Enforced by code review today;
  Phase 2 may add a runtime validator.
- This module is intentionally pymatgen-free so it stays cheap to import.
  Structure construction (canonicalization + hashing) lives in
  `crucible.core.hashing`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    """Identifies a specific predictor or relaxer checkpoint and its conventions.

    `units` is keyed by property name and must agree with the keys a
    `Predictor` puts into `Prediction.values`. Frozen because mutating it
    after the fact would silently break the predictions UNIQUE constraint.
    """

    model_id: str
    checkpoint: str
    dataset: str
    version: str
    units: dict[str, str]


@dataclass(frozen=True, slots=True)
class Structure:
    """A canonicalized crystal structure with its content hash.

    `cif` is the canonical primitive-cell text; `structure_hash` is sha256
    over that canonical text. `prototype_label` is the AFLOW prototype
    string used as a coarse dedup key.
    """

    cif: str
    structure_hash: str
    prototype_label: str
    composition: str
    space_group: int
    source_generator: str
    source_run_id: str
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class Prediction:
    """A single model's prediction set for one structure.

    Keys in `values` MUST embed units. `provenance.units` should cover every
    key present in `values`.
    """

    structure_hash: str
    provenance: ModelProvenance
    values: dict[str, float]
    latency_ms: int
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(slots=True)
class Job:
    """A unit of work in the queue (generate / relax / predict / rank).

    Mutable on purpose: `attempts` increments on retry. `payload` is `dict`
    rather than a typed union because each `kind` has its own shape; the
    dispatcher in `crucible.agents.tools` is responsible for typing it.
    """

    job_id: str
    kind: str
    payload: dict[str, Any]
    run_id: str
    enqueued_at: datetime = field(default_factory=_utcnow)
    attempts: int = 0


@dataclass(slots=True)
class Result:
    """Return value of a worker for one Job.

    `payload` shape mirrors `Job.payload` for the same `kind`.
    """

    job_id: str
    ok: bool
    payload: dict[str, Any]
    error: str | None = None
    worker_id: str | None = None
