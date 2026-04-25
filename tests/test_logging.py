"""Tests for `crucible.core.logging` — JSON-line logger.

The crucible logger is process-global, so every test uses the
`fresh_logger` fixture to clear handlers and avoid bleed across tests.
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
from datetime import datetime

import pytest

from crucible.core.logging import log_event, setup_logging


@pytest.fixture
def fresh_logger():
    """Reset the crucible logger between tests so handlers don't accumulate."""
    logger = _stdlib_logging.getLogger("crucible")
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    logger.handlers = []
    yield logger
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
    logger.handlers = saved_handlers
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


def _read_last_event(events_path) -> dict:
    return json.loads(events_path.read_text().splitlines()[-1])


def test_setup_creates_run_dir_and_jsonl_file(tmp_path, fresh_logger) -> None:
    """setup_logging mkdirs the run dir and (after first event) writes the file."""
    logger = setup_logging("test_run", tmp_path)
    log_event(logger, stage="smoke")
    target = tmp_path / "test_run" / "events.jsonl"
    assert target.exists()
    record = _read_last_event(target)
    assert record["stage"] == "smoke"
    assert record["run_id"] == "test_run"


def test_log_event_includes_required_envelope(tmp_path, fresh_logger) -> None:
    """Every event has ts, level, logger, msg, run_id, stage."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="parse")
    rec = _read_last_event(tmp_path / "rt" / "events.jsonl")
    for key in ("ts", "level", "logger", "msg", "run_id", "stage"):
        assert key in rec, f"missing key {key!r} in {rec}"
    assert rec["level"] == "INFO"
    assert rec["logger"] == "crucible"


def test_optional_fields_present_when_supplied(tmp_path, fresh_logger) -> None:
    """structure_hash, model_id, latency_ms, passed land in the event when given."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="predict", structure_hash="abc",
              model_id="alignn", latency_ms=42, passed=True)
    rec = _read_last_event(tmp_path / "rt" / "events.jsonl")
    assert rec["structure_hash"] == "abc"
    assert rec["model_id"] == "alignn"
    assert rec["latency_ms"] == 42
    assert rec["passed"] is True


def test_optional_fields_omitted_when_none(tmp_path, fresh_logger) -> None:
    """None-valued optional fields are NOT written, keeping JSON minimal."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="parse", structure_hash="abc")  # others left None
    rec = _read_last_event(tmp_path / "rt" / "events.jsonl")
    assert rec["structure_hash"] == "abc"
    assert "model_id" not in rec
    assert "latency_ms" not in rec
    assert "passed" not in rec


def test_extra_kwargs_pass_through(tmp_path, fresh_logger) -> None:
    """Free-form **extra kwargs land in the JSON event."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="custom", reason="missing-Li", attempts=3)
    rec = _read_last_event(tmp_path / "rt" / "events.jsonl")
    assert rec["reason"] == "missing-Li"
    assert rec["attempts"] == 3


def test_setup_is_idempotent(tmp_path, fresh_logger) -> None:
    """Calling setup_logging twice for the same run does not duplicate file handlers."""
    a = setup_logging("rt", tmp_path)
    n_a = sum(isinstance(h, _stdlib_logging.FileHandler) for h in a.handlers)
    b = setup_logging("rt", tmp_path)
    n_b = sum(isinstance(h, _stdlib_logging.FileHandler) for h in b.handlers)
    assert a is b
    assert n_a == n_b == 1


def test_timestamp_is_iso_with_timezone(tmp_path, fresh_logger) -> None:
    """ts field round-trips through datetime.fromisoformat with a tzinfo."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="parse")
    rec = _read_last_event(tmp_path / "rt" / "events.jsonl")
    parsed = datetime.fromisoformat(rec["ts"])
    assert parsed.tzinfo is not None


def test_multiple_events_produce_multiple_lines(tmp_path, fresh_logger) -> None:
    """Each log_event writes its own line — events.jsonl is append-only."""
    logger = setup_logging("rt", tmp_path)
    log_event(logger, stage="parse", structure_hash="a")
    log_event(logger, stage="composition", structure_hash="a", passed=True)
    log_event(logger, stage="geometry", structure_hash="a", passed=False)
    lines = (tmp_path / "rt" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 3
    stages = [json.loads(line)["stage"] for line in lines]
    assert stages == ["parse", "composition", "geometry"]
