"""Gauntlet stage 4 — Materials Project novelty filter.

Queries MP by composition; runs `StructureMatcher` against returned entries
and flags rediscoveries. Behavior (log-only / demote / drop) is configurable
via `materials_project.novelty_filter`. Implemented in Phase 1.
"""
