"""Default `Orchestrator` — Anthropic SDK tool-use loop on Claude Sonnet 4.6.

Drives the discovery loop by calling five tools (`generate_structures`,
`relax`, `predict`, `score_and_rank`, `query_cache`). Used in solo Phase 1
runs and any sponsor-funded central deployment. See ARCHITECTURE.md §6 and
playbook §G. Implemented in Phase 1.
"""
