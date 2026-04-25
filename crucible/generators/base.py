"""Optional mixin/base class shared by `Generator` plugins.

Houses post-processing helpers that turn raw model output (CIF strings,
sometimes with garbage prefixes) into validated `Structure` objects.
Implemented in Phase 1 alongside the first concrete generator.
"""
