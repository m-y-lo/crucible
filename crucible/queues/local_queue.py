"""`LocalQueue` — async aiosqlite-backed `JobQueue` for Phase 1.

Reads and writes the `jobs` table that the shared schema creates. Uses
an `asyncio.Event` to wake waiting dequeuers when a new job lands, plus
an `asyncio.Lock` to serialize the SELECT-then-UPDATE claim so two
consumers never grab the same job. Phase-3 `HTTPQueue` will implement
the same Protocol against an HTTP server with no caller-side changes.

LocalQueue and `LocalStore` may share a single `crucible.db` file —
both `executescript(SCHEMA)` in their `__init__` and SQLite's WAL mode
keeps the readers and writer from blocking each other.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from crucible.core._schema import SCHEMA
from crucible.core.models import Job, Result


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalQueue:
    """Async `JobQueue` backed by the same SQLite file as `LocalStore`."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None
        self._notify = asyncio.Event()
        self._claim_lock = asyncio.Lock()
        self._open_lock = asyncio.Lock()
        self._closed = False

    async def _ensure_open(self) -> aiosqlite.Connection:
        """Lazy-open the aiosqlite connection (double-checked under a lock)."""
        if self._conn is not None:
            return self._conn
        async with self._open_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(
                    str(self._path), isolation_level=None
                )
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute("PRAGMA journal_mode = WAL")
                await self._conn.executescript(SCHEMA)
        return self._conn

    # ------------------------------------------------------------------
    # JobQueue Protocol implementation
    # ------------------------------------------------------------------

    async def enqueue(self, job: Job) -> None:
        if self._closed:
            raise RuntimeError("LocalQueue is closed")
        conn = await self._ensure_open()
        await conn.execute(
            """
            INSERT INTO jobs(job_id, kind, status, run_id, payload_json,
                             attempts, enqueued_at)
            VALUES (?, ?, 'queued', ?, ?, 0, ?)
            """,
            (
                job.job_id,
                job.kind,
                job.run_id,
                json.dumps(job.payload),
                job.enqueued_at.isoformat(),
            ),
        )
        self._notify.set()

    async def dequeue(self, kinds: list[str]) -> Job | None:
        """Block until a job of one of `kinds` is available; return it.

        Returns None if the queue is closed (sentinel for shutdown).
        Increments the job's `attempts` counter as part of the claim.
        """
        if not kinds:
            return None
        conn = await self._ensure_open()
        placeholders = ",".join("?" * len(kinds))
        select_sql = (
            f"""
            SELECT job_id, kind, run_id, payload_json, enqueued_at, attempts
            FROM jobs
            WHERE status = 'queued' AND kind IN ({placeholders})
            ORDER BY enqueued_at, job_id
            LIMIT 1
            """
        )
        while not self._closed:
            async with self._claim_lock:
                cur = await conn.execute(select_sql, kinds)
                row = await cur.fetchone()
                await cur.close()
                if row is not None:
                    new_attempts = row["attempts"] + 1
                    await conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'running', started_at = ?, attempts = ?
                        WHERE job_id = ?
                        """,
                        (_utcnow_iso(), new_attempts, row["job_id"]),
                    )
                    return Job(
                        job_id=row["job_id"],
                        kind=row["kind"],
                        payload=json.loads(row["payload_json"]),
                        run_id=row["run_id"],
                        enqueued_at=datetime.fromisoformat(row["enqueued_at"]),
                        attempts=new_attempts,
                    )
            # Nothing matched; wait for an enqueue or a close to wake us.
            await self._notify.wait()
            self._notify.clear()
        return None

    async def mark_done(self, job_id: str, result: Result) -> None:
        conn = await self._ensure_open()
        status = "done" if result.ok else "failed"
        await conn.execute(
            """
            UPDATE jobs
            SET status = ?, result_json = ?, error = ?, finished_at = ?
            WHERE job_id = ?
            """,
            (
                status,
                json.dumps(result.payload),
                result.error,
                _utcnow_iso(),
                job_id,
            ),
        )

    async def get_result(self, job_id: str) -> Result | None:
        conn = await self._ensure_open()
        cur = await conn.execute(
            "SELECT status, result_json, error FROM jobs WHERE job_id = ?",
            (job_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if row is None or row["status"] not in ("done", "failed"):
            return None
        return Result(
            job_id=job_id,
            ok=(row["status"] == "done"),
            payload=json.loads(row["result_json"]) if row["result_json"] else {},
            error=row["error"],
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the connection. Wakes any waiting dequeuer so it returns None.

        Idempotent — safe to call twice.
        """
        if self._closed:
            return
        self._closed = True
        self._notify.set()  # wake waiting dequeuers
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
