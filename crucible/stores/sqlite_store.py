"""`LocalStore` — SQLite-backed `ResultStore` for solo and Phase-1 runs.

Applies the schema from ARCHITECTURE.md §4 in `__init__`. Five tables:
runs, structures, predictions, rankings, jobs, plus gauntlet_events.
Implemented in Phase 1.
"""
