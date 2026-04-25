"""`LocalQueue` — asyncio + aiosqlite-backed `JobQueue` for Phase 1.

Reads/writes the `jobs` table; uses an `asyncio.Event` to wake dequeuers.
Phase 3's `HTTPQueue` will implement the same protocol against an HTTP
server with no orchestrator-side changes. Implemented in Phase 1.
"""
