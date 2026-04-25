"""Gauntlet stage 5 — within-run dedup.

Coarse pre-filter on `(prototype_label, composition)`; full
`StructureMatcher` is only invoked on collisions. Pairwise scan across all
runs is an O(N²) batch job that runs nightly server-side, not here.
Implemented in Phase 1.
"""
