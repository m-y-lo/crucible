"""Gauntlet stage 1 — parse a CIF string into a `pymatgen.Structure`.

Catches malformed CIFs at the front of the funnel; logs a
`gauntlet_event(stage='parse', passed=0)` on failure. Implemented in Phase 1.
"""
