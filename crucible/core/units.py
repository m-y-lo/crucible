"""Single source of truth for unit constants and converters.

Materials properties travel as floats; this module pins their meaning.
Conventions: formation energy in eV/atom, bandgaps in eV, bulk/shear moduli
in GPa, lattice parameters in A. See playbook section 3.B.

Why this file matters:
ALIGNN checkpoints return values in different units depending on the
checkpoint (per-atom vs total, eV vs meV). The codebase-wide rule is that
unit strings live inside dict keys, e.g. {"formation_energy_eV_per_atom": -1.7}.
This module is the canonical source for those key strings and the small
set of converters we actually need.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Unit string constants
# These are the canonical suffixes and identifiers that go inside dict keys
# (Prediction.values, ModelProvenance.units) throughout the codebase.
# ---------------------------------------------------------------------------

EV = "eV"
EV_PER_ATOM = "eV/atom"
MEV_PER_ATOM = "meV/atom"
GPA = "GPa"
ANGSTROM = "Angstrom"
KJ_PER_MOL = "kJ/mol"


# ---------------------------------------------------------------------------
# Canonical property keys
# Helpers that build the exact strings used as keys in Prediction.values.
# Use these instead of typing the strings inline so a typo cannot drift.
# ---------------------------------------------------------------------------

FORMATION_ENERGY_KEY = "formation_energy_eV_per_atom"
BANDGAP_KEY = "bandgap_eV"
BULK_MODULUS_KEY = "bulk_modulus_GPa"
SHEAR_MODULUS_KEY = "shear_modulus_GPa"
TOTAL_ENERGY_KEY = "total_energy_eV"


# ---------------------------------------------------------------------------
# Converters
# Only the conversions actually used downstream. eV <-> kJ/mol is the
# textbook factor; the per-atom <-> total conversions are the ones that
# actually trip people up between checkpoints.
# ---------------------------------------------------------------------------

# 1 eV = 96.48533212... kJ/mol (CODATA 2018, eV * Avogadro / 1000)
_EV_TO_KJ_PER_MOL = 96.48533212331

# 1 eV = 1000 meV
_EV_TO_MEV = 1000.0


def ev_to_kj_per_mol(ev: float) -> float:
    """Convert an energy in eV to kJ/mol."""
    return ev * _EV_TO_KJ_PER_MOL


def kj_per_mol_to_ev(kj_per_mol: float) -> float:
    """Convert an energy in kJ/mol to eV."""
    return kj_per_mol / _EV_TO_KJ_PER_MOL


def ev_to_mev(ev: float) -> float:
    """Convert eV to meV."""
    return ev * _EV_TO_MEV


def mev_to_ev(mev: float) -> float:
    """Convert meV to eV."""
    return mev / _EV_TO_MEV


def per_atom_to_total(value_per_atom: float, num_atoms: int) -> float:
    """Convert a per-atom quantity (e.g. eV/atom) to a total (e.g. eV).

    `num_atoms` must be the count in the same cell the value was computed
    over. Mixing primitive vs conventional cell counts here is a classic
    bug; the caller is responsible for passing the matching count.
    """
    if num_atoms <= 0:
        raise ValueError(f"num_atoms must be positive, got {num_atoms}")
    return value_per_atom * num_atoms


def total_to_per_atom(value_total: float, num_atoms: int) -> float:
    """Convert a total quantity (e.g. eV) to per-atom (e.g. eV/atom)."""
    if num_atoms <= 0:
        raise ValueError(f"num_atoms must be positive, got {num_atoms}")
    return value_total / num_atoms
