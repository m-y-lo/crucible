"""``crucible status`` — read-only run report.

Builds a multi-section text report from the SQLite store: run metadata,
top-N leaderboard, and a per-stage gauntlet histogram. Pure formatter —
opens its own read-only sqlite connection, never writes.

Phase 1 caveat: the orchestrator currently keeps rankings + gauntlet
events in-memory only, so a fresh DB will produce empty sections. The
schema is correct and the formatter works on any data; Phase 2 will
wire orchestrator -> store persistence.
"""

from __future__ import annotations

import json
import sqlite3
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


_DEFAULT_TOP_N = 10


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def render_run_summary(run_row: dict[str, Any] | None) -> str:
    """One-paragraph overview of the run. Empty string if no run found."""
    if run_row is None:
        return "No run record found.\n"
    lines = [
        f"Run id:    {run_row['run_id']}",
        f"Target:    {run_row['target']}",
        f"Budget:    {run_row['budget']}",
        f"Started:   {run_row['started_at']}",
        f"Ended:     {run_row['ended_at'] or '(in progress)'}",
    ]
    return "\n".join(lines) + "\n"


def render_leaderboard(rows: list[dict[str, Any]], top_n: int = _DEFAULT_TOP_N) -> str:
    """Render the top-``top_n`` scored candidates as a rich Table."""
    table = Table(title=f"Top {top_n} candidates")
    table.add_column("rank", justify="right")
    table.add_column("score", justify="right")
    table.add_column("composition")
    table.add_column("space_group", justify="right")
    table.add_column("prototype")
    table.add_column("hash_prefix")
    table.add_column("predictions")

    for i, row in enumerate(rows[:top_n], start=1):
        preds = _format_predictions(row.get("values_json"))
        table.add_row(
            str(i),
            f"{row.get('score', 0.0):.3f}",
            str(row.get("composition", "?")),
            str(row.get("space_group", "?")),
            str(row.get("prototype_label", "?")),
            str(row.get("structure_hash", ""))[:12],
            preds,
        )

    if not rows:
        table.add_row("—", "—", "—", "—", "—", "—", "—")

    return _table_to_str(table)


def render_gauntlet_histogram(events_summary: list[dict[str, Any]]) -> str:
    """One row per stage: passed / rejected / pass-rate."""
    # Architecture-defined stage order; missing stages are still shown
    # with zeros so the funnel reads cleanly top-to-bottom.
    canonical_order = ["parse", "composition", "geometry", "novelty", "dedup"]
    by_stage: dict[str, dict[str, int]] = {
        s: {"passed": 0, "rejected": 0} for s in canonical_order
    }
    for row in events_summary:
        stage = row["stage"]
        by_stage.setdefault(stage, {"passed": 0, "rejected": 0})
        if int(row.get("passed", 0)) == 1:
            by_stage[stage]["passed"] += int(row["count"])
        else:
            by_stage[stage]["rejected"] += int(row["count"])

    table = Table(title="Gauntlet histogram")
    table.add_column("stage")
    table.add_column("passed", justify="right")
    table.add_column("rejected", justify="right")
    table.add_column("pass rate", justify="right")

    # Stages we know about first, then any extras (e.g. energy_screen).
    known = [s for s in canonical_order if s in by_stage]
    extras = [s for s in by_stage.keys() if s not in canonical_order]
    for stage in known + extras:
        passed = by_stage[stage]["passed"]
        rejected = by_stage[stage]["rejected"]
        total = passed + rejected
        rate = (passed / total * 100.0) if total else 0.0
        table.add_row(
            stage,
            str(passed),
            str(rejected),
            f"{rate:.1f}%" if total else "—",
        )

    return _table_to_str(table)


def render_status(
    db_path: Path | str,
    run_id: str | None = None,
    target: str | None = None,
    top_n: int = _DEFAULT_TOP_N,
) -> str:
    """Build the full status report. ``run_id=None`` selects the latest."""
    conn = _connect_readonly(Path(db_path))
    try:
        if run_id is None:
            run_row = _latest_run(conn)
            if run_row is not None:
                run_id = run_row["run_id"]
                target = target or run_row["target"]
        else:
            run_row = _run_by_id(conn, run_id)
            if run_row is not None and target is None:
                target = run_row["target"]

        leaderboard_rows = _leaderboard(conn, run_id=run_id, target=target, limit=top_n)
        gauntlet_rows = _gauntlet_summary(conn, run_id=run_id)
    finally:
        conn.close()

    parts = [
        render_run_summary(run_row),
        "",
        render_leaderboard(leaderboard_rows, top_n=top_n),
        "",
        render_gauntlet_histogram(gauntlet_rows),
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Read-only SQL helpers
# ---------------------------------------------------------------------------


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _run_by_id(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def _leaderboard(
    conn: sqlite3.Connection,
    run_id: str | None,
    target: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Top-K rankings joined with structure metadata + best prediction.

    The "best" prediction here is just the most recently inserted; Phase
    2 may switch to per-checkpoint tagging once multiple predictors land.
    """
    where = ["r.passes_criteria = 1"]
    params: list[Any] = []
    if run_id is not None:
        where.append("r.run_id = ?")
        params.append(run_id)
    if target is not None:
        where.append("r.target = ?")
        params.append(target)
    sql = f"""
        SELECT
            r.score             AS score,
            r.structure_hash    AS structure_hash,
            s.composition       AS composition,
            s.space_group       AS space_group,
            s.prototype_label   AS prototype_label,
            (SELECT p.values_json FROM predictions p
              WHERE p.structure_hash = s.structure_hash
              ORDER BY p.created_at DESC LIMIT 1) AS values_json
        FROM rankings r
        JOIN structures s USING (structure_hash)
        WHERE {' AND '.join(where)}
        ORDER BY r.score DESC
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _gauntlet_summary(
    conn: sqlite3.Connection,
    run_id: str | None,
) -> list[dict[str, Any]]:
    """Group gauntlet_events by (stage, passed)."""
    sql = "SELECT stage, passed, COUNT(*) AS count FROM gauntlet_events"
    params: list[Any] = []
    if run_id is not None:
        sql += " WHERE run_id = ?"
        params.append(run_id)
    sql += " GROUP BY stage, passed"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_predictions(values_json: str | None) -> str:
    """Compact one-cell summary of the prediction dict."""
    if not values_json:
        return "—"
    try:
        values = json.loads(values_json)
    except json.JSONDecodeError:
        return "(unparseable)"
    if not values:
        return "—"
    parts = [f"{k}={float(v):.3f}" for k, v in values.items()]
    return " ".join(parts)


def _table_to_str(table: Table) -> str:
    """Render a rich Table as a plain string. Console.export_text strips
    ANSI codes so the output is stable for tests + suitable for files."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120, record=True)
    console.print(table)
    return console.export_text()
