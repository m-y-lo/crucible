"""MatterGen `Generator` plugin via remote Colab notebook.

HTTP client to a user-run Colab notebook exposing a `/generate` endpoint.
Lets a contributor delegate the heavy MatterGen inference to a Colab GPU
while the orchestrator keeps running locally. Implemented in Phase 2.
"""
