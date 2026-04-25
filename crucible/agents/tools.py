"""Anthropic tool schemas exposed to the Claude orchestrator.

Five tools: `generate_structures`, `relax`, `predict`, `score_and_rank`,
`query_cache`. Each tool's `dispatch` calls a registry-loaded plugin.
Implemented in Phase 1.
"""
