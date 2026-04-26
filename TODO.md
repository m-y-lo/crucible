# TODO

Shared brain for Crucible. Move items between phases as work progresses. See `ARCHITECTURE.md` for the design these tasks implement.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done. Drop inline `# TODO:` / `# FIXME:` notes in code when you spot something minor — don't break flow to come back here.

---

## Phase 0 — Bootstrapping (1–2 days)

- [x] `pyproject.toml` skeleton — project metadata + empty entry-point groups for all 7 plugin kinds (generators, relaxers, predictors, rankers, orchestrators, stores, queues).
- [x] `uv` lockfile — run `uv sync --extra ml` locally to resolve and lock `torch` + `alignn` + the rest. Must run on each contributor's machine; not committed-as-pinned to the repo at this stage.
- [x] `crucible/` package skeleton — `__init__.py` files for every subpackage; module-level docstrings on every planned file in the layout (`core/`, `gauntlet/`, `data/`, `generators/`, `relaxers/`, `predictors/`, `rankers/`, `orchestrators/`, `stores/`, `queues/`, `agents/`, `reports/`).
- [x] `.env.example` with `ANTHROPIC_API_KEY`, `MP_API_KEY`, `CUDA_VISIBLE_DEVICES`, `CRUCIBLE_OUTPUT_DIR`.
- [x] `crucible.yaml.example` matching ARCHITECTURE.md §7.
- [x] `ruff` + `pyright` + `pytest` configs in `pyproject.toml`.
- [x] `scripts/check_gpu.py` — smoke-test `torch.cuda.is_available()` and report VRAM.
- [x] `.gitignore` — Python caches, .venv, .env, runs/, model weights, OS junk.

---

## Phase 1 — MVP single-process loop (the weekend)

### Core

- [x] `core/models.py` — `Structure`, `Prediction`, `Job`, `Result`, `ModelProvenance`.
- [x] `core/protocols.py` — every contract from ARCHITECTURE.md §3.
- [x] `core/units.py` — eV, eV/atom, GPa, Å + safe converters.
- [x] `core/hashing.py` — canonical primitive-cell sha256 + AFLOW prototype label. Plus `hash_structure()` / `prototype_label_of()` Structure-input variants used by the gauntlet pipeline.
- [x] `core/config.py` — pydantic schema for `crucible.yaml`.
- [x] `core/registry.py` — entry-point loader with `lru_cache`.
- [x] `core/logging.py` — JSON line logger to file + rich console.

### Storage & queue

- [x] `stores/sqlite_store.py` `LocalStore` — applies the SQLite schema in `__init__`, implements all `ResultStore` methods.
- [x] `queues/local_queue.py` `LocalQueue` over the `jobs` table + asyncio.Event.

### Gauntlet

- [x] `gauntlet/parse.py` — CIF → pymatgen.Structure with structured rejection, never raises.
- [x] `gauntlet/composition.py` — reduced formula + BVAnalyzer charge balance.
- [x] `gauntlet/geometry.py` — min interatomic distance (0.7×Σ radii) + cell volume per atom in [5, 100] Å³.
- [x] `data/mp_client.py` — cached `MPRester` wrapper. SQLite cache, JSON-serialized payloads, separate cache namespaces per method.
- [x] `gauntlet/novelty.py` — flag rediscoveries against MP via StructureMatcher; conservative on MP outage.
- [x] `gauntlet/dedup.py` — three-tier (hash exact → prototype bucket → StructureMatcher fallback). Stateful `Deduplicator` per run.
- [x] `gauntlet/pipeline.py` — composes stages with early exit; returns `GauntletResult` with event log for callers to persist.

### Generators / Relaxers / Predictors / Rankers

- [ ] `generators/crystallm.py` — load weights, sample N CIFs, post-process via pymatgen.
- [x] `generators/random_baseline.py` — rattles a seed CIF / built-in NaCl baseline with reproducible RNG for sanity tests.
- [ ] `relaxers/alignn_ff.py` — single-point energy for the cheap screen.
- [ ] `predictors/alignn.py` — wraps `jv_formation_energy_peratom_alignn` and `jv_optb88vdw_bandgap`, populates `ModelProvenance`.
- [ ] `rankers/battery_cathode.py` — `criteria()` (contains-Li, E_form < −1.0 eV/atom, bandgap < 1.5 eV) + `score()` with thresholds in docstring.

