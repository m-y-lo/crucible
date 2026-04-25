"""Plugin discovery via `importlib.metadata` entry points.

Exposes `load(kind, name, **kwargs)` and `list_plugins(kind)`. Plugin kinds
are declared in `pyproject.toml` `[project.entry-points."crucible.<kind>"]`
sections. See ARCHITECTURE.md §5. Implemented in Phase 1.
"""
