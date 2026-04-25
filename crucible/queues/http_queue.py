"""`HTTPQueue` — worker-side `JobQueue` for Phase 3 fleet operation.

Long-polls `/dequeue`, posts results to `/jobs/{id}/result`. Bearer-token
auth. Volunteers run this; orchestrator runs centrally. Implemented in
Phase 3.
"""
