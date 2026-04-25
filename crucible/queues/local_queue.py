"""`LocalQueue` — asyncio + aiosqlite-backed `JobQueue` for Phase 1.

Reads/writes the `jobs` table that `LocalStore` creates. Uses an
`asyncio.Event` to wake dequeuers when a new job lands. Phase-3
`HTTPQueue` will implement the same Protocol against an HTTP server with
no orchestrator-side changes.

Wave 2 work. The Protocol it implements lives in
`crucible.core.protocols.JobQueue`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from crucible.core.models import Job, Result


class LocalQueue:
    """Asynchronous `JobQueue` backed by the same SQLite file as `LocalStore`."""

    def __init__(self, path: Path | str) -> None:
        # TODO Wave 2:
        #   1. self._path = Path(path).
        #   2. self._conn: aiosqlite.Connection | None = None  (opened lazily).
        #   3. self._notify = asyncio.Event() — set whenever a job is enqueued.
        #   4. self._lock = asyncio.Lock() — serializes the dequeue claim
        #      so two awaiting consumers never grab the same row.
        #   5. self._closed = False.
        raise NotImplementedError

    async def _ensure_open(self) -> None:
        """Open the aiosqlite connection if not already."""
        # TODO Wave 2:
        #   if self._conn is None:
        #     self._conn = await aiosqlite.connect(str(self._path))
        #     self._conn.row_factory = aiosqlite.Row
        #     await self._conn.execute("PRAGMA foreign_keys = ON")
        raise NotImplementedError

    async def enqueue(self, job: Job) -> None:
        # TODO Wave 2:
        #   await self._ensure_open()
        #   await self._conn.execute("""
        #       INSERT INTO jobs(job_id, kind, status, run_id, payload_json,
        #                        attempts, enqueued_at)
        #       VALUES (?, ?, 'queued', ?, ?, 0, ?)
        #   """, (job.job_id, job.kind, job.run_id, json.dumps(job.payload),
        #         job.enqueued_at.isoformat()))
        #   await self._conn.commit()
        #   self._notify.set()
        raise NotImplementedError

    async def dequeue(self, kinds: list[str]) -> Job | None:
        # TODO Wave 2:
        #   while not self._closed:
        #     async with self._lock:
        #       row = await self._conn.execute_fetchone("""
        #           SELECT job_id, kind, run_id, payload_json, enqueued_at, attempts
        #           FROM jobs WHERE status = 'queued' AND kind IN ({placeholders})
        #           ORDER BY enqueued_at LIMIT 1
        #       """, kinds)
        #       if row:
        #         await self._conn.execute("""
        #             UPDATE jobs SET status='running', started_at=?, attempts=attempts+1
        #             WHERE job_id=?
        #         """, (now, row["job_id"]))
        #         await self._conn.commit()
        #         return Job(job_id=row["job_id"], kind=row["kind"], ...)
        #     await self._notify.wait()
        #     self._notify.clear()
        #   return None  # closed
        raise NotImplementedError

    async def mark_done(self, job_id: str, result: Result) -> None:
        # TODO Wave 2:
        #   status = 'done' if result.ok else 'failed'
        #   UPDATE jobs SET status=?, result_json=?, error=?, finished_at=?
        #   WHERE job_id=?
        raise NotImplementedError

    async def get_result(self, job_id: str) -> Result | None:
        # TODO Wave 2:
        #   SELECT status, result_json, error FROM jobs WHERE job_id=?
        #   If status not in ('done', 'failed'): return None
        #   Else rebuild Result(job_id=..., ok=(status=='done'), payload=json.loads(...), error=...)
        raise NotImplementedError

    async def close(self) -> None:
        """Close the aiosqlite connection. Idempotent."""
        # TODO Wave 2:
        #   self._closed = True
        #   self._notify.set()  # wake any waiting dequeuer to return None
        #   if self._conn is not None: await self._conn.close()
        raise NotImplementedError
