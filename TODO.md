# TODO

Shared brain for Crucible. Move items between sections as work progresses. Keep entries short — link out to issues, PRs, or notes for detail.

## To Do

- [ ] Define target use case for MVP (battery cathode? CO₂ sorbent? alloy?)
- [ ] Stand up Python project skeleton (`pyproject.toml`, `crucible/` package, lint/test config)
- [ ] Pin CUDA-compatible `torch` build and verify GPU is visible
- [ ] Wire up ALIGNN client — auth, single-CIF predict, batch predict
- [ ] Integrate CrystaLLM generator (load weights, sample N structures)
- [ ] Integrate MatterGen generator as alternative backend
- [ ] CIF validation + dedup pass (`pymatgen` sanity checks before prediction)
- [ ] Scoring function per target (e.g. formation energy + bandgap window)
- [ ] Multi-agent orchestrator (generator agent ↔ critic agent ↔ ranker)
- [ ] Result store (SQLite or parquet) with structure hash → properties
- [ ] CLI entry points (`crucible.run`, `crucible.predict`)
- [ ] `.env.example` with all required variables
- [ ] Smoke test: end-to-end run that generates 10 CIFs and ranks them
- [ ] Stretch: distributed worker protocol (folding@home-style)

## In Progress

- [ ] _nothing yet_

## Done

- [x] Initial repo + README scaffold
