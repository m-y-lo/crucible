"""Plugin discovery via `importlib.metadata` entry points.

Exposes `load(kind, name, **kwargs)` and `list_plugins(kind)`. Plugin kinds
are declared in `pyproject.toml` `[project.entry-points."crucible.<kind>"]`
sections. See ARCHITECTURE.md §5.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from typing import Any

# Map plugin kind (the name we use in code and config) to the entry-point
# group name (the string in pyproject.toml). Single source of truth; all
# other modules talk to the registry, never importlib.metadata directly.
GROUPS: dict[str, str] = {
    "generator": "crucible.generators",
    "relaxer": "crucible.relaxers",
    "predictor": "crucible.predictors",
    "ranker": "crucible.rankers",
    "orchestrator": "crucible.orchestrators",
    "store": "crucible.stores",
    "queue": "crucible.queues",
}


@lru_cache
def _eps(kind: str) -> dict[str, EntryPoint]:
    """Return `{plugin_name: EntryPoint}` for the given plugin kind.

    Tests inject fakes by replacing this attribute via `monkeypatch.setattr`
    on the module — that bypasses the cache cleanly because callers look
    up `_eps` through the module namespace each time.
    """
    if kind not in GROUPS:
        raise KeyError(f"Unknown plugin kind {kind!r}; have {sorted(GROUPS)}")
    return {ep.name: ep for ep in entry_points(group=GROUPS[kind])}


def list_plugins(kind: str) -> list[str]:
    """Return sorted plugin names registered under `kind`.

    Raises KeyError if `kind` is not a known plugin kind.
    """
    return sorted(_eps(kind).keys())


def load(kind: str, name: str, **kwargs: Any) -> Any:
    """Instantiate a plugin by `kind` + `name` with the given keyword args.

    Raises KeyError if the plugin is not registered, with the available
    names included so a typo is immediately diagnosable.
    """
    eps = _eps(kind)
    ep = eps.get(name)
    if ep is None:
        raise KeyError(f"No {kind} plugin {name!r}; have {sorted(eps)}")
    cls = ep.load()
    return cls(**kwargs)
