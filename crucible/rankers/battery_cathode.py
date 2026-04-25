"""`Ranker` for Li-ion battery cathodes.

Hard gates: contains-Li, formation_energy < -1.0 eV/atom, bandgap < 1.5 eV.
Score combines stability, electronic suitability, and Li atom fraction.
See ARCHITECTURE.md §13 and the Ranker docstring for thresholds.
Implemented in Phase 1.
"""
