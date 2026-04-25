"""Tests for `crucible.core.config` — pydantic schema for crucible.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from crucible.core.config import CrucibleConfig, load_config

# crucible.yaml.example lives at the repo root, two parents up from this file.
REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_example_config_parses_with_expected_values() -> None:
    """The committed `crucible.yaml.example` is a valid CrucibleConfig."""
    cfg = load_config(REPO_ROOT / "crucible.yaml.example")

    assert cfg.run.target == "battery_cathode"
    assert cfg.run.budget == 200

    assert len(cfg.predictors) == 1
    assert cfg.predictors[0].name == "alignn"
    assert "checkpoints" in cfg.predictors[0].options

    assert cfg.ranker.name == "battery_cathode"
    assert cfg.ranker.options["formation_energy_max_eV_per_atom"] == -1.0

    assert cfg.orchestrator.name == "claude_tools"
    assert cfg.orchestrator.options["model"] == "claude-sonnet-4-6"

    assert cfg.materials_project.enabled is True


def test_minimal_config_uses_defaults(tmp_path: Path) -> None:
    """A YAML with only required sections still validates and fills defaults."""
    minimal = tmp_path / "minimal.yaml"
    minimal.write_text(yaml.safe_dump({
        "run": {"target": "battery_cathode", "budget": 50},
        "predictors": [{"name": "alignn"}],
        "ranker": {"name": "battery_cathode"},
    }))
    cfg = load_config(minimal)
    assert cfg.queue.name == "local"
    assert cfg.store.name == "sqlite"
    assert cfg.orchestrator.name == "claude_tools"
    assert cfg.materials_project.enabled is True
    assert cfg.generators == []
    assert cfg.relaxers == []


def test_extra_keys_rejected_at_top_level(tmp_path: Path) -> None:
    """Unknown top-level YAML keys raise ValidationError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "run": {"target": "x", "budget": 10},
        "predictors": [{"name": "alignn"}],
        "ranker": {"name": "x"},
        "totally_unrelated_key": 1,
    }))
    with pytest.raises(ValidationError):
        load_config(bad)


def test_extra_keys_rejected_inside_section(tmp_path: Path) -> None:
    """Unknown nested keys (the realistic typo path) also raise ValidationError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "run": {"target": "x", "budget": 10, "budgett": 10},  # typo
        "predictors": [{"name": "alignn"}],
        "ranker": {"name": "x"},
    }))
    with pytest.raises(ValidationError):
        load_config(bad)


def test_missing_required_section_raises(tmp_path: Path) -> None:
    """Omitting a required section (e.g. `ranker`) raises ValidationError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "run": {"target": "x", "budget": 10},
        "predictors": [{"name": "alignn"}],
        # ranker missing
    }))
    with pytest.raises(ValidationError):
        load_config(bad)


def test_budget_must_be_positive(tmp_path: Path) -> None:
    """`budget` is an int >= 1; zero or negative values are rejected."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "run": {"target": "x", "budget": 0},
        "predictors": [{"name": "alignn"}],
        "ranker": {"name": "x"},
    }))
    with pytest.raises(ValidationError):
        load_config(bad)


def test_load_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    """A nonexistent config path surfaces FileNotFoundError, not a swallowed empty config."""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_path_fields_are_path_objects(tmp_path: Path) -> None:
    """`run.output_dir` and `store.path` come back as pathlib.Path, not strings."""
    cfg = load_config(REPO_ROOT / "crucible.yaml.example")
    assert isinstance(cfg.run.output_dir, Path)
    assert isinstance(cfg.store.path, Path)


def test_plugin_entry_options_default_to_empty_dict(tmp_path: Path) -> None:
    """Plugin entries without an `options:` block default to an empty dict, not None."""
    cfg_yaml = tmp_path / "x.yaml"
    cfg_yaml.write_text(yaml.safe_dump({
        "run": {"target": "x", "budget": 10},
        "predictors": [{"name": "alignn"}],  # no options key
        "ranker": {"name": "x"},
    }))
    cfg = load_config(cfg_yaml)
    assert cfg.predictors[0].options == {}
    assert cfg.predictors[0].weight == 1.0
