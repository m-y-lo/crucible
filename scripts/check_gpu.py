"""Verify torch is installed and a CUDA (or Apple MPS) device is reachable.

Run this once after `uv sync --extra ml` to confirm the environment can
host ALIGNN, CrystaLLM, and friends. Reports device count, names, and
free VRAM (or unified memory on Apple Silicon).

Usage:
    python scripts/check_gpu.py
"""

from __future__ import annotations

import sys


def _bytes_to_gb(n: int) -> float:
    return n / (1024**3)


def main() -> int:
    try:
        import torch
    except ImportError:
        print("torch not installed. Run: uv sync --extra ml", file=sys.stderr)
        return 1

    print(f"torch version: {torch.__version__}")

    if torch.cuda.is_available():
        n = torch.cuda.device_count()
        print(f"CUDA available: {n} device(s)")
        for i in range(n):
            props = torch.cuda.get_device_properties(i)
            total = _bytes_to_gb(props.total_memory)
            print(f"  [{i}] {props.name} — {total:.1f} GB")
        return 0

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        print("Apple MPS available (no dedicated VRAM; uses unified memory).")
        print("Note: ALIGNN's DGL backend may not support MPS — verify before relying on it.")
        return 0

    print("No GPU backend reachable. CrystaLLM and ALIGNN will fall back to CPU (slow).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
