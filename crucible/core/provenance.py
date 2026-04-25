"""`ModelProvenance` helpers — model_id, checkpoint, dataset, version, units.

Every `Predictor` and `Relaxer` must attach this to its outputs so the
predictions table's `(structure_hash, model_id, checkpoint, version)`
UNIQUE constraint stays meaningful. See playbook §F. Implemented in Phase 1.
"""
