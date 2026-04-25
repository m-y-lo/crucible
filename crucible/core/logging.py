"""Structured JSON-line logger to file plus rich console output.

Emits one JSON line per event to `runs/{run_id}/events.jsonl` and a
human-friendly rendering to stdout. Every gauntlet stage and every model
call should go through `log_event` so events always carry a stable set of
fields. See ARCHITECTURE.md §13.
"""

from __future__ import annotations

import logging as _stdlib_logging
from pathlib import Path
from typing import Any


_LOGGER_NAME = "crucible"


def setup_logging(run_id: str, output_dir: Path | str) -> _stdlib_logging.Logger:
    """Configure the root `crucible` logger for a run.

    Adds two handlers:
      - JSON-line FileHandler at `<output_dir>/<run_id>/events.jsonl`
      - rich.logging.RichHandler on stdout at level INFO

    Returns the configured logger; downstream code uses
    `logging.getLogger("crucible.<module>")` and gets both handlers via
    propagation.
    """
    # TODO Wave 1:
    #   1. run_dir = Path(output_dir) / run_id; mkdir parents=True, exist_ok=True
    #   2. Define class JsonLineFormatter(logging.Formatter) that returns
    #      json.dumps({
    #          "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
    #          "level": record.levelname,
    #          "logger": record.name,
    #          "msg": record.getMessage(),
    #          "run_id": run_id,
    #          **getattr(record, "extra_fields", {}),
    #      })
    #   3. file_handler = FileHandler(run_dir / "events.jsonl"); set formatter; level DEBUG.
    #   4. console_handler = RichHandler(show_time=True, show_path=False); level INFO.
    #   5. logger = logging.getLogger(_LOGGER_NAME); level DEBUG; add both handlers
    #      (only if not already added — idempotent on re-runs).
    #   6. return logger.
    raise NotImplementedError


def log_event(
    logger: _stdlib_logging.Logger,
    *,
    stage: str,
    structure_hash: str | None = None,
    model_id: str | None = None,
    latency_ms: int | None = None,
    passed: bool | None = None,
    **extra: Any,
) -> None:
    """Emit a structured event with consistent fields.

    Every gauntlet stage and every predictor / relaxer call should go
    through this helper so the JSON lines always carry stage,
    structure_hash, model_id, latency_ms, passed (when relevant). Free-form
    `**extra` keys land in the JSON event but should be used sparingly.
    """
    # TODO Wave 1:
    #   fields = {"stage": stage}
    #   for k, v in [("structure_hash", structure_hash), ("model_id", model_id),
    #                 ("latency_ms", latency_ms), ("passed", passed)]:
    #       if v is not None: fields[k] = v
    #   fields.update(extra)
    #   logger.info(stage, extra={"extra_fields": fields})
    raise NotImplementedError
