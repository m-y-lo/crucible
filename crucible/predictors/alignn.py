"""ALIGNN `Predictor` plugin — wraps multiple pretrained checkpoints.

MVP loads `jv_formation_energy_peratom_alignn` (eV/atom) and
`jv_optb88vdw_bandgap` (eV). Each prediction carries a `ModelProvenance`
tagging dataset and version. Implemented in Phase 1.
"""
