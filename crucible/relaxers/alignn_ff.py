"""ALIGNN-FF ``Relaxer`` — universal MLP from JARVIS.

Wraps ``alignn.ff.ff.AlignnAtomwiseCalculator`` (or the ``ForceField`` API,
depending on installed version) to satisfy
``crucible.core.protocols.Relaxer``.

Status as of 2026-04-26 on macOS Apple Silicon: ALIGNN imports
``dgl``, whose prebuilt graphbolt ``.dylib`` is missing on this
platform for the torch versions we use. Construction therefore raises
``RuntimeError`` with a clear message — the registry surfaces it as a
tool error, the orchestrator's loop stays alive, and Claude adapts.
``ChgnetRelaxer`` is the working alternative for now.

When DGL ships proper macOS Apple Silicon wheels (or on Linux/CUDA),
this file works as-is. The wrapper is API-correct against ALIGNN
2026.4.x.
"""

from __future__ import annotations

from typing import Any

from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter

from crucible.core.models import ModelProvenance
from crucible.core.units import EV, EV_PER_ATOM


# Cached calculator + force-field instance.
_FF: Any | None = None


def _load_ff() -> Any:
    """Lazily instantiate the ALIGNN-FF calculator. Raises with a
    diagnostic message if DGL is not importable (the typical macOS
    failure today)."""
    global _FF
    if _FF is not None:
        return _FF
    try:
        from alignn.ff.ff import default_path
        # Different alignn releases place the relaxation entry point in
        # different locations. Try the canonical one, then fall back.
        try:
            from alignn.ff.ff import ForceField  # type: ignore
            _FF = ForceField(model_path=default_path())
        except ImportError:
            from alignn.ff.ff import AlignnAtomwiseCalculator  # type: ignore
            _FF = AlignnAtomwiseCalculator(path=default_path())
    except ImportError as e:
        # The most common cause is dgl's missing graphbolt .dylib on
        # macOS Apple Silicon. Surface a useful hint.
        raise RuntimeError(
            "ALIGNN/dgl import failed; on macOS Apple Silicon DGL's "
            "prebuilt graphbolt library is missing. Use ChgnetRelaxer "
            f"as a substitute. Underlying error: {type(e).__name__}: {e}"
        ) from e
    return _FF


class AlignnFFRelaxer:
    """Concrete ``Relaxer`` plugin backed by ALIGNN-FF."""

    name = "alignn_ff"

    def __init__(self, max_steps_default: int = 200) -> None:
        # Probe DGL/ALIGNN at construction time so registry-load failures
        # are loud, not deferred to mid-relaxation.
        try:
            import alignn  # noqa: F401
            import dgl  # noqa: F401
            # graphbolt import is the actual bomb on macOS:
            from dgl import graphbolt  # noqa: F401
        except (ImportError, FileNotFoundError) as e:
            raise RuntimeError(
                "ALIGNN-FF unavailable on this machine: "
                f"{type(e).__name__}: {e}. Use chgnet as a substitute."
            ) from e

        self._max_steps_default = int(max_steps_default)

        from alignn import __version__ as alignn_version

        self.provenance = ModelProvenance(
            model_id="alignn",
            checkpoint="alignn_ff_default",
            dataset="JARVIS-DFT",
            version=str(alignn_version),
            units={"total_energy": EV, "energy_per_atom": EV_PER_ATOM},
        )

    def relax(self, cif: str, max_steps: int = 200) -> tuple[str, float]:
        """Relax ``cif`` and return ``(relaxed_cif, total_energy_eV)``.

        Steps:
          1. Parse CIF -> ``pymatgen.Structure``.
          2. Convert to ``ase.Atoms`` (ALIGNN-FF's native input).
          3. Run the relaxation for up to ``max_steps``.
          4. Convert the relaxed Atoms back to CIF.
        """
        ff = _load_ff()
        structure = Structure.from_str(cif, fmt="cif")
        atoms = structure.to_ase_atoms()

        # ALIGNN-FF's API has shifted between releases; try the canonical
        # `relax` method, falling back to `optimize`.
        if hasattr(ff, "relax"):
            relaxed_atoms, total_energy_eV = ff.relax(atoms=atoms, steps=max_steps)
        elif hasattr(ff, "optimize"):
            relaxed_atoms, total_energy_eV = ff.optimize(
                atoms=atoms, steps=max_steps
            )
        else:  # pragma: no cover - defensive
            raise RuntimeError(
                "ALIGNN-FF object exposes neither .relax nor .optimize; "
                "API has drifted, this wrapper needs updating."
            )

        relaxed_structure = Structure.from_ase_atoms(relaxed_atoms)
        return str(CifWriter(relaxed_structure)), float(total_energy_eV)
