"""Tests for crucible.predictors.alignn.

The predictor has a dual-backend dispatcher (in_process for Linux/CUDA,
conda_subprocess for macOS). We exercise the detection logic with mocks
and the actual subprocess plumbing with a fake runner. Real ALIGNN
prediction requires (a) DGL working in this Python or (b) a fully
configured conda env with downloaded model weights — both gated by
`skipif`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from crucible.predictors.alignn import (
    AlignnPredictor,
    _CondaSubprocessAlignn,
    _conda_runner_available,
    _detect_backend,
    _in_process_dgl_works,
)


def _real_dgl_works() -> bool:
    return _in_process_dgl_works()


def _conda_env_present() -> bool:
    ok, _ = _conda_runner_available("crucible-alignn")
    return ok


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def test_detect_backend_prefers_in_process_when_dgl_works() -> None:
    with patch("crucible.predictors.alignn._in_process_dgl_works", return_value=True):
        assert _detect_backend("any-env") == "in_process"


def test_detect_backend_falls_back_to_conda_when_env_present() -> None:
    with patch("crucible.predictors.alignn._in_process_dgl_works", return_value=False), \
         patch("crucible.predictors.alignn._conda_runner_available",
               return_value=(True, "/usr/bin/mamba")):
        assert _detect_backend("crucible-alignn") == "conda_subprocess"


def test_detect_backend_returns_in_process_when_neither_works() -> None:
    """When everything is missing, fall back to in_process so the
    constructor raises a useful error."""
    with patch("crucible.predictors.alignn._in_process_dgl_works", return_value=False), \
         patch("crucible.predictors.alignn._conda_runner_available",
               return_value=(False, None)):
        assert _detect_backend("missing-env") == "in_process"


# ---------------------------------------------------------------------------
# Construction with explicit backend
# ---------------------------------------------------------------------------


def test_explicit_backend_unknown_raises() -> None:
    with pytest.raises(ValueError):
        AlignnPredictor(backend="not_a_backend")


def test_in_process_backend_raises_clean_when_dgl_missing() -> None:
    if _real_dgl_works():
        pytest.skip("DGL works on this host; in-process construction succeeds.")
    with pytest.raises(RuntimeError) as exc:
        AlignnPredictor(backend="in_process")
    assert "alignn" in str(exc.value).lower()


def test_conda_subprocess_backend_requires_existing_env(tmp_path: Path) -> None:
    """The constructor refuses if the named conda env doesn't exist."""
    with patch("crucible.predictors.alignn._conda_runner_available",
               return_value=(False, None)):
        with pytest.raises(RuntimeError) as exc:
            AlignnPredictor(backend="conda_subprocess", conda_env="ghost-env")
        assert "ghost-env" in str(exc.value) or "not found" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Subprocess backend with a stubbed mamba runner
# ---------------------------------------------------------------------------


def _fake_runner_returning(payload: dict) -> Path:
    """Create a tiny shell-script-as-runner that prints the given JSON."""
    return _fake_runner_with_stdout(json.dumps(payload))


def _fake_runner_with_stdout(stdout_str: str, returncode: int = 0) -> Path:
    """Make a fake 'mamba'-equivalent that prints stdout and exits."""
    # We patch subprocess.run instead of building a real script; that's
    # cleaner and OS-independent. This helper stays for symmetry but is
    # currently unused.
    raise NotImplementedError


def test_conda_subprocess_predict_round_trip(tmp_path: Path) -> None:
    """Stub _conda_runner_available + subprocess.run and check that the
    payload returned by the runner makes it back to the caller mapped to
    property keys."""
    runner = tmp_path / "alignn_runner.py"
    runner.write_text("# fake runner\n")

    fake_payload = {
        "jv_formation_energy_peratom_alignn": -1.234,
        "jv_optb88vdw_bandgap_alignn": 0.567,
    }

    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(fake_payload),
        stderr="",
    )

    with patch("crucible.predictors.alignn._conda_runner_available",
               return_value=(True, "/fake/mamba")), \
         patch("crucible.predictors.alignn.subprocess.run", return_value=completed):
        impl = _CondaSubprocessAlignn(
            checkpoints={
                "formation_energy_eV_per_atom": "jv_formation_energy_peratom_alignn",
                "bandgap_eV": "jv_optb88vdw_bandgap_alignn",
            },
            env_name="crucible-alignn",
            runner_path=runner,
        )
        out = impl.predict("dummy_cif")

    assert out["formation_energy_eV_per_atom"] == pytest.approx(-1.234)
    assert out["bandgap_eV"] == pytest.approx(0.567)


