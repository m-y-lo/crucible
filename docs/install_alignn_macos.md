# Installing ALIGNN on macOS Apple Silicon

ALIGNN is the property predictor we use for formation energy + bandgap. On
Linux/CUDA, `uv sync --extra ml` is enough — `crucible.predictors.alignn`'s
default `backend="auto"` detects the working in-process import and uses it.

On macOS Apple Silicon, the underlying DGL native libs (graphbolt, metis,
GKlib) are missing or ABI-mismatched on PyPI. Conda-forge has working
DGL builds but the dependency chain is fragile. This doc walks the
**conda env + subprocess backend** path that does work on a Mac.

## One-time setup (~10 minutes)

### 1. Install miniforge

```bash
brew install --cask miniforge
```

Verify:

```bash
which mamba   # /opt/homebrew/bin/mamba
mamba --version
```

### 2. Create the alignn env

We pin every native lib version so the DGL graphbolt dylib resolves.

```bash
mamba create -n crucible-alignn python=3.11 \
  pytorch=2.1.2 dgl=2.0.0 torchdata=0.7.1 \
  -c conda-forge -y

mamba run -n crucible-alignn pip install \
  "alignn==2024.12.12" pymatgen ase jarvis-tools pyyaml
```

### 3. Patch the DGL dylib version mismatch

Conda-forge's DGL 2.0.0 was built against `torch 2.1.2.post2` but
ships with the metadata-bumped `torch 2.1.2.post4`. Add symlinks so
DGL's loader finds its libs:

```bash
DGL_DIR=/opt/homebrew/Caskroom/miniforge/base/envs/crucible-alignn/lib/python3.11/site-packages/dgl
for sub in graphbolt dgl_sparse tensoradapter/pytorch; do
  cd "$DGL_DIR/$sub"
  for lib in lib*_pytorch_2.1.2.post2.dylib; do
    [ -f "$lib" ] && ln -sf "$lib" "${lib/post2/post4}"
  done
  cd - > /dev/null
done
```

### 4. Verify DGL imports

```bash
mamba run -n crucible-alignn python -c \
  "from dgl import graphbolt; print('graphbolt OK')"
```

Expected output: `graphbolt OK`.

### 5. Download the ALIGNN model weights (manual step)

ALIGNN downloads pretrained checkpoints from figshare on first use,
but figshare's WAF blocks automated downloads (curl/python requests).
You need to fetch them once via a real browser:

| Property | URL |
|---|---|
| Formation energy | https://figshare.com/ndownloader/files/31458679 |
| Bandgap (OptB88vdW) | https://figshare.com/ndownloader/files/31458694 |

For each URL: paste it in your browser, complete any "verify you are
human" challenge, and save the resulting `.zip` file.

Place the files at:

```
/opt/homebrew/Caskroom/miniforge/base/envs/crucible-alignn/lib/python3.11/site-packages/alignn/jv_formation_energy_peratom_alignn.zip
/opt/homebrew/Caskroom/miniforge/base/envs/crucible-alignn/lib/python3.11/site-packages/alignn/jv_optb88vdw_bandgap_alignn.zip
```

(The filename must match the model name exactly — alignn looks them up by
`<model_name>.zip` next to its package source.)

### 6. Verify ALIGNN predicts

```bash
mamba run -n crucible-alignn python -c "
from alignn.pretrained import get_prediction
from pymatgen.core import Lattice, Structure
nacl = Structure(Lattice.cubic(5.64), ['Na','Cl'], [[0,0,0],[0.5,0.5,0.5]])
v = get_prediction(model_name='jv_formation_energy_peratom_alignn',
                   atoms=nacl.to_ase_atoms())
print('NaCl formation energy:', float(v) if hasattr(v,'__float__') else float(v[0]),
      'eV/atom')
"
```

Expected: `NaCl formation energy: -2.0xx eV/atom` (close to MP's
literature value of −2.13 eV/atom for rocksalt NaCl).

## Using ALIGNN from Crucible

Once the env is set up, no further config needed. `AlignnPredictor()`
(or `registry.load("predictor", "alignn")`) auto-detects the conda env
and routes through `mamba run -n crucible-alignn python
scripts/alignn_runner.py`.

```python
from crucible.predictors.alignn import AlignnPredictor

p = AlignnPredictor()
print(p.backend)            # "conda_subprocess" on macOS
print(p.predict(cif_text))  # {"formation_energy_eV_per_atom": -2.04,
                            #  "bandgap_eV": 0.74}
```

To force a specific backend (e.g. CI on Linux):

```python
AlignnPredictor(backend="in_process")     # Linux/CUDA path
AlignnPredictor(backend="conda_subprocess")  # macOS via mamba run
```

## Performance

Subprocess overhead is ~1–2 seconds per call (mamba env activation +
torch/alignn imports). For batch use, write your own loop that calls
`scripts/alignn_runner.py` directly with multiple checkpoints in one
invocation. The orchestrator's `predict` tool is one CIF per call
today; Phase 2 may batch.
