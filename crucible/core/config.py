"""Pydantic schema for `crucible.yaml`.

Mirrors `crucible.yaml.example`:
    run, generators[], relaxers[], predictors[], ranker, queue, store,
    orchestrator, materials_project.

Top-level entry: `load_config(path) -> CrucibleConfig`.

Every section uses `extra='forbid'` so a typo in YAML (e.g.
`formatation_energy_max_eV_per_atom`) raises `ValidationError` at load
time instead of silently being ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Base for all sections — reject unknown keys to catch YAML typos early."""

    model_config = ConfigDict(extra="forbid")


class RunSection(_Strict):
    """`run:` block — what we are searching for and the spend cap."""

    target: str
    budget: int = Field(ge=1)
    output_dir: Path = Path("./runs")


class PluginEntry(_Strict):
    """A reference to a plugin by registered name + kwargs.

    Used by `generators[]`, `relaxers[]`, `predictors[]`. `weight` is only
    meaningful for generators (sampling proportion); leave at 1.0 elsewhere.
    """

    name: str
    weight: float = 1.0
    options: dict[str, Any] = Field(default_factory=dict)


class RankerSection(_Strict):
    """`ranker:` block — single ranker plugin, target-specific options."""

    name: str
    options: dict[str, Any] = Field(default_factory=dict)


class QueueSection(_Strict):
    """`queue:` block — which `JobQueue` plugin to instantiate."""

    name: str = "local"
    options: dict[str, Any] = Field(default_factory=dict)


class StoreSection(_Strict):
    """`store:` block — which `ResultStore` plugin and its db path."""

    name: str = "sqlite"
    path: Path = Path("./runs/crucible.db")
    options: dict[str, Any] = Field(default_factory=dict)


class OrchestratorSection(_Strict):
    """`orchestrator:` block — which `Orchestrator` plugin and its options."""

    name: str = "claude_tools"
    options: dict[str, Any] = Field(
        default_factory=lambda: {"model": "claude-sonnet-4-6", "max_iterations": 20}
    )


class MaterialsProjectSection(_Strict):
    """`materials_project:` block — MP integration toggles."""

    enabled: bool = True
    novelty_filter: bool = True
    use_seeds: bool = False


class CrucibleConfig(_Strict):
    """Root of `crucible.yaml`.

    Required: `run`, `predictors`, `ranker`. All other sections have
    sensible defaults so a minimal config still validates.
    """

    run: RunSection
    generators: list[PluginEntry] = Field(default_factory=list)
    relaxers: list[PluginEntry] = Field(default_factory=list)
    predictors: list[PluginEntry]
    ranker: RankerSection
    queue: QueueSection = Field(default_factory=QueueSection)
    store: StoreSection = Field(default_factory=StoreSection)
    orchestrator: OrchestratorSection = Field(default_factory=OrchestratorSection)
    materials_project: MaterialsProjectSection = Field(
        default_factory=MaterialsProjectSection
    )


def load_config(path: Path | str) -> CrucibleConfig:
    """Load and validate a YAML config file.

    Raises:
        FileNotFoundError: if `path` does not exist.
        pydantic.ValidationError: on schema mismatch (missing required
            sections, unknown keys, wrong types, out-of-range values).
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    return CrucibleConfig.model_validate(raw)
