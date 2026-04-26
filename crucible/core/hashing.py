"""Canonical hash and prototype label for a crystal structure.

Two outputs:

- ``structure_hash`` — sha256 of a canonical, deterministic serialization of
  the primitive cell. Same crystal -> same hash, regardless of how the CIF
  was originally written (cell choice, atom ordering, lattice orientation,
  small floating-point noise).
- ``prototype_label`` — AFLOW-style structural fingerprint
  ``"<stoich>_<pearson>_<sg>_<wyckoff>"``. Coarse pre-filter for dedup:
  same prototype = same structural pattern (different elements possible).

These functions take CIF text and are pure (no I/O, no network). Cell
convention is primitive throughout — see ARCHITECTURE.md sections 3, 4, 10.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from string import ascii_uppercase

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

# Symmetry tolerance for SpacegroupAnalyzer. 1e-3 A is a common pymatgen
# default for noisy generator output; tighter than that and CrystaLLM
# output starts mis-classifying its own space groups.
_SYMPREC = 1e-3

# Decimals to round to before hashing. Six is enough to distinguish real
# structural differences while absorbing FP noise from primitive-cell
# transforms.
_HASH_PRECISION = 6


def _canonical_payload(structure: Structure, sg_number: int) -> dict:
    """Build the deterministic dict whose JSON form is what we sha256."""
    lat = structure.lattice
    sites = [
        (
            site.specie.symbol,
            round(float(site.frac_coords[0]) % 1.0, _HASH_PRECISION),
            round(float(site.frac_coords[1]) % 1.0, _HASH_PRECISION),
            round(float(site.frac_coords[2]) % 1.0, _HASH_PRECISION),
        )
        for site in structure
    ]
    sites.sort()
    return {
        "space_group": sg_number,
        "lattice": [
            round(lat.a, _HASH_PRECISION),
            round(lat.b, _HASH_PRECISION),
            round(lat.c, _HASH_PRECISION),
            round(lat.alpha, _HASH_PRECISION),
            round(lat.beta, _HASH_PRECISION),
            round(lat.gamma, _HASH_PRECISION),
        ],
        "sites": sites,
    }


def hash_structure(structure: Structure) -> str:
    """Return a sha256 hex digest uniquely identifying ``structure``.

    Reduces to the primitive standard cell, then hashes a deterministic
    tuple of (space group, rounded lattice parameters, sorted (element,
    rounded fractional coords)). The same crystal in any representation
    produces the same digest.

    Use this directly when you already have a parsed ``Structure`` (e.g.
    inside the gauntlet pipeline). Use :func:`structure_hash` when you
    only have CIF text.
    """
    sga = SpacegroupAnalyzer(structure, symprec=_SYMPREC)
    primitive = sga.get_primitive_standard_structure()
    sg_number = sga.get_space_group_number()
    payload = _canonical_payload(primitive, sg_number)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def structure_hash(cif: str) -> str:
    """CIF-text wrapper around :func:`hash_structure`. See that function
    for the canonicalization details."""
    return hash_structure(Structure.from_str(cif, fmt="cif"))


def _stoichiometry_label(structure: Structure) -> str:
    """Anonymized stoichiometry: counts only, elements replaced by A, B, C....

    "NaCl" -> "AB", "Li2MnO3" -> "A2BC3", "Fe2O3" -> "A2B3". Counts are
    sorted descending, then ascending element symbol as tiebreaker, so the
    output depends only on the *shape* of the composition.
    """
    counts = Counter(site.specie.symbol for site in structure)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    for letter, (_, count) in zip(ascii_uppercase, ordered, strict=False):
        parts.append(letter if count == 1 else f"{letter}{count}")
    return "".join(parts)


def prototype_label_of(structure: Structure) -> str:
    """Return an AFLOW-style prototype label for ``structure``.

    Format: ``"<stoich>_<pearson>_<sg_num>_<wyckoff>"`` where ``<stoich>`` is
    anonymized (NaCl -> AB), ``<pearson>`` is the Pearson symbol (cF8),
    ``<sg_num>`` is the international space group number, and ``<wyckoff>``
    is the sorted concatenation of Wyckoff letters of the inequivalent
    sites. Two structures with the same prototype share the same skeletal
    arrangement (element identities may differ).

    Example: NaCl rocksalt -> ``"AB_cF8_225_ab"``.

    Use this when you already have a parsed ``Structure``; use
    :func:`prototype_label` when you only have CIF text.
    """
    sga = SpacegroupAnalyzer(structure, symprec=_SYMPREC)
    primitive = sga.get_primitive_standard_structure()

    stoich = _stoichiometry_label(primitive)
    pearson = sga.get_pearson_symbol()
    sg_num = sga.get_space_group_number()

    # Wyckoff letters of the inequivalent sites (e.g. ['4a', '4b'] -> 'ab').
    sym_struct = sga.get_symmetrized_structure()
    wyckoff_letters = "".join(
        sorted(symbol.lstrip("0123456789") for symbol in sym_struct.wyckoff_symbols)
    )

    return f"{stoich}_{pearson}_{sg_num}_{wyckoff_letters}"


def prototype_label(cif: str) -> str:
    """CIF-text wrapper around :func:`prototype_label_of`. See that function
    for the format details."""
    return prototype_label_of(Structure.from_str(cif, fmt="cif"))
