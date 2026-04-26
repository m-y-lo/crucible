"""ALIGNN ``Predictor`` plugin — wraps pretrained property checkpoints.

Default checkpoints (per ARCHITECTURE.md section 7):

  - ``jv_formation_energy_peratom_alignn``  (eV/atom, JARVIS-DFT)
  - ``jv_optb88vdw_bandgap``                (eV, JARVIS-DFT)

Both are downloaded on first use via ``alignn.pretrained.get_prediction``
(stored under ``~/.cache/alignn``).

Status as of 2026-04-26 on macOS Apple Silicon: ALIGNN imports
``dgl``, whose prebuilt graphbolt ``.dylib`` is missing on this
platform for the torch versions we use. ``__init__`` therefore raises
``RuntimeError`` with a clear message; the registry surfaces it as a
tool error and the orchestrator's loop stays alive. On Linux/CUDA, or
once DGL ships proper macOS wheels, this file works as-is.
"""

from __future__ import annotations

from crucible.core.models import ModelProvenance
from crucible.core.units import (
    BANDGAP_KEY,
    EV,
    EV_PER_ATOM,
    FORMATION_ENERGY_KEY,
)


# Canonical default checkpoints. Override via the ``checkpoints``
# constructor arg (or the ``crucible.predictors[].options.checkpoints``
# YAML field).
_DEFAULT_CHECKPOINTS: dict[str, str] = {
    FORMATION_ENERGY_KEY: "jv_formation_energy_peratom_alignn",
    BANDGAP_KEY: "jv_optb88vdw_bandgap",
}

# Property key -> unit string for the ModelProvenance.units payload.
_DEFAULT_UNITS: dict[str, str] = {
    FORMATION_ENERGY_KEY: EV_PER_ATOM,
    BANDGAP_KEY: EV,
}


class AlignnPredictor:
    """Concrete ``Predictor`` backed by ALIGNN's pretrained checkpoints."""

    name = "alignn"

    def __init__(
        self,
        checkpoints: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
    ) -> None:
        # Eager probe: surface DGL/ALIGNN failures at registry-load time
        # rather than deep inside predict().
        try:
            import alignn  # noqa: F401
            import dgl  # noqa: F401
            from dgl import graphbolt  # noqa: F401
            from alignn.pretrained import get_prediction  # noqa: F401
        except (ImportError, FileNotFoundError) as e:
            raise RuntimeError(
                "ALIGNN/dgl import failed: "
                f"{type(e).__name__}: {e}. On macOS Apple Silicon, DGL's "
                "prebuilt graphbolt library is missing; this predictor "
                "is unusable until DGL ships an Apple Silicon binary."
            ) from e

        self._checkpoints = dict(checkpoints) if checkpoints else dict(_DEFAULT_CHECKPOINTS)
        self._units = dict(units) if units else dict(_DEFAULT_UNITS)

        from alignn import __version__ as alignn_version

        # The provenance carries every property -> unit mapping in one
        # place so callers (LocalStore.insert_prediction) can persist it
        # without round-tripping through this object.
        self.provenance = ModelProvenance(
            model_id="alignn",
            checkpoint=",".join(sorted(self._checkpoints.values())),
            dataset="JARVIS-DFT",
            version=str(alignn_version),
            units=self._units,
        )

    def predict(self, cif: str) -> dict[str, float]:
        """Run every configured checkpoint on ``cif`` and return the
        merged property dict.

        Property keys embed units (e.g. ``formation_energy_eV_per_atom``)
        per the playbook §3.B rule. The orchestrator persists this dict
        verbatim into ``predictions.values_json``.
        """
        from alignn.pretrained import get_prediction
        from pymatgen.core import Structure

        atoms = Structure.from_str(cif, fmt="cif").to_ase_atoms()
        out: dict[str, float] = {}
        for property_key, checkpoint_name in self._checkpoints.items():
            value = get_prediction(model_name=checkpoint_name, atoms=atoms)
            # ``get_prediction`` returns either a scalar or a 1-element
            # tensor depending on alignn release; normalize to float.
            try:
                out[property_key] = float(value)
            except (TypeError, ValueError):
                out[property_key] = float(value[0])
        return out
