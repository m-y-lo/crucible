"""CrystaLLM `Generator` plugin — local pretrained autoregressive LM.

Loads weights from the path given in plugin options, samples N CIFs for a
prompt, and post-processes via pymatgen. CrystaLLM is not on PyPI; install
from source per docs/install.md. Implemented in Phase 1.
"""
