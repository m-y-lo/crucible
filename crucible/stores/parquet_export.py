"""`crucible export --format parquet` — portable snapshot of a run.

Joins `structures` with the best prediction per checkpoint and the latest
ranking, writes a single Parquet file for sharing. Implemented in Phase 2.
"""
