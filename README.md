# Crucible

A desktop materials discovery engine. Multi-agent Python workflow that generates novel crystal structures and screens them for useful properties (formation energy, mechanical, electronic) on a consumer GPU — an indie, local analogue of large-scale platforms like the DOE's FORUM-AI.

## How it works

1. **Generate** — agents propose novel crystal structures via generative models (CrystaLLM, MatterGen), emitted as CIF files.
2. **Predict** — CIFs are passed to the ALIGNN Pretrained Models API for property prediction.
3. **Rank & iterate** — agents score candidates (e.g. for solid-state batteries, carbon capture, extreme-heat alloys) and feed results back into the generator.

Long-term: same code path, scaled out folding@home-style across volunteer GPUs.

## Dependencies (preliminary)

System:
- Python 3.11+
- CUDA-capable GPU (recommended)
- `uv` or `pip` for environment management

Python packages (pin versions in `requirements.txt` / `pyproject.toml`):
- `alignn` — property prediction
- `crystallm` and/or `mattergen` — structure generation
- `pymatgen`, `ase` — CIF / structure handling
- `torch` (CUDA build matching your driver)
- `anthropic` — agent orchestration
- `pydantic`, `httpx` — API layer
- `rich` — CLI output

## Setup

```bash
git clone <repo-url> crucible
cd crucible
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env   # then fill in keys
```

## Run

```bash
# Single discovery run
python -m crucible.run --target battery-cathode --budget 100

# Predict properties for an existing CIF
python -m crucible.predict path/to/structure.cif

# Launch the multi-agent loop
python -m crucible.agents.orchestrator
```

## Environment variables

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Agent orchestration via Claude |
| `ALIGNN_API_URL` | ALIGNN Pretrained Models endpoint |
| `ALIGNN_API_KEY` | ALIGNN auth token (if required) |
| `MATTERGEN_MODEL_PATH` | Local path to MatterGen weights |
| `CRYSTALLM_MODEL_PATH` | Local path to CrystaLLM weights |
| `CUDA_VISIBLE_DEVICES` | GPU selection |
| `CRUCIBLE_OUTPUT_DIR` | Where generated CIFs and reports are written |

## Status

Weekend MVP — APIs and module layout subject to change.
