"""Entry point for `python -m crucible` — delegates to the Typer CLI."""

from crucible.cli import app

if __name__ == "__main__":
    app()
