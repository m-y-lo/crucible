"""Typer dispatcher for the ``crucible`` command-line interface.

Four user-facing commands:

  crucible run     -- start a discovery loop (kicks off the orchestrator)
  crucible status  -- read-only leaderboard + gauntlet histogram
  crucible plugins -- list registered plugins by kind
  crucible predict -- predict properties for a single CIF

Each command is a thin shell over registry-loaded plugins and the
formatter helpers in ``crucible.reports``. Configuration lives in
``crucible.yaml`` (validated by ``crucible.core.config``); secrets in
``.env`` (loaded automatically on import via python-dotenv).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from crucible.core.config import load_config
from crucible.core.registry import list_plugins, load as registry_load


# Load .env at import time so env-var lookups inside command bodies
# Just Work without the user remembering to source it.
load_dotenv()


app = typer.Typer(
    name="crucible",
    help="Crucible — desktop materials discovery engine.",
    no_args_is_help=True,
)
console = Console()


# Plugin kinds shown by `crucible plugins`. Order is the canonical
# pipeline order, so a reader sees generators -> ... -> queue top-down.
_PLUGIN_KINDS = (
    "generator",
    "relaxer",
    "predictor",
    "ranker",
    "orchestrator",
    "store",
    "queue",
)


# ---------------------------------------------------------------------------
# crucible run
# ---------------------------------------------------------------------------


@app.command("run")
def run_cmd(
    target: Optional[str] = typer.Option(
        None, "--target", help="Override run.target from crucible.yaml."
    ),
    budget: Optional[int] = typer.Option(
        None, "--budget", help="Override run.budget from crucible.yaml.", min=1
    ),
    config: Path = typer.Option(
        Path("crucible.yaml"), "--config", "-c", help="Path to crucible.yaml.",
    ),
) -> None:
    """Start a discovery loop and print the resulting run_id."""
    cfg = load_config(config)
    target = target or cfg.run.target
    budget = budget or cfg.run.budget

    use_novelty = cfg.materials_project.enabled and cfg.materials_project.novelty_filter
    mp_client = None
    if use_novelty:
        from crucible.data.mp_client import MPClient

        try:
            mp_client = MPClient.from_env()
        except RuntimeError as exc:
            console.print(f"[red]MP novelty enabled but {exc}[/red]")
            raise typer.Exit(code=1) from exc

    try:
        orch = registry_load(
            "orchestrator",
            cfg.orchestrator.name,
            mp_client=mp_client,
            skip_novelty=not use_novelty,
            **cfg.orchestrator.options,
        )
    except KeyError as exc:
        console.print(f"[red]Unknown orchestrator: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        console.print(f"[red]Orchestrator init failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[cyan]Starting run[/cyan] target={target!r} budget={budget}"
    )
    run_id = orch.run(target, budget)
    console.print(f"[green]Run complete[/green] run_id={run_id}")


# ---------------------------------------------------------------------------
# crucible status
# ---------------------------------------------------------------------------


@app.command("status")
def status_cmd(
    run_id: Optional[str] = typer.Option(
        None, "--run-id", help="Run to inspect; latest if omitted."
    ),
    config: Path = typer.Option(
        Path("crucible.yaml"), "--config", "-c", help="Path to crucible.yaml.",
    ),
    top_n: int = typer.Option(10, "--top-n", min=1, help="Top-N candidates to display."),
) -> None:
    """Print leaderboard + gauntlet histogram for a run."""
    from crucible.reports.status import render_status

    cfg = load_config(config)
    db_path = cfg.store.path
    if not Path(db_path).exists():
        console.print(f"[yellow]No database at {db_path}[/yellow]")
        console.print(
            "[dim]Phase 1 caveat: the orchestrator does not yet persist "
            "rankings to the store. Run `crucible run` and Phase 2 will "
            "populate the DB.[/dim]"
        )
        raise typer.Exit(code=1)

    out = render_status(db_path, run_id=run_id, top_n=top_n)
    console.print(out)


# ---------------------------------------------------------------------------
# crucible plugins
# ---------------------------------------------------------------------------


@app.command("plugins")
def plugins_cmd() -> None:
    """List registered plugins by kind."""
    for kind in _PLUGIN_KINDS:
        names = list_plugins(kind)
        rendered = ", ".join(names) if names else "(none)"
        console.print(f"[bold]{kind}[/bold]: {rendered}")


# ---------------------------------------------------------------------------
# crucible predict
# ---------------------------------------------------------------------------


@app.command("predict")
def predict_cmd(
    cif_path: Path = typer.Argument(..., help="Path to a CIF file."),
    predictor: str = typer.Option(
        "alignn", "--predictor", help="Predictor plugin name."
    ),
) -> None:
    """Predict properties for a single CIF using the named predictor."""
    if not cif_path.exists():
        console.print(f"[red]CIF not found: {cif_path}[/red]")
        raise typer.Exit(code=1)

    cif = cif_path.read_text()
    try:
        pred = registry_load("predictor", predictor)
    except KeyError as exc:
        console.print(f"[red]Predictor not registered: {exc}[/red]")
        console.print(
            "[dim]Hint: run `crucible plugins` to see what is available. "
            "ALIGNN requires `uv sync --extra ml`.[/dim]"
        )
        raise typer.Exit(code=1) from exc

    props = pred.predict(cif)
    for key, value in props.items():
        console.print(f"  {key}: {value}")


# ---------------------------------------------------------------------------
# Optional silence-the-noisy-loaders helper for tests / scripts
# ---------------------------------------------------------------------------


def _set_log_level_from_env() -> None:
    """Honor CRUCIBLE_LOG_LEVEL when set. Currently only exists so the
    test harness can quiet things down without the CLI assuming logging
    is configured by Ming's logging setup, which is run-scoped."""
    level = os.environ.get("CRUCIBLE_LOG_LEVEL")
    if not level:
        return
    import logging

    logging.basicConfig(level=level.upper())


_set_log_level_from_env()
