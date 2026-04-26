"""CHGNet ``Relaxer`` — universal MLP, charge-aware, MP-trained.

Wraps ``chgnet.model.StructOptimizer`` to satisfy
``crucible.core.protocols.Relaxer``:

  relax(cif, max_steps) -> (relaxed_cif, total_energy_eV)

Why this lives here today (and not just Phase 2):
ALIGNN-FF currently breaks on macOS Apple Silicon because DGL's
prebuilt graphbolt C++ library is missing. CHGNet has a pure-PyTorch
backend, no DGL, and runs on Apple-Silicon MPS as well as CUDA. Giving
the discovery loop a working relaxer today unblocks the cheap-energy
screen stage even before ALIGNN is fixed.

Cell convention: input/output CIFs are whatever the caller produced.
Internally we round-trip through ``pymatgen.Structure`` and
``CifWriter``; the relaxed structure is the converged geometry.
"""

from __future__ import annotations

from typing import Any

from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter

from crucible.core.models import ModelProvenance
from crucible.core.units import EV, EV_PER_ATOM


# Lazy import: keep package import-time cheap and avoid loading torch
# unless a CHGNet plugin is actually instantiated.
_CHGNET_MODEL: Any | None = None
_OPTIMIZER: Any | None = None


def _load_optimizer() -> Any:
    """Instantiate (and cache) a ``StructOptimizer`` once per process."""
    global _CHGNET_MODEL, _OPTIMIZER
    if _OPTIMIZER is not None:
        return _OPTIMIZER
    from chgnet.model import CHGNet, StructOptimizer

    _CHGNET_MODEL = CHGNet.load()
    _OPTIMIZER = StructOptimizer(model=_CHGNET_MODEL, optimizer_class="FIRE")
    return _OPTIMIZER


class ChgnetRelaxer:
    """Concrete ``Relaxer`` plugin backed by CHGNet."""

    name = "chgnet"

    def __init__(self, fmax: float = 0.1, verbose: bool = False) -> None:
        # Probe the import surface eagerly so registry.load fails fast
        # with a useful message rather than blowing up mid-relaxation.
        try:
            import chgnet  # noqa: F401
        except ImportError as e:  # pragma: no cover - environment issue
            raise RuntimeError(
                "chgnet is not installed; run `uv sync --extra ml` "
                "to pull torch + chgnet + alignn"
            ) from e

        self._fmax = float(fmax)
        self._verbose = bool(verbose)

        # The provenance string is the chgnet package version; downstream
        # callers (LocalStore.insert_prediction) use it as the immutable
        # tag so re-running with a different chgnet release counts as a
        # different prediction.
        from chgnet import __version__ as chgnet_version

        self.provenance = ModelProvenance(
            model_id="chgnet",
            checkpoint="default-pretrained",
            dataset="MPtrj",
            version=str(chgnet_version),
            units={"total_energy": EV, "energy_per_atom": EV_PER_ATOM},
        )

    def relax(self, cif: str, max_steps: int = 200) -> tuple[str, float]:
        """Relax ``cif`` for up to ``max_steps`` steps.

        Returns ``(relaxed_cif, total_energy_eV)``. ``total_energy_eV`` is
        the energy of the final relaxed configuration in absolute eV
        (not per-atom; multiply ``num_sites * eV_per_atom`` at the call
        site if you need per-atom).
        """
        optimizer = _load_optimizer()
        structure = Structure.from_str(cif, fmt="cif")
        result = optimizer.relax(
            structure, fmax=self._fmax, steps=max_steps, verbose=self._verbose
        )
        relaxed: Structure = result["final_structure"]
        # CHGNet's TrajectoryObserver records total energy in eV at each step.
        total_energy_eV = float(result["trajectory"].energies[-1])
        return str(CifWriter(relaxed)), total_energy_eV
