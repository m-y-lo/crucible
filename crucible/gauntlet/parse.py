"""Gauntlet stage 1 — parse a CIF string into a pymatgen.Structure.

The first filter every generated CIF passes through. CrystaLLM-style
generators emit a meaningful fraction of malformed output (truncated
text, garbled numerics, invented keywords); this stage rejects those
before any downstream stage tries to touch them.

This module is pure (no I/O, no network) and never raises on bad input —
the gauntlet pipeline must be able to log a rejection and keep going.
Exceptions are caught here and turned into a structured ``ParseResult``.

Cell convention: pymatgen returns whichever cell the CIF specified
(conventional or primitive). Canonicalization to primitive happens later
in ``crucible.core.hashing``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure

# Hard cap on CIF text size. Real CIFs from CrystaLLM are ~2-5 kB. Anything
# above 1 MB is a generator misbehavior or a deliberate DoS attempt; reject
# without invoking the parser.
_MAX_CIF_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of attempting to parse a CIF.

    On success: ``structure`` is set, ``reason`` is None.
    On failure: ``structure`` is None, ``reason`` is a short human-readable
    string suitable for the ``gauntlet_events.reason`` column.
    """

    structure: Structure | None
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.structure is not None


def _success(structure: Structure) -> ParseResult:
    return ParseResult(structure=structure, reason=None)


def _failure(reason: str) -> ParseResult:
    return ParseResult(structure=None, reason=reason)


def try_parse(cif: str) -> ParseResult:
    """Attempt to parse ``cif`` into a pymatgen.Structure. Never raises.

    Rejection reasons (each surfaces as a distinct ``reason`` string):

    - empty / whitespace-only input
    - input exceeds the size cap
    - pymatgen parse error (truncation, invented syntax, bad numerics)
    - parses to a structure with zero atomic sites
    """
    if not cif or not cif.strip():
        return _failure("empty CIF")

    if len(cif.encode("utf-8")) > _MAX_CIF_BYTES:
        return _failure(f"CIF too large (>{_MAX_CIF_BYTES} bytes)")

    try:
        structure = Structure.from_str(cif, fmt="cif")
    # pymatgen raises a range of exceptions (ValueError, KeyError, etc.)
    # for malformed CIFs. Anything that isn't a SystemExit / KeyboardInterrupt
    # is a parse failure as far as the gauntlet is concerned.
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
        return _failure(f"parse error: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001 - intentional broad catch
        return _failure(f"unexpected parse error: {type(e).__name__}: {e}")

    if len(structure) == 0:
        return _failure("empty structure (no atomic sites)")

    return _success(structure)