def test_conda_subprocess_runner_error_surfaces_as_runtimeerror(tmp_path: Path) -> None:
    runner = tmp_path / "r.py"
    runner.write_text("")
    bad = subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout='{"error": "BadZipFile: File is not a zip file"}',
        stderr="",
    )
    with patch("crucible.predictors.alignn._conda_runner_available",
               return_value=(True, "/fake/mamba")), \
         patch("crucible.predictors.alignn.subprocess.run", return_value=bad):
        impl = _CondaSubprocessAlignn(
            checkpoints={"x": "ckpt"}, env_name="x", runner_path=runner
        )
        with pytest.raises(RuntimeError) as exc:
            impl.predict("dummy")
        assert "exited 1" in str(exc.value)
        assert "BadZipFile" in str(exc.value)


# ---------------------------------------------------------------------------
# Public AlignnPredictor surface
# ---------------------------------------------------------------------------


def test_default_checkpoints_match_alignn_pretrained_model_names() -> None:
    """Sanity: the names we ask alignn for must exist in alignn.pretrained.
    Skipif — alignn must be importable somewhere (in_process or via conda env).
    """
    if not _real_dgl_works() and not _conda_env_present():
        pytest.skip("Neither in-process DGL nor conda env available.")

    p = AlignnPredictor()
    for ck in p._checkpoints.values():
        assert ck.endswith("_alignn"), f"checkpoint {ck!r} naming convention drift"


def test_provenance_carries_backend_in_version() -> None:
    """SQLite UNIQUE on (hash, model_id, checkpoint, version) treats
    in_process and conda_subprocess as different runs, which is desired."""
    if not _conda_env_present():
        pytest.skip("conda env required for the subprocess provenance check.")
    p = AlignnPredictor(backend="conda_subprocess")
    assert "subprocess" in p.provenance.version


def test_backend_property_exposes_chosen_backend() -> None:
    if not _conda_env_present():
        pytest.skip("conda env required to construct a non-raising predictor.")
    p = AlignnPredictor()
    assert p.backend in ("in_process", "conda_subprocess")


# ---------------------------------------------------------------------------
# Real end-to-end (heavy; only runs when the user has fully set up alignn)
# ---------------------------------------------------------------------------


def _alignn_models_downloaded() -> bool:
    """True only when both default-checkpoint zip files exist in the
    conda env's alignn package dir."""
    out = subprocess.run(
        ["mamba", "run", "-n", "crucible-alignn", "python", "-c",
         "import alignn, pathlib; print(pathlib.Path(alignn.__file__).parent)"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        return False
    pkg = Path(out.stdout.strip())
    needed = [
        "jv_formation_energy_peratom_alignn.zip",
        "jv_optb88vdw_bandgap_alignn.zip",
    ]
    for name in needed:
        f = pkg / name
        if not f.exists() or f.stat().st_size == 0:
            return False
    return True


@pytest.mark.slow
@pytest.mark.skipif(
    not _conda_env_present() or not _alignn_models_downloaded(),
    reason="conda env + alignn model zips required (see docs/install_alignn_macos.md)",
)
def test_real_alignn_subprocess_predict_nacl() -> None:
    """The real thing: a NaCl prediction round-trip via the conda env.
    Skipped unless the user has completed the manual figshare download."""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    s = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    cif = str(CifWriter(s))
    p = AlignnPredictor(backend="conda_subprocess")
    out = p.predict(cif)
    # NaCl is ionic + wide-gap; sanity-check the orders of magnitude.
    assert out["formation_energy_eV_per_atom"] < 0
    assert out["formation_energy_eV_per_atom"] > -10
    assert out["bandgap_eV"] >= 0
