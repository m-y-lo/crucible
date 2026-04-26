"""Tests for `crucible.queues.local_queue.LocalQueue`."""

from __future__ import annotations

import asyncio
import sqlite3

from crucible.core.models import Job, Result
from crucible.core.protocols import JobQueue
from crucible.queues.local_queue import LocalQueue


async def test_enqueue_then_dequeue_round_trip(tmp_path) -> None:
    """Enqueue a Job, dequeue it back with the same payload."""
    q = LocalQueue(tmp_path / "crucible.db")
    try:
        job = Job(job_id="j1", kind="predict", payload={"cif": "..."}, run_id="r1")
        await q.enqueue(job)
        got = await q.dequeue(["predict"])
        assert got is not None
        assert got.job_id == "j1"
        assert got.kind == "predict"
        assert got.payload == {"cif": "..."}
        assert got.run_id == "r1"
        assert got.attempts == 1
    finally:
        await q.close()


async def test_dequeue_filters_by_kind(tmp_path) -> None:
    """Only jobs whose kind is in the requested list are returned."""
    db_path = tmp_path / "crucible.db"
    q = LocalQueue(db_path)
    try:
        await q.enqueue(Job(job_id="relax-1", kind="relax", payload={}, run_id="r1"))
        await q.enqueue(Job(job_id="predict-1", kind="predict", payload={}, run_id="r1"))

        got = await q.dequeue(["predict"])
        assert got is not None
        assert got.job_id == "predict-1"

        with sqlite3.connect(db_path) as conn:
            statuses = dict(conn.execute("SELECT job_id, status FROM jobs").fetchall())
        assert statuses == {"relax-1": "queued", "predict-1": "running"}
    finally:
        await q.close()


async def test_mark_done_then_get_result(tmp_path) -> None:
    """mark_done makes get_result return the Result; before that it returns None."""
    q = LocalQueue(tmp_path / "crucible.db")
    try:
        await q.enqueue(Job(job_id="j1", kind="predict", payload={}, run_id="r1"))
        assert await q.get_result("j1") is None

        result = Result(job_id="j1", ok=True, payload={"value": 42})
        await q.mark_done("j1", result)

        got = await q.get_result("j1")
        assert got == result
    finally:
        await q.close()


async def test_localqueue_implements_jobqueue_protocol(tmp_path) -> None:
    """isinstance(LocalQueue(...), JobQueue) is True."""
    q = LocalQueue(tmp_path / "x.db")
    try:
        assert isinstance(q, JobQueue)
    finally:
        await q.close()


async def test_dequeue_wakes_on_enqueue(tmp_path) -> None:
    """A dequeue() that finds an empty queue should resume after enqueue()."""
    q = LocalQueue(tmp_path / "crucible.db")
    try:
        task = asyncio.create_task(q.dequeue(["predict"]))
        await asyncio.sleep(0)

        await q.enqueue(Job(job_id="j1", kind="predict", payload={}, run_id="r1"))

        got = await asyncio.wait_for(task, timeout=1)
        assert got is not None
        assert got.job_id == "j1"
    finally:
        await q.close()
