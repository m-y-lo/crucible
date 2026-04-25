"""`RemoteStore` — HTTP client `ResultStore` for Phase-3 worker fleet.

Same `ResultStore` protocol as `LocalStore`; talks to the central server's
append-only Parquet event log instead of a local SQLite file. Implemented
in Phase 3.
"""
