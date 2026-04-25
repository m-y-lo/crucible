# Crucible Architecture

This is the design source of truth. Read this before adding code, plugins, or rankers. The goal: a single-machine MVP today, an HTTP-server / pipx-worker fleet for Phase 2, and a BOINC-integrated public project for Phase 3 — all sharing one codebase, swapped via config.

---

## 0. Core idea in one paragraph

A `Generator` plugin proposes novel crystal structures (CIF strings). They run a **validation gauntlet** — parse, composition sanity, geometry sanity, novelty check against Materials Project, dedup, cheap-energy screen — and the survivors are scored by a `Predictor` plugin (ALIGNN's pretrained checkpoints). A `Ranker` plugin applies target-specific hard gates and a scalar score. An `Orchestrator` plugin (default: a Claude Sonnet 4.6 tool-use loop) decides when to generate, when to predict, when to stop, and how to condition the next batch on top survivors. Every component crosses module boundaries through a `JobQueue` and a `ResultStore`, both of which have local and remote implementations.

---

## 1. High-level diagram

```
                        +--------------------------------+
                        |  crucible.orchestrators        |
                        |  (Claude tools | rule-based)   |
                        +---------------+----------------+
                                        |
                              tool calls | results
                                        v
+-----------------+    +-----------------+----------------+    +-----------------+
|  Generators     |    |        crucible.core             |    |   Rankers       |
|  (plugins)      |<-->|   registry · config · models ·   |<-->|   (plugins)     |
| crystallm       |    |   units · provenance · logging   |    | battery_cathode |
| mattergen_colab |    +-----------------+----------------+    | refractory      |
| mattergen_local |                      |                     | co2_sorbent     |
| random_baseline |                      |                     +-----------------+
+-----------------+                      |
                                         |
              +--------------------------+--------------------------+
              |                          |                          |
              v                          v                          v
      +---------------+          +---------------+          +---------------+
      |  Relaxers     |          |  Predictors   |          |  Gauntlet     |
      |  (plugins)    |          |  (plugins)    |          |  (stages)     |
      | alignn_ff     |          | alignn (jv_*) |          | parse         |
      | mace          |          | alignn (mp_*) |          | composition   |
      | chgnet        |          | chgnet_ehull  |          | geometry      |
      +-------+-------+          +-------+-------+          | novelty (MP)  |
              |                          |                  | dedup         |
              +--------------------------+----------+       +-------+-------+
                                                    |               |
                                          +---------v---------------v---+
                                          |        JobQueue            |   <-- LocalQueue (asyncio + SQLite)
                                          |        (interface)         |       HTTPQueue (Phase 3)
                                          +---------+------------------+       BOINCQueue (Phase 4)
                                                    |
                                          +---------v------------------+
                                          |        ResultStore         |   <-- LocalStore (SQLite)
                                          |        (interface)         |       RemoteStore (HTTP, Parquet)
                                          +----------------------------+
```

---

## 2. Package layout

```
crucible/
├── pyproject.toml
├── crucible.yaml.example
├── .env.example
├── README.md  TODO.md  ARCHITECTURE.md  playbook.md  LICENSE
├── crucible/
│   ├── __init__.py
│   ├── __main__.py             # python -m crucible -> Typer dispatcher
│   ├── cli.py                  # crucible run | predict | status | export | plugins
│   ├── core/
│   │   ├── protocols.py        # Generator, Relaxer, Predictor, Ranker, Orchestrator, JobQueue, ResultStore
│   │   ├── models.py           # Structure, Prediction, Job, Result, ModelProvenance dataclasses
│   │   ├── registry.py         # entry-point loader: load("generator", "crystallm")
│   │   ├── config.py           # pydantic schema for crucible.yaml
│   │   ├── units.py            # eV, eV/atom, GPa, Å constants + safe converters
│   │   ├── hashing.py          # canonical primitive-cell sha256 + AFLOW prototype label
│   │   ├── provenance.py       # ModelProvenance helpers (model_id, checkpoint, dataset, units)
│   │   └── logging.py          # JSON line logger to file + rich console
│   ├── gauntlet/
│   │   ├── parse.py            # CIF -> pymatgen.Structure
│   │   ├── composition.py      # reduced formula + BVAnalyzer charge balance
│   │   ├── geometry.py         # nearest-neighbor + volume sanity
│   │   ├── novelty.py          # Materials Project lookup -- flags rediscovery
│   │   ├── dedup.py            # coarse + StructureMatcher fallback
│   │   └── pipeline.py         # composes stages with early exit + gauntlet_events writes
│   ├── data/
│   │   ├── mp_client.py        # cached pymatgen.MPRester wrapper
│   │   ├── calibration.py      # score known MP structures, report MAE vs DFT
│   │   └── seeds.py            # pull top-K known structures as conditioning seeds
│   ├── generators/
│   │   ├── base.py
│   │   ├── crystallm.py        # local pretrained -- MVP
│   │   ├── mattergen_colab.py  # HTTP client to a Colab notebook
│   │   ├── mattergen_local.py  # local pretrained -- Phase 2
│   │   └── random_baseline.py  # rattle a known structure for sanity tests
│   ├── relaxers/
│   │   ├── alignn_ff.py        # MVP cheap-energy screen
│   │   ├── chgnet.py           # Phase 2
│   │   └── mace.py             # Phase 2
│   ├── predictors/
│   │   └── alignn.py           # wraps multiple pretrained checkpoints
│   ├── rankers/
│   │   ├── battery_cathode.py  # MVP
│   │   ├── refractory_alloy.py # Phase 2
│   │   └── co2_sorbent.py      # Phase 2
│   ├── orchestrators/
│   │   ├── claude_tools.py     # default: Anthropic tool-use loop, Sonnet 4.6
│   │   └── rule_based.py       # Phase 2: zero-API-cost state machine
│   ├── stores/
│   │   ├── sqlite_store.py     # MVP LocalStore
│   │   ├── parquet_export.py   # crucible export --format parquet
│   │   └── remote_store.py     # Phase 3 HTTP client
│   ├── queues/
│   │   ├── local_queue.py      # asyncio + aiosqlite MVP
│   │   └── http_queue.py       # Phase 3 worker-side client
│   ├── agents/
│   │   ├── tools.py            # tool-schema definitions for Claude
│   │   └── prompts.py          # system prompt + target-specific framing
│   └── reports/
│       └── status.py           # crucible status leaderboard + gauntlet histogram
├── workers/
│   └── crucible_worker/        # separate package, Phase 3
│       ├── pyproject.toml
│       └── worker.py
├── docs/
│   ├── plugins.md              # third-party plugin authoring -- Phase 2
│   └── colab/
│       └── mattergen_server.ipynb   # Phase 2: Colab template
├── scripts/
│   └── check_gpu.py
└── tests/
    ├── test_units.py
    ├── test_hashing.py
    ├── test_registry.py
    ├── test_gauntlet.py
    └── fixtures/
        └── known_good.cif
```

Module responsibilities (one sentence each):

| Module | Responsibility |
|---|---|
| `core/protocols.py` | Typed contracts every plugin must satisfy |
| `core/models.py` | Dataclasses crossing module boundaries with explicit units |
| `core/registry.py` | Discovers plugins via `importlib.metadata` entry points |
| `core/config.py` | Parses `crucible.yaml`, validates with pydantic |
| `core/units.py` | Single source of truth for unit constants and conversions |
| `core/hashing.py` | Canonical hash for a `Structure` (primitive cell + AFLOW prototype) |
| `core/provenance.py` | `(model_id, checkpoint, dataset, version, units)` tags |
| `gauntlet/*` | Staged validators with early exit; pure functions, no IO |
| `data/*` | Materials Project client, calibration runner, seed fetcher |
| `generators/*` | Concrete `Generator` plugins |
| `relaxers/*` | Concrete `Relaxer` plugins (MLP-based) |
| `predictors/*` | Concrete `Predictor` plugins (one wrapper, many checkpoints) |
| `rankers/*` | Target-specific `Ranker`s with criteria thresholds in the docstring |
| `orchestrators/*` | Concrete `Orchestrator` plugins (Claude / rule-based) |
| `stores/*` | Concrete `ResultStore` implementations |
| `queues/*` | Concrete `JobQueue` implementations |
| `agents/*` | Tool schemas and prompts the Claude orchestrator uses |
| `reports/*` | Read-only views over the store |

---

## 3. Core protocols

All plugins are typed `Protocol`s. Every prediction carries a `ModelProvenance` and unit suffixes live in dictionary keys, not separate fields. This is the rule that prevents silent unit mismatches across checkpoints.

```python
# crucible/core/models.py
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class ModelProvenance:
    """Identifies a specific predictor checkpoint, dataset, and units."""
    model_id: str          # e.g. "alignn"
    checkpoint: str        # e.g. "jv_formation_energy_peratom_alignn"
    dataset: str           # e.g. "JARVIS-DFT"
    version: str           # package version + git sha if available
    units: dict[str, str]  # {"formation_energy": "eV/atom", ...}

@dataclass
class Structure:
    """Wraps a CIF with canonical hashes and source tags. Cell convention: primitive."""
    cif: str
    structure_hash: str          # sha256 of canonicalized primitive CIF
    prototype_label: str         # AFLOW prototype, fast pre-filter
    composition: str             # reduced formula, e.g. "Li2MnO3"
    space_group: int
    source_generator: str        # plugin id, e.g. "crystallm"
    source_run_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Prediction:
    """A single model's prediction set for one structure. Units must be explicit."""
    structure_hash: str
    provenance: ModelProvenance
    values: dict[str, float]     # {"formation_energy_eV_per_atom": -1.7, ...}
    latency_ms: int
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Job:
    job_id: str
    kind: str                    # "generate" | "relax" | "predict" | "rank"
    payload: dict
    run_id: str
    enqueued_at: datetime
    attempts: int = 0

@dataclass
class Result:
    job_id: str
    ok: bool
    payload: dict
    error: str | None = None
    worker_id: str | None = None
```

```python
# crucible/core/protocols.py
from typing import Protocol, runtime_checkable
from crucible.core.models import Structure, Prediction, Job, Result, ModelProvenance

@runtime_checkable
class Generator(Protocol):
    """Proposes novel crystal structures as raw CIF strings."""
    name: str
    def sample(self, n: int, conditions: dict | None = None) -> list[str]:
        """Return up to n CIF strings. `conditions` may include
        `elements`, `target_props`, `space_group`, `seed_structures`."""

@runtime_checkable
class Relaxer(Protocol):
    """Relaxes a CIF using an ML potential and returns relaxed CIF + energy."""
    name: str
    provenance: ModelProvenance
    def relax(self, cif: str, max_steps: int = 200) -> tuple[str, float]:
        """Return (relaxed_cif, total_energy_eV)."""

@runtime_checkable
class Predictor(Protocol):
    """Predicts properties for a (preferably relaxed) CIF."""
    name: str
    provenance: ModelProvenance
    def predict(self, cif: str) -> dict[str, float]:
        """Return {property_name_with_units: value}.
        Keys MUST embed units, e.g. 'bandgap_eV', 'bulk_modulus_GPa'."""

@runtime_checkable
class Ranker(Protocol):
    """Maps predicted props to (a) a hard pass/fail and (b) a scalar score."""
    name: str
    target: str
    def criteria(self, props: dict[str, float]) -> bool:
        """Hard gates (e.g. contains-Li, bandgap < threshold)."""
    def score(self, props: dict[str, float]) -> float:
        """Higher is better; only meaningful when criteria() is True."""

@runtime_checkable
class Orchestrator(Protocol):
    """Decides when to generate, predict, rank, and stop."""
    name: str
    def run(self, target: str, budget: int) -> str:
        """Drive a full discovery loop. Returns the run_id."""

@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, job: Job) -> None: ...
    async def dequeue(self, kinds: list[str]) -> Job | None: ...
    async def mark_done(self, job_id: str, result: Result) -> None: ...
    async def get_result(self, job_id: str) -> Result | None: ...

@runtime_checkable
class ResultStore(Protocol):
    def insert_structure(self, s: Structure) -> None: ...
    def insert_prediction(self, p: Prediction) -> None: ...
    def get_by_hash(self, structure_hash: str) -> Structure | None: ...
    def list_by_target(self, target: str, limit: int = 100) -> list[dict]: ...
    def dedup_against_known(self, s: Structure) -> str | None:
        """Return the hash of an existing match, or None if novel."""
    def materialize_view(self, name: str) -> None:
        """Refresh a named denormalized view (e.g. 'top_battery_cathodes')."""
```

---

## 4. SQLite schema

```sql
-- runs: every invocation of `crucible run`
CREATE TABLE runs (
  run_id      TEXT PRIMARY KEY,
  target      TEXT NOT NULL,
  config_json TEXT NOT NULL,        -- frozen copy of crucible.yaml
  budget      INTEGER NOT NULL,
  started_at  TIMESTAMP NOT NULL,
  ended_at    TIMESTAMP
);

-- structures: one row per unique structure_hash (post-canonicalization)
CREATE TABLE structures (
  structure_hash    TEXT PRIMARY KEY,    -- sha256 of canonical primitive CIF
  cif               TEXT NOT NULL,
  composition       TEXT NOT NULL,       -- reduced formula
  space_group       INTEGER NOT NULL,
  prototype_label   TEXT NOT NULL,       -- AFLOW prototype, coarse-dedup key
  num_sites         INTEGER NOT NULL,
  density_g_per_cm3 REAL,
  source_generator  TEXT NOT NULL,
  source_run_id     TEXT NOT NULL,
  created_at        TIMESTAMP NOT NULL,
  FOREIGN KEY (source_run_id) REFERENCES runs(run_id)
);
CREATE INDEX idx_structures_proto ON structures(prototype_label, composition);
CREATE INDEX idx_structures_run   ON structures(source_run_id);

-- predictions: one row per (structure, model_checkpoint) pair
CREATE TABLE predictions (
  prediction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash TEXT NOT NULL,
  model_id       TEXT NOT NULL,    -- 'alignn'
  checkpoint     TEXT NOT NULL,    -- 'jv_formation_energy_peratom_alignn'
  dataset        TEXT NOT NULL,    -- 'JARVIS-DFT'
  version        TEXT NOT NULL,    -- pkg version + git sha
  values_json    TEXT NOT NULL,    -- {"formation_energy_eV_per_atom": -1.7, ...}
  units_json     TEXT NOT NULL,    -- {"formation_energy_eV_per_atom": "eV/atom"}
  latency_ms     INTEGER,
  created_at     TIMESTAMP NOT NULL,
  FOREIGN KEY (structure_hash) REFERENCES structures(structure_hash),
  UNIQUE (structure_hash, model_id, checkpoint, version)
);
CREATE INDEX idx_predictions_struct ON predictions(structure_hash);

-- rankings: one row per (structure, target, ranker_version)
CREATE TABLE rankings (
  ranking_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash  TEXT NOT NULL,
  run_id          TEXT NOT NULL,
  target          TEXT NOT NULL,
  ranker_name     TEXT NOT NULL,
  ranker_version  TEXT NOT NULL,
  passes_criteria INTEGER NOT NULL,   -- 0/1
  score           REAL,
  reasoning_json  TEXT,               -- {"contributions": {...}, "thresholds": {...}}
  created_at      TIMESTAMP NOT NULL,
  FOREIGN KEY (structure_hash) REFERENCES structures(structure_hash),
  FOREIGN KEY (run_id) REFERENCES runs(run_id),
  UNIQUE (structure_hash, run_id, target, ranker_name, ranker_version)
);
CREATE INDEX idx_rankings_run_score ON rankings(run_id, target, score DESC);

-- jobs: durable queue for asyncio LocalQueue (and HTTP server later)
CREATE TABLE jobs (
  job_id       TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,      -- 'generate'|'relax'|'predict'|'rank'
  status       TEXT NOT NULL,      -- 'queued'|'running'|'done'|'failed'
  run_id       TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json  TEXT,
  error        TEXT,
  attempts     INTEGER NOT NULL DEFAULT 0,
  worker_id    TEXT,
  enqueued_at  TIMESTAMP NOT NULL,
  started_at   TIMESTAMP,
  finished_at  TIMESTAMP
);
CREATE INDEX idx_jobs_status ON jobs(status, kind);

-- gauntlet_events: per-stage filter outcomes (drives reject-rate stats)
CREATE TABLE gauntlet_events (
  event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id         TEXT NOT NULL,
  stage          TEXT NOT NULL,    -- 'parse'|'composition'|'geometry'|'novelty'|'dedup'|'energy_screen'
  passed         INTEGER NOT NULL,
  reason         TEXT,
  structure_hash TEXT,             -- nullable: hash may not exist yet at parse failure
  created_at     TIMESTAMP NOT NULL
);
CREATE INDEX idx_gauntlet_run ON gauntlet_events(run_id, stage, passed);
```

**Key invariants.**
- `predictions` is normalized so multiple checkpoints can score the same `structure_hash`.
- `(structure_hash, model_id, checkpoint, version)` UNIQUE prevents duplicate predictions.
- `units_json` is mandatory and travels with every row.
- `rankings.ranker_version` lets us re-score with a tweaked formula without overwriting history.

---

## 5. Plugin discovery

Plugins are registered as `importlib.metadata` entry points in `pyproject.toml`. Third parties publish their own packages exposing the same entry-point groups; `pip install` makes them visible to Crucible.

```toml
# pyproject.toml (excerpt)
[project.entry-points."crucible.generators"]
crystallm        = "crucible.generators.crystallm:CrystaLLMGenerator"
mattergen_colab  = "crucible.generators.mattergen_colab:MatterGenColabGenerator"
mattergen_local  = "crucible.generators.mattergen_local:MatterGenLocalGenerator"
random_baseline  = "crucible.generators.random_baseline:RandomBaselineGenerator"

[project.entry-points."crucible.relaxers"]
alignn_ff = "crucible.relaxers.alignn_ff:AlignnFFRelaxer"
chgnet    = "crucible.relaxers.chgnet:ChgnetRelaxer"

[project.entry-points."crucible.predictors"]
alignn = "crucible.predictors.alignn:AlignnPredictor"

[project.entry-points."crucible.rankers"]
battery_cathode  = "crucible.rankers.battery_cathode:BatteryCathodeRanker"
refractory_alloy = "crucible.rankers.refractory_alloy:RefractoryAlloyRanker"
co2_sorbent      = "crucible.rankers.co2_sorbent:CO2SorbentRanker"

[project.entry-points."crucible.orchestrators"]
claude_tools = "crucible.orchestrators.claude_tools:ClaudeOrchestrator"
rule_based   = "crucible.orchestrators.rule_based:RuleBasedOrchestrator"

[project.entry-points."crucible.stores"]
sqlite = "crucible.stores.sqlite_store:LocalStore"

[project.entry-points."crucible.queues"]
local = "crucible.queues.local_queue:LocalQueue"
```

```python
# crucible/core/registry.py (sketch)
from importlib.metadata import entry_points
from functools import lru_cache

GROUPS = {
    "generator":    "crucible.generators",
    "relaxer":      "crucible.relaxers",
    "predictor":    "crucible.predictors",
    "ranker":       "crucible.rankers",
    "orchestrator": "crucible.orchestrators",
    "store":        "crucible.stores",
    "queue":        "crucible.queues",
}

@lru_cache
def _eps(kind: str):
    return {ep.name: ep for ep in entry_points(group=GROUPS[kind])}

def list_plugins(kind: str) -> list[str]:
    return sorted(_eps(kind).keys())

def load(kind: str, name: str, **kwargs):
    ep = _eps(kind).get(name)
    if not ep:
        raise KeyError(f"No {kind} plugin named {name!r}; have {list_plugins(kind)}")
    cls = ep.load()
    return cls(**kwargs)
```

A third party publishes `crucible-plugin-mace` with its own `pyproject.toml`:

```toml
[project.entry-points."crucible.relaxers"]
mace = "crucible_plugin_mace:MaceRelaxer"
```

`pip install crucible-plugin-mace` makes `registry.load("relaxer", "mace")` work — no Crucible code change required.

---

## 6. Orchestration

The default orchestrator is `ClaudeOrchestrator`, an Anthropic SDK tool-use loop using **`claude-sonnet-4-6`**. It exposes five tools to the model:

```python
TOOLS = [
    {"name": "generate_structures",
     "description": "Sample N CIFs from a generator. Args: {generator, n, conditions}.",
     "input_schema": {...}},
    {"name": "relax",
     "description": "Run an MLP relaxer; returns relaxed CIF and total energy (eV).",
     "input_schema": {...}},
    {"name": "predict",
     "description": "Predict properties via a checkpoint. Returns dict with units in keys.",
     "input_schema": {...}},
    {"name": "score_and_rank",
     "description": "Apply target ranker; returns score and pass/fail per structure.",
     "input_schema": {...}},
    {"name": "query_cache",
     "description": "Look up existing predictions/rankings by structure_hash or run_id.",
     "input_schema": {...}},
]
```

```python
def run(target: str, budget: int):
    client = Anthropic()
    msgs = [{"role": "user", "content": SYSTEM_PROMPT.format(target=target, budget=budget)}]
    while not done(target, budget):
        resp = client.messages.create(model="claude-sonnet-4-6", tools=TOOLS, messages=msgs)
        if resp.stop_reason == "tool_use":
            for tu in resp.content:
                if tu.type == "tool_use":
                    out = dispatch(tu.name, tu.input)   # registry-loaded plugin call
                    msgs.append({"role": "assistant", "content": resp.content})
                    msgs.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": tu.id, "content": out}]})
        else:
            break
```

`RuleBasedOrchestrator` (Phase 2) implements the same `Orchestrator` protocol with a hand-written state machine — zero Claude API calls, used in the central Phase-2 deployment so volunteers don't pay anything.

**Upgrade trigger to LangGraph:** durable cross-run checkpointing, conditional routing across more than ~5 tools, or parallel multi-target fan-out. None of those are needed for the MVP.

---

## 7. Configuration

Two files. **YAML for structural choices, .env for secrets only.** If a value matters for reproducing a run, it goes in YAML.

```yaml
# crucible.yaml.example
run:
  target: battery_cathode      # ranker plugin name
  budget: 200                  # max structures fully predicted this run
  output_dir: ./runs

generators:
  - name: crystallm
    weight: 1.0
    options:
      checkpoint: lantunes/CrystaLLM-v1
      temperature: 0.9
      max_new_tokens: 1024

  # Optional: route some samples through a Colab MatterGen worker
  # - name: mattergen_colab
  #   weight: 0.5
  #   options:
  #     endpoint: https://your-colab-tunnel.example.com/generate
  #     auth_token_env: MATTERGEN_COLAB_TOKEN

relaxers:
  - name: alignn_ff
    options:
      max_steps: 100

predictors:
  - name: alignn
    options:
      checkpoints:
        - jv_formation_energy_peratom_alignn   # eV/atom
        - jv_optb88vdw_bandgap                 # eV

ranker:
  name: battery_cathode
  options:
    formation_energy_max_eV_per_atom: -1.0
    bandgap_max_eV: 1.5
    require_li: true

queue: { name: local }
store: { name: sqlite, path: ./runs/crucible.db }

orchestrator:
  name: claude_tools
  options:
    model: claude-sonnet-4-6
    max_iterations: 20

materials_project:
  enabled: true
  novelty_filter: true       # gauntlet rejects rediscoveries
  use_seeds: false           # Phase 2 feature
```

`.env` is for secrets only:
- `ANTHROPIC_API_KEY` — required only when `orchestrator.name = claude_tools`.
- `MP_API_KEY` — required when `materials_project.enabled = true`.
- `CUDA_VISIBLE_DEVICES` — GPU selection.
- `CRUCIBLE_OUTPUT_DIR` — overrides `run.output_dir`.

---

## 8. Job queue + scaling seam

`LocalQueue` and `HTTPQueue` both implement `JobQueue`. `LocalQueue` reads/writes the `jobs` table via aiosqlite and uses an asyncio.Event to wake dequeuers. `HTTPQueue` (Phase 3) is a thin httpx client against `POST /enqueue`, `GET /dequeue?kinds=...`, `POST /jobs/{id}/result`. The orchestrator never knows which is in use — it constructs whichever via `registry.load("queue", cfg.queue.name, **cfg.queue.options)`.

Same shape for `LocalStore` (sqlite) vs. `RemoteStore` (HTTP append-Parquet client) — both implement `ResultStore`. Swapping is one config line.

This is the seam that makes Phase 2/3 a config swap, not a rewrite.

---

## 9. Crowdsourcing path

### Phase 1 — today (single process)

- **Changes:** none extra. `LocalQueue` + `LocalStore` only.
- **Stays the same:** protocols, registry, gauntlet, ranker contracts.
- **Ready when:** full run completes locally, ≥1 structure passes the full gauntlet and lands in `rankings`.

### Phase 2 — multi-target, plugin maturity (still single machine)

- **Changes:** add MatterGen plugins (Colab + local), more rankers, more relaxers, MP calibration command, parquet export, nightly batch dedup, `RuleBasedOrchestrator`.
- **Stays the same:** protocols, schema, CLI shape.
- **Ready when:** three rankers usable; `crucible calibrate` reports MAE on MP structures; `crucible export --format parquet` ships.

### Phase 3 — HTTP server + pipx workers

- **Changes:** `crucible-server` (FastAPI: `/enqueue`, `/dequeue`, `/result` + bearer-token auth); `crucible-worker` package, `pipx install crucible-worker` exposing `crucible-worker --server <url> --token <pat>`; per-worker rate limit; 2× redundant scheduling for predict jobs with disagreement → tiebreaker. Stores diverge: server keeps Parquet event log + DuckDB analytics view; worker keeps tiny local SQLite cache.
- **Stays the same:** every plugin, every protocol, the ranker code, the YAML schema. Only `queue` and `store` config keys change.
- **Ready when:** 3 external machines run a worker for 24h with zero data loss, redundant-result agreement ≥98% for predict jobs, server survives a worker crash mid-job.

### Phase 4 — BOINC integration

- **Changes:** package each predict job as a BOINC workunit (input = canonicalized CIF + checkpoint id + binary hash; output = JSON predictions + signed worker manifest); adaptive replication (3× initially, drop to 2× on trusted hosts); spot-check by re-issuing 1% of completed jobs to a different host; ship prebuilt CPU-only and CUDA worker binaries; public leaderboard + co-authorship roll-up.
- **Stays the same:** `Predictor` protocol, the SQLite schema (predictions still keyed by `(structure_hash, model_id, checkpoint, version)`), the ranker code.
- **Ready when:** 50 distinct hosts have submitted ≥1 valid workunit, replication-disagreement rate <1%, public landing page lists active contributors.

---

## 10. Validation gauntlet

```
raw CIF (from Generator)
   |
   v
[1] parse              pymatgen.Structure.from_str          worker  (cheap)
   |  fails -> log gauntlet_event(stage=parse, passed=0)
   v
[2] composition        reduced formula sanity, oxidation    worker
                       states with BVAnalyzer, charge balance
   |
   v
[3] geometry           nearest-neighbor distance >= 0.7 *   worker
                       sum of covalent radii; max coord
                       number <= 16; cell volume sane
   |
   v
[4] novelty (MP)       MPRester lookup by composition;      worker (cached)
                       StructureMatcher against MP entries.
                       Flagged rediscoveries are recorded
                       but can be dropped or kept by config.
   |
   v
[5] dedup (coarse)     prototype_label + composition hit    worker (full
                       in this-run cache?                   pairwise StructureMatcher
                                                            runs nightly server-side)
   |
   v
[6] cheap energy       alignn-ff or chgnet single-point;    worker (GPU)
    screen             drop top X% highest-energy
   |
   v
[7] expensive          alignn jv_formation_energy +         worker (GPU)
    predict            alignn jv_bandgap (full inference)
   |
   v
[8] score & rank       Ranker.criteria() then               central (cheap, deterministic)
                       Ranker.score(); persists to rankings
   |
   v
top-K -> conditioning seeds for next generate batch
```

Stages 1–7 run wherever the GPU lives (in Phase 1, the local process; in Phase 3, the worker). Stage 8 always runs central so the ranker version and thresholds are consistent. Coarse dedup runs locally on the worker; full pairwise `StructureMatcher` is O(N²) and runs server-side as a nightly batch.

---

## 11. Cost & responsibility model

Who pays for the LLM calls and where the orchestrator runs is the single most important question for the crowdsourcing story. The `Orchestrator` plugin slot exists to give us a clean answer per phase.

| Phase | Where orchestrator runs | Who pays for Claude API | Volunteer needs API key? | Default orchestrator |
|---|---|---|---|---|
| Phase 1 (solo) | Local user's machine | Local user | Yes — their own | `ClaudeOrchestrator` (Sonnet 4.6) |
| Phase 2 (single-machine, multi-plugin) | Local user's machine | Local user | Yes — their own | `ClaudeOrchestrator` *or* `RuleBasedOrchestrator` |
| Phase 3 (HTTP fleet) | Project's central server | Project sponsor | **No — never** | `RuleBasedOrchestrator` (default) or `ClaudeOrchestrator` (sponsor-funded) |
| Phase 4 (BOINC, public) | Project's central server | Project sponsor | **No — never** | `RuleBasedOrchestrator` |

**The principle:** volunteers donate **compute**, not money. They never need an Anthropic account. The central server makes whatever LLM calls happen.

A typical Phase-1 solo run with ~20 tool-loop iterations is roughly **cents on Sonnet, ~$1 on Opus**. Hobbyist-scale fine.

---

## 12. Materials Project integration

Three uses, all funneled through one cached client (`crucible/data/mp_client.py`).

1. **Novelty filter (gauntlet stage 4).** Before scoring, query MP by composition; run `StructureMatcher` against returned entries; flag rediscoveries. Configurable: log-only, demote, or drop entirely.
2. **Predictor calibration (`crucible calibrate`).** For a sample of MP structures, run them through our ALIGNN pipeline and compare predictions against MP's published DFT values. Report MAE/RMSE per property. Live calibration number for trust.
3. **Conditioning seeds (`data/seeds.py`).** For a target like "Li-ion cathode", pull the top-K known cathodes from MP and feed them as prompts/conditioning to CrystaLLM or MatterGen.

**Caveat:** MatterGen was trained on MP + Alexandria. Its outputs will be biased toward MP-similar structures — the novelty filter is doubly important when MatterGen is in the generator mix.

`MP_API_KEY` env var required. Disk-cache MP queries by `(composition, query_hash)` — MP changes slowly, repeat queries are wasteful.

---

## 13. Observability

**MVP minimum.**
- Single structured logger (`core/logging.py`) emits one JSON line per event to both stdout (rich-prettified for humans) and `runs/{run_id}/events.jsonl`. Every line carries `run_id`, `stage`, `structure_hash` when known, `model_id` when relevant, `latency_ms`, and a timestamp.
- `crucible status` (in `reports/status.py`) reads SQLite and prints: current run id, budget consumed, count by gauntlet stage outcome, top-10 ranked structures (composition, score, key props), and a fail-reason histogram.
- `crucible export --format parquet` dumps `structures` ⋈ best-prediction-per-checkpoint ⋈ rankings to a portable Parquet for sharing.

**Phase 3 dashboard (deferred):** a small read-only web view over the central server showing the same `crucible status` data plus per-worker throughput, redundant-result agreement rate, and a global leaderboard.

---

## 14. Open follow-ups (not blocking MVP)

- GPU specs check (`scripts/check_gpu.py`) — determines whether MatterGen weights are loadable and which torch build to pin.
- License confirmation — currently MIT; consider Apache-2.0 if BOINC distribution path becomes serious (better patent grants).
- Multi-objective Pareto-front scoring — extend `Ranker` interface in Phase 2.
- Fine-tuning — entirely out of MVP scope; would warrant a `Trainer` plugin slot if added.
