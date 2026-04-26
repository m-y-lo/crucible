"""ALIGNN ``Predictor`` plugin — dual-backend.

Default checkpoints (per ARCHITECTURE.md section 7):

  - ``jv_formation_energy_peratom_alignn``  (eV/atom, JARVIS-DFT)
  - ``jv_optb88vdw_bandgap_alignn``         (eV, JARVIS-DFT)

Two execution backends, selected by ``backend=`` (default ``"auto"``):

  - ``"in_process"`` — direct import of alignn into the calling Python.
    Works on Linux/CUDA out of the box. On macOS Apple Silicon the
    underlying DGL native libs (graphbolt, metis, GKlib) are missing
    or ABI-mismatched, so this path raises ``RuntimeError`` at
    construction.

  - ``"conda_subprocess"`` — invokes ``scripts/alignn_runner.py`` inside
    a ``crucible-alignn`` conda env via ``mamba run``. The conda env
    is the only setup where DGL+ALIGNN work natively on macOS Apple
    Silicon. See ``docs/install_alignn_macos.md`` for env creation.

  - ``"auto"`` — try in_process first; on ImportError/FileNotFoundError
    fall back to ``conda_subprocess`` if the env is detected.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from crucible.core.models import ModelProvenance
from crucible.core.units import (
    BANDGAP_KEY,
    EV,
    EV_PER_ATOM,
    FORMATION_ENERGY_KEY,
)


# Canonical default checkpoints. Names match alignn.pretrained.all_models.
_DEFAULT_CHECKPOINTS: dict[str, str] = {
    FORMATION_ENERGY_KEY: "jv_formation_energy_peratom_alignn",
    BANDGAP_KEY: "jv_optb88vdw_bandgap_alignn",
}

_DEFAULT_UNITS: dict[str, str] = {
    FORMATION_ENERGY_KEY: EV_PER_ATOM,
    BANDGAP_KEY: EV,
}

# Conda env name created by docs/install_alignn_macos.md. Override via
# CRUCIBLE_ALIGNN_CONDA_ENV if a user wants a non-default name.
_DEFAULT_CONDA_ENV = "crucible-alignn"


# ----- backend detection helpers -----------------------------------------


def _in_process_dgl_works() -> bool:
    """Return True iff alignn + dgl + graphbolt all import in this Python."""
    try:
        import dgl  # noqa: F401
        from dgl import graphbolt  # noqa: F401
        from alignn.pretrained import get_prediction  # noqa: F401
        return True
    except (ImportError, FileNotFoundError):
        return False


def _conda_runner_available(env_name: str) -> tuple[bool, str | None]:
    """Return (True, mamba_path) if the named conda env exists and exposes
    a runnable Python; (False, None) otherwise."""
    mamba = shutil.which("mamba") or shutil.which("conda")
    if mamba is None:
        return False, None
    try:
        out = subprocess.run(
            [mamba, "env", "list"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False, None
    return (env_name in out, mamba)


def _detect_backend(env_name: str) -> str:
    """Pick a backend automatically. Prefer in-process; fall back to
    conda subprocess only when in-process is unusable."""
    if _in_process_dgl_works():
        return "in_process"
    available, _ = _conda_runner_available(env_name)
    if available:
        return "conda_subprocess"
    return "in_process"  # so __init__ raises a useful error below


# ----- backends -----------------------------------------------------------


class _InProcessAlignn:
    def __init__(self, checkpoints: dict[str, str]) -> None:
        try:
            import alignn  # noqa: F401
            import dgl  # noqa: F401
            from dgl import graphbolt  # noqa: F401
            from alignn.pretrained import get_prediction  # noqa: F401
        except (ImportError, FileNotFoundError) as e:
            raise RuntimeError(
                "ALIGNN/dgl import failed: "
                f"{type(e).__name__}: {e}. On macOS Apple Silicon, set up "
                "the conda env per docs/install_alignn_macos.md and the "
                "predictor will switch to backend='conda_subprocess'."
            ) from e
        self._checkpoints = checkpoints
        from alignn import __version__ as v
        self._version = str(v)

    def predict(self, cif: str) -> dict[str, float]:
        from alignn.pretrained import get_prediction
        from pymatgen.core import Structure

        atoms = Structure.from_str(cif, fmt="cif").to_ase_atoms()
        out: dict[str, float] = {}
        for prop, ck in self._checkpoints.items():
            v = get_prediction(model_name=ck, atoms=atoms)
            try:
                out[prop] = float(v)
            except (TypeError, ValueError):
                out[prop] = float(v[0])
        return out


class _CondaSubprocessAlignn:
    """Run alignn inside ``mamba run -n <env>`` via ``scripts/alignn_runner.py``."""

    def __init__(
        self,
        checkpoints: dict[str, str],
        env_name: str,
        runner_path: Path,
    ) -> None:
        available, mamba = _conda_runner_available(env_name)
        if not available:
            raise RuntimeError(
                f"conda env {env_name!r} not found. Run "
                "`mamba env create -n crucible-alignn ...` per "
                "docs/install_alignn_macos.md."
            )
        if not runner_path.exists():
            raise RuntimeError(f"runner missing at {runner_path}")
        self._mamba = mamba
        self._env_name = env_name
        self._runner = runner_path
        self._checkpoints = checkpoints
        self._version = "subprocess"  # filled in by first call

    def predict(self, cif: str) -> dict[str, float]:
        ck_to_prop = {ck: prop for prop, ck in self._checkpoints.items()}
        with tempfile.NamedTemporaryFile(
            "w", suffix=".cif", delete=False
        ) as fh:
            fh.write(cif)
            cif_path = fh.name
        try:
            cmd = [
                self._mamba, "run", "-n", self._env_name,
                "python", str(self._runner),
                cif_path,
                *ck_to_prop.keys(),
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, check=False
            )
        finally:
            try:
                os.unlink(cif_path)
            except OSError:
                pass

        if proc.returncode != 0:
            raise RuntimeError(
                f"alignn_runner exited {proc.returncode}: "
                f"stdout={proc.stdout[-300:]} stderr={proc.stderr[-300:]}"
            )
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as e:
            raise RuntimeError(
                f"alignn_runner produced unparseable output: {proc.stdout[-300:]}"
            ) from e
        if "error" in payload:
            raise RuntimeError(f"alignn_runner error: {payload['error']}")

        # Map checkpoint-keyed runner output back to property-keyed result.
        return {ck_to_prop[ck]: float(v) for ck, v in payload.items()}


# ----- public class -------------------------------------------------------


class AlignnPredictor:
    """ALIGNN property predictor with macOS-friendly conda fallback."""

    name = "alignn"

    def __init__(
        self,
        checkpoints: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
        backend: str = "auto",
        conda_env: str | None = None,
        runner_path: Path | None = None,
    ) -> None:
        env_name = conda_env or os.environ.get(
            "CRUCIBLE_ALIGNN_CONDA_ENV", _DEFAULT_CONDA_ENV
        )
        self._checkpoints = dict(checkpoints) if checkpoints else dict(_DEFAULT_CHECKPOINTS)
        self._units = dict(units) if units else dict(_DEFAULT_UNITS)

        chosen = _detect_backend(env_name) if backend == "auto" else backend
        if chosen == "in_process":
            self._impl = _InProcessAlignn(self._checkpoints)
            version = self._impl._version
        elif chosen == "conda_subprocess":
            runner = runner_path or _default_runner_path()
            self._impl = _CondaSubprocessAlignn(
                self._checkpoints, env_name=env_name, runner_path=runner
            )
            version = f"{env_name}-subprocess"
        else:
            raise ValueError(
                f"unknown backend {backend!r}; use 'auto', 'in_process', "
                "or 'conda_subprocess'"
            )
        self._backend = chosen

        # Provenance tag — same shape as the in-process flavor; the
        # 'version' string identifies the backend so SQLite UNIQUE
        # treats subprocess and in-process as different runs.
        self.provenance = ModelProvenance(
            model_id="alignn",
            checkpoint=",".join(sorted(self._checkpoints.values())),
            dataset="JARVIS-DFT",
            version=version,
            units=self._units,
        )

    @property
    def backend(self) -> str:
        return self._backend

    def predict(self, cif: str) -> dict[str, float]:
        return self._impl.predict(cif)


def _default_runner_path() -> Path:
    """Locate ``scripts/alignn_runner.py`` relative to the package install.

    Uses the package's parent (..) since both ``crucible/`` and ``scripts/``
    are siblings under the repo root. This breaks if someone installs the
    package outside its repo (e.g. wheel into site-packages), in which
    case ``runner_path=`` should be passed explicitly.
    """
    here = Path(__file__).resolve()
    candidate = here.parent.parent.parent / "scripts" / "alignn_runner.py"
    return candidate
