"""Typer dispatcher for the `crucible` command-line interface.

Phase 1 will register the `run`, `predict`, `status`, `plugins`, and `export`
subcommands. For now this is a placeholder so `python -m crucible` and the
`crucible` console-script entry point both resolve.
"""

import typer

app = typer.Typer(
    name="crucible",
    help="Crucible — desktop materials discovery engine.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Crucible CLI. Subcommands are added in Phase 1."""
