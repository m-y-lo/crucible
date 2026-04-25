"""Tests for `crucible.queues.local_queue.LocalQueue` — Wave 2."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2 implementation pending")
async def test_enqueue_then_dequeue_round_trip(tmp_path) -> None:
    """Enqueue a Job, dequeue it back with the same payload."""
    # TODO:
    #   q = LocalQueue(tmp_path / "crucible.db")
    #   await q.enqueue(Job(job_id="j1", kind="predict", payload={"cif": "..."},
    #                       run_id="r1"))
    #   got = await q.dequeue(["predict"])
    #   assert got.job_id == "j1" and got.payload == {"cif": "..."}
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
async def test_dequeue_filters_by_kind(tmp_path) -> None:
    """Only jobs whose kind is in the requested list are returned."""
    # TODO: enqueue both a 'predict' and a 'relax' job; dequeue(['predict'])
    # returns the predict one; the relax one stays queued.
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
async def test_mark_done_then_get_result(tmp_path) -> None:
    """mark_done makes get_result return the Result; before that it returns None."""
    # TODO
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
async def test_localqueue_implements_jobqueue_protocol(tmp_path) -> None:
    """isinstance(LocalQueue(...), JobQueue) is True."""
    # TODO:
    #   from crucible.core.protocols import JobQueue
    #   assert isinstance(LocalQueue(tmp_path / "x.db"), JobQueue)
    ...


@pytest.mark.skip(reason="Wave 2 implementation pending")
async def test_dequeue_wakes_on_enqueue(tmp_path) -> None:
    """A dequeue() that finds an empty queue should resume after enqueue()."""
    # TODO: kick off `task = asyncio.create_task(q.dequeue([...]))`,
    # await asyncio.sleep(0); enqueue; assert await task returns the Job.
    ...
