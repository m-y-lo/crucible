"""Shared SQLite DDL applied by both `LocalStore` and `LocalQueue`.

Both components share one `crucible.db` file so the orchestrator can join
across all tables. Each component opens its own connection (sync sqlite3
for LocalStore, async aiosqlite for LocalQueue) and runs `executescript`
on this constant in its `__init__` — `CREATE TABLE IF NOT EXISTS` makes
that idempotent.

Deviation from ARCHITECTURE.md §4: `structures.num_sites` is NULLABLE
(rather than NOT NULL) for now. The `Structure` dataclass in
`crucible.core.models` is intentionally pymatgen-free and cannot compute
num_sites without parsing the CIF; Ani's future `hashing.from_cif()`
factory will populate it. Until then this column is null on store-only
insertions. Same reasoning applies to `density_g_per_cm3`.

Foreign-key enforcement is off by default in SQLite and we leave it that
way for Phase 1 — tests can insert structures without first seeding
`runs`. We can flip `PRAGMA foreign_keys = ON` once the orchestrator
always inserts a `runs` row before any child rows.
"""

SCHEMA = """
-- runs: every invocation of `crucible run`
CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  target      TEXT NOT NULL,
  config_json TEXT NOT NULL,
  budget      INTEGER NOT NULL,
  started_at  TIMESTAMP NOT NULL,
  ended_at    TIMESTAMP
);

-- structures: one row per unique structure_hash (post-canonicalization)
CREATE TABLE IF NOT EXISTS structures (
  structure_hash    TEXT PRIMARY KEY,
  cif               TEXT NOT NULL,
  composition       TEXT NOT NULL,
  space_group       INTEGER NOT NULL,
  prototype_label   TEXT NOT NULL,
  num_sites         INTEGER,
  density_g_per_cm3 REAL,
  source_generator  TEXT NOT NULL,
  source_run_id     TEXT NOT NULL,
  created_at        TIMESTAMP NOT NULL,
  FOREIGN KEY (source_run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_structures_proto
  ON structures(prototype_label, composition);
CREATE INDEX IF NOT EXISTS idx_structures_run
  ON structures(source_run_id);

-- predictions: one row per (structure, model_checkpoint, version) tuple
CREATE TABLE IF NOT EXISTS predictions (
  prediction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash TEXT NOT NULL,
  model_id       TEXT NOT NULL,
  checkpoint     TEXT NOT NULL,
  dataset        TEXT NOT NULL,
  version        TEXT NOT NULL,
  values_json    TEXT NOT NULL,
  units_json     TEXT NOT NULL,
  latency_ms     INTEGER,
  created_at     TIMESTAMP NOT NULL,
  FOREIGN KEY (structure_hash) REFERENCES structures(structure_hash),
  UNIQUE (structure_hash, model_id, checkpoint, version)
);

CREATE INDEX IF NOT EXISTS idx_predictions_struct
  ON predictions(structure_hash);

-- rankings: one row per (structure, run, target, ranker_version) tuple
CREATE TABLE IF NOT EXISTS rankings (
  ranking_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_hash  TEXT NOT NULL,
  run_id          TEXT NOT NULL,
  target          TEXT NOT NULL,
  ranker_name     TEXT NOT NULL,
  ranker_version  TEXT NOT NULL,
  passes_criteria INTEGER NOT NULL,
  score           REAL,
  reasoning_json  TEXT,
  created_at      TIMESTAMP NOT NULL,
  FOREIGN KEY (structure_hash) REFERENCES structures(structure_hash),
  FOREIGN KEY (run_id) REFERENCES runs(run_id),
  UNIQUE (structure_hash, run_id, target, ranker_name, ranker_version)
);

CREATE INDEX IF NOT EXISTS idx_rankings_run_score
  ON rankings(run_id, target, score DESC);

-- jobs: durable async queue (read/written by LocalQueue)
CREATE TABLE IF NOT EXISTS jobs (
  job_id       TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  status       TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, kind);

-- gauntlet_events: per-stage filter outcomes (drives reject-rate stats)
CREATE TABLE IF NOT EXISTS gauntlet_events (
  event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id         TEXT NOT NULL,
  stage          TEXT NOT NULL,
  passed         INTEGER NOT NULL,
  reason         TEXT,
  structure_hash TEXT,
  created_at     TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gauntlet_run
  ON gauntlet_events(run_id, stage, passed);
"""
