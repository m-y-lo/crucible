"""Pull top-K known structures for a target as conditioning seeds.

Used by generators that support conditional sampling (e.g. MatterGen). For
"battery cathode", returns the highest-rated known cathodes from MP.
Implemented in Phase 2.
"""