### Orchestrator & CLI

- [ ] `agents/tools.py` — five Claude tool schemas.
- [ ] `agents/prompts.py` — system prompt + battery-cathode framing.
- [ ] `orchestrators/claude_tools.py` — `ClaudeOrchestrator` Anthropic-SDK tool-use loop, default `claude-sonnet-4-6`.
- [ ] `cli.py` — `crucible run`, `crucible predict <cif>`, `crucible status`, `crucible plugins`.
- [ ] `reports/status.py` — leaderboard + gauntlet histogram from SQLite.

### Validation

- [ ] Smoke test: `crucible run --budget 20` produces ≥1 structure that passes all gauntlet stages and lands in `rankings`.
- [x] `test_units.py` — done.
- [x] `test_registry.py` — done. Also written outside TODO: `test_config.py`, `test_logging.py`, active `test_store.py`, active `test_queue.py`.
- [x] `test_hashing.py`, `test_gauntlet_parse.py`, `test_gauntlet_composition.py`, `test_gauntlet_geometry.py`, `test_gauntlet_novelty.py`, `test_gauntlet_dedup.py`, `test_gauntlet_pipeline.py`, `test_generators_random_baseline.py`, `test_mp_client.py`. Total repo: 116 passing.

---

## Phase 2 — Multi-target, multi-generator, plugin maturity

- [ ] `generators/mattergen_colab.py` — HTTP client to a user-run Colab notebook.
- [ ] `docs/colab/mattergen_server.ipynb` — Colab template that exposes `/generate`.
- [ ] `generators/mattergen_local.py` — local pretrained MatterGen with Hydra config wrapper.
- [ ] `rankers/refractory_alloy.py`.
- [ ] `rankers/co2_sorbent.py`.
- [ ] `relaxers/chgnet.py`.
- [ ] `relaxers/mace.py`.
- [ ] `predictors/chgnet_ehull.py` — energy-above-hull stability filter.
- [ ] `data/calibration.py` — `crucible calibrate` command: score known MP structures, report MAE.
- [ ] `data/seeds.py` — pull top-K known structures for a target.
- [ ] `stores/parquet_export.py` — `crucible export --format parquet`.
- [ ] Nightly batch full pairwise StructureMatcher dedup (`crucible dedup --since 24h`).
- [ ] `orchestrators/rule_based.py` — `RuleBasedOrchestrator` for zero-API-cost runs.
- [ ] `docs/plugins.md` — third-party plugin authoring guide.

---

## Phase 3 — HTTP worker scale-out

- [ ] FastAPI `crucible-server`: `/enqueue`, `/dequeue`, `/result`, bearer-token auth.
- [ ] `queues/http_queue.py` `HTTPQueue` against `JobQueue` protocol.
- [ ] `stores/remote_store.py` `RemoteStore` against `ResultStore` protocol.
- [ ] `workers/crucible_worker/` separate package — long-poll `/dequeue`, run gauntlet stages 1–7, post result.
- [ ] Append-only Parquet event log on the server; nightly DuckDB materialized view.
- [ ] 2× redundant scheduling + disagreement detector for `predict` jobs.
- [ ] `pipx install crucible-worker` distribution; CLI flags `--server --token --gpu`.
- [ ] Read-only web dashboard with throughput + agreement rate.
- [ ] Multi-machine soak test: 3 external workers × 24h, zero data loss.

---

## Phase 4 — BOINC + public launch

- [ ] BOINC workunit schema (canonical CIF + checkpoint id + binary hash).
- [ ] Prebuilt CPU-only and CUDA worker binaries; signed manifests.
- [ ] Adaptive replication (3× → 2× on trusted hosts) + 1% spot-check re-issue.
- [ ] Public leaderboard + symbolic incentives (badges, co-authorship roll-up).
- [ ] Landing page with contributor stats.
- [ ] Public soak: 50 distinct hosts, replication-disagreement <1%.

---

## Done

- [x] Initial repo + README scaffold.
- [x] `playbook.md` — git/AI-agent rules, plus materials-domain math/units rules.
- [x] Architecture planning session — `ARCHITECTURE.md` produced; first MVP target locked in (battery cathode); first generator picked (CrystaLLM local + MatterGen-via-Colab adapter); package manager (`uv`); orchestrator default (Claude Sonnet 4.6); Materials Project integration scoped.
