"""Standalone ALIGNN prediction runner.

Designed to be invoked from the main Crucible (uv) venv via subprocess
into a separate conda env that has DGL+ALIGNN working natively. On
macOS Apple Silicon this is the only realistic way to use ALIGNN; on
Linux/CUDA the in-process import path works fine and this script is
unused.

Protocol (kept deliberately simple so the parent process can shell out
without any shared state beyond the filesystem):

  Input  : argv[1] is the path to a CIF file. argv[2..] are checkpoint
           names from ``alignn.pretrained.all_models``.
  Output : a single JSON object printed to stdout, like
           ``{"jv_formation_energy_peratom_alignn": -1.234,
              "jv_optb88vdw_bandgap_alignn": 0.987}``
  Errors : non-zero exit + JSON ``{"error": "..."}``.

This script imports nothing from ``crucible``. It is meant to run inside
``mamba run -n crucible-alignn python scripts/alignn_runner.py ...``
where only alignn / pymatgen / ase / dgl are available.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _predict_one(checkpoint: str, atoms) -> float:
    from alignn.pretrained import get_prediction

    val = get_prediction(model_name=checkpoint, atoms=atoms)
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(val[0])


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            json.dumps(
                {"error": "usage: alignn_runner.py <cif_path> <checkpoint> [...]"}
            ),
            file=sys.stdout,
        )
        return 2

    cif_path = Path(argv[1])
    checkpoints = argv[2:]
    try:
        from pymatgen.core import Structure

        structure = Structure.from_str(cif_path.read_text(), fmt="cif")
        atoms = structure.to_ase_atoms()
        out: dict[str, float] = {}
        for ck in checkpoints:
            out[ck] = _predict_one(ck, atoms)
    except Exception as e:  # noqa: BLE001 - report any failure as JSON
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}), file=sys.stdout)
        return 1

    print(json.dumps(out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
