"""Pydantic schema for `crucible.yaml`.

Mirrors `crucible.yaml.example`:
    run, generators[], relaxers[], predictors[], ranker, queue, store,
    orchestrator, materials_project.

Top-level entry: `load_config(path) -> CrucibleConfig`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Base for all sections — reject unknown keys to catch YAML typos early."""

    model_config = ConfigDict(extra="forbid")


class RunSection(_Strict):
    """`run:` block — what we are searching for and the spend cap."""

    # TODO Wave 1:
    #   target: str                        # ranker plugin name, e.g. "battery_cathode"
    #   budget: int = Field(ge=1)          # max structures fully predicted
    #   output_dir: Path = Path("./runs")


class PluginEntry(_Strict):
    """A reference to a plugin by registered name + kwargs.

    Used by generators[], relaxers[], predictors[]. `weight` only meaningful
    for generators (sampling proportion) — leave as 1.0 elsewhere.
    """

    # TODO Wave 1:
    #   name: str
    #   weight: float = 1.0
    #   options: dict[str, Any] = Field(default_factory=dict)


class RankerSection(_Strict):
    """`ranker:` block — single ranker, target-specific options."""

    # TODO Wave 1:
    #   name: str
    #   options: dict[str, Any] = Field(default_factory=dict)


class QueueSection(_Strict):
    """`queue:` block — which `JobQueue` plugin to instantiate."""

    # TODO Wave 1: name: str = "local"; options: dict[str, Any] = {}


class StoreSection(_Strict):
    """`store:` block — which `ResultStore` plugin and its db path."""

    # TODO Wave 1:
    #   name: str = "sqlite"
    #   path: Path = Path("./runs/crucible.db")
    #   options: dict[str, Any] = Field(default_factory=dict)


class OrchestratorSection(_Strict):
    """`orchestrator:` block — which `Orchestrator` plugin and its options."""

    # TODO Wave 1:
    #   name: str = "claude_tools"
    #   options: dict[str, Any] = {"model": "claude-sonnet-4-6", "max_iterations": 20}


class MaterialsProjectSection(_Strict):
    """`materials_project:` block — MP integration toggles."""

    # TODO Wave 1:
    #   enabled: bool = True
    #   novelty_filter: bool = True
    #   use_seeds: bool = False


class CrucibleConfig(_Strict):
    """Root of `crucible.yaml`."""

    # TODO Wave 1:
    #   run: RunSection
    #   generators: list[PluginEntry] = Field(default_factory=list)
    #   relaxers: list[PluginEntry] = Field(default_factory=list)
    #   predictors: list[PluginEntry]
    #   ranker: RankerSection
    #   queue: QueueSection = QueueSection()
    #   store: StoreSection = StoreSection()
    #   orchestrator: OrchestratorSection = OrchestratorSection()
    #   materials_project: MaterialsProjectSection = MaterialsProjectSection()


def load_config(path: Path | str) -> CrucibleConfig:
    """Load + validate a YAML config file.

    Raises pydantic.ValidationError on schema mismatch, FileNotFoundError on
    missing file. Any unknown YAML key is a hard error (extra='forbid').
    """
    # TODO Wave 1:
    #   import yaml
    #   raw = yaml.safe_load(Path(path).read_text())
    #   return CrucibleConfig.model_validate(raw)
    raise NotImplementedError
