"""Composes gauntlet stages with early exit and `gauntlet_events` writes.

Each stage is a pure function; the pipeline threads a CIF through them in
order, recording the per-stage outcome. See ARCHITECTURE.md §10.
Implemented in Phase 1.
"""
