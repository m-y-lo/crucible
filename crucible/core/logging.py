"""Structured JSON-line logger to file plus rich console output.

Emits one JSON line per event to `runs/{run_id}/events.jsonl` and a
human-friendly rendering to stdout. Every gauntlet stage and every model
call should go through `log_event` so events always carry a stable set of
fields. See ARCHITECTURE.md §13.

Usage:
    from crucible.core.logging import setup_logging, log_event
    logger = setup_logging("run_2026_04_25_173000", "./runs")
    log_event(logger, stage="parse", structure_hash="abc...", passed=True)
"""

from __future__ import annotations

import json
import logging as _logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

_LOGGER_NAME = "crucible"


class _JsonLineFormatter(_logging.Formatter):
    """Emit each LogRecord as a single JSON line.

    Fields written: ts (ISO 8601 UTC), level, logger, msg, run_id, plus
    everything inside `record.extra_fields` (a dict the caller supplies
    via `logger.info(msg, extra={"extra_fields": {...}})`). The wrapped-
    dict shape avoids clashing with reserved stdlib LogRecord attributes
    like `name`, `msg`, `levelname`, etc.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def format(self, record: _logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": self._run_id,
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(run_id: str, output_dir: Path | str) -> _logging.Logger:
    """Configure the root `crucible` logger for a run.

    Adds (idempotently) two handlers:
      - JSON-line FileHandler at `<output_dir>/<run_id>/events.jsonl` (DEBUG)
      - rich.logging.RichHandler on stdout (INFO)

    Idempotency is keyed on the file path: re-calling `setup_logging` with
    the same `run_id` and `output_dir` is a no-op and returns the existing
    logger. Calls with different run_ids add additional file handlers —
    that's a bug at the call site, not here, so we don't try to police it.
    """
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "events.jsonl"

    logger = _logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_logging.DEBUG)
    logger.propagate = False

    already_attached = any(
        isinstance(h, _logging.FileHandler) and Path(h.baseFilename) == target
        for h in logger.handlers
    )
    if already_attached:
        return logger

    file_handler = _logging.FileHandler(target, mode="a", encoding="utf-8")
    file_handler.setLevel(_logging.DEBUG)
    file_handler.setFormatter(_JsonLineFormatter(run_id=run_id))
    logger.addHandler(file_handler)

    if not any(isinstance(h, RichHandler) for h in logger.handlers):
        console = RichHandler(show_time=True, show_path=False, rich_tracebacks=True)
        console.setLevel(_logging.INFO)
        logger.addHandler(console)

    return logger


def log_event(
    logger: _logging.Logger,
    *,
    stage: str,
    structure_hash: str | None = None,
    model_id: str | None = None,
    latency_ms: int | None = None,
    passed: bool | None = None,
    **extra: Any,
) -> None:
    """Emit a structured event with consistent fields.

    `stage` is required. The named optional fields are dropped when None
    so the JSON output stays minimal. Free-form `**extra` keys land in
    the JSON as-is — use sparingly and prefer named arguments.
    """
    fields: dict[str, Any] = {"stage": stage}
    for key, value in (
        ("structure_hash", structure_hash),
        ("model_id", model_id),
        ("latency_ms", latency_ms),
        ("passed", passed),
    ):
        if value is not None:
            fields[key] = value
    fields.update(extra)
    logger.info(stage, extra={"extra_fields": fields})
