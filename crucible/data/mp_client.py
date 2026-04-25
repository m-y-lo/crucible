"""Thin cached `pymatgen.MPRester` (mp-api) wrapper.

Single client used by `gauntlet.novelty`, `data.calibration`, and
`data.seeds`. Disk-caches queries by `(composition, query_hash)` because MP
changes slowly. Requires `MP_API_KEY`. Implemented in Phase 1.
"""
