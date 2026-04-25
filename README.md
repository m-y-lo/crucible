# Crucible

A desktop materials discovery engine. Multi-agent Python workflow that generates novel crystal structures and screens them for useful properties (formation energy, bandgap, mechanical, electronic) on a single consumer GPU — an indie, local analogue of large-scale platforms like the DOE's FORUM-AI.

For the design, see [`ARCHITECTURE.md`](./ARCHITECTURE.md). For tasks and current state, see [`TODO.md`](./TODO.md). For workflow and AI-agent rules, see [`playbook.md`](./playbook.md).

## How it works

1. **Generate** — a `Generator` plugin (CrystaLLM locally, optionally MatterGen via a Colab notebook) emits novel CIF files.
2. **Validate** — every CIF runs a gauntlet: parse → composition sanity → geometry sanity → novelty check vs. Materials Project → dedup → cheap-energy screen.
3. **Predict** — survivors are passed to **ALIGNN** pretrained graph-neural-network checkpoints, which estimate properties like formation energy (eV/atom) and bandgap (eV) in milliseconds — what DFT would do in hours, at lower accuracy but accurate enough to screen.
4. **Rank & iterate** — a target-specific `Ranker` plugin (e.g. battery cathode) applies hard gates and a scalar score; the orchestrator feeds top survivors back as conditioning seeds for the next batch.

Long-term: same code path, scaled out folding@home-style across volunteer GPUs (Phase 3 HTTP server + pipx workers; Phase 4 BOINC).

## A note on ALIGNN

ALIGNN is **not a hosted API** — it's an open-source PyTorch package from NIST (MIT license) that ships with multiple pretrained checkpoints. We import it locally and run inference on the user's GPU. A separate `alignn-ff` variant is used as a force-field relaxer for the cheap-energy screen. Same picture for CrystaLLM and MatterGen: open-source local packages, no API keys, no rate limits.

## Materials Project integration

Crucible queries Materials Project for three things:

- **Novelty filter** — flag CIFs that are rediscoveries of known materials.
- **Predictor calibration** — periodically score known MP structures with our pipeline and compare predictions against MP's published DFT values to track our drift / error.
- **Conditioning seeds** — pull top-K known materials for a target as prompts to the generator.

Set `MP_API_KEY` in `.env` to enable.

## Cost model — who pays for what

The Claude orchestrator (default `claude-sonnet-4-6`) makes routing decisions for the discovery loop. **In solo Phase 1 use, the user pays for their own runs** — typically cents to a couple of dollars per discovery session.

In Phase 3 / 4 (crowdsourced), the orchestrator runs centrally on the project's server. **Volunteers contribute GPU compute only — no Anthropic account, no API key, no money.** A `RuleBasedOrchestrator` (no LLM calls) is also available for cost-free deployments. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) §11 for the full table.

## Dependencies (preliminary, will be pinned in `pyproject.toml`)

System:
- Python 3.11+
- CUDA-capable GPU (8 GB+ VRAM comfortable; CPU works for CrystaLLM but is slow)
- `uv` for environment and lockfile management

Python:
- `alignn` — property prediction (NIST, MIT)
- `crystallm` — structure generation (lantunes, MIT)
- `mattergen` — structure generation, Phase 2 (Microsoft, MIT)
- `pymatgen`, `ase` — CIF / structure handling
- `mp-api` — Materials Project client
- `torch` (CUDA build matching your driver)
- `anthropic` — orchestrator LLM calls
- `pydantic`, `httpx`, `aiosqlite`, `typer`, `rich`

## Setup

```bash
git clone <repo-url> crucible
cd crucible
uv sync                                # creates .venv and installs from pyproject.toml
cp .env.example .env                   # fill ANTHROPIC_API_KEY, MP_API_KEY
cp crucible.yaml.example crucible.yaml # tweak target, budget, plugins
python scripts/check_gpu.py            # verify CUDA + VRAM
```

## Run

```bash
# Discover materials for the target configured in crucible.yaml
python -m crucible run --budget 100

# Predict properties for an existing CIF
python -m crucible predict path/to/structure.cif

# Show leaderboard + gauntlet histogram for the latest run
python -m crucible status

# List available plugins (generators, predictors, rankers, ...)
python -m crucible plugins
```

## Environment variables

| Variable | Purpose | Required when |
|---|---|---|
| `ANTHROPIC_API_KEY` | Orchestrator LLM calls | `orchestrator.name = claude_tools` |
| `MP_API_KEY` | Materials Project queries | `materials_project.enabled = true` |
| `CUDA_VISIBLE_DEVICES` | GPU selection | Multi-GPU host |
| `CRUCIBLE_OUTPUT_DIR` | Override `run.output_dir` | Optional |

Structural choices (which plugins, thresholds, budgets) live in `crucible.yaml`, not `.env`. If a value matters for reproducing a run, it goes in YAML.

## Status

Weekend MVP — APIs and module layout subject to change. See `TODO.md` for what's done and what's next.
