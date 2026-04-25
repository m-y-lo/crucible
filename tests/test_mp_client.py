"""Tests for crucible.data.mp_client.

Goals:
- Cache hits skip the network entirely (`_open_rester` is never called).
- Cache misses call MP exactly once and re-serve from cache thereafter.
- Cache survives across `MPClient` instances pointing at the same file.
- Missing MP_API_KEY surfaces a clean error.

The MP API is stubbed out by replacing `MPClient._open_rester` with a fake
context manager. No network, no real API key needed for these tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pymatgen.core import Lattice, Structure

from crucible.data.mp_client import MPClient


# --------------------------------------------------------------------------
# Test fixtures
# --------------------------------------------------------------------------


def _nacl() -> Structure:
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def _kcl() -> Structure:
    return Structure(
        Lattice.cubic(6.29),
        ["K", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


class FakeRester:
    """Stub MPRester. Counts calls so we can assert the cache works."""

    def __init__(self, results_by_formula: dict[str, list[Structure]]) -> None:
        self.results_by_formula = results_by_formula
        self.call_count = 0

    def __enter__(self) -> "FakeRester":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    @property
    def materials(self) -> "FakeRester":
        return self

    @property
    def summary(self) -> "FakeRester":
        return self

    def search(self, **kwargs: Any) -> list[MagicMock]:
        self.call_count += 1
        if "formula" in kwargs:
            structures = self.results_by_formula.get(kwargs["formula"], [])
        elif "material_ids" in kwargs:
            mp_id = kwargs["material_ids"][0]
            structures = self.results_by_formula.get(mp_id, [])
        else:
            structures = []
        return [MagicMock(material_id=f"mp-{i}", structure=s) for i, s in enumerate(structures)]


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.sqlite"


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_constructor_rejects_empty_key(cache_path: Path) -> None:
    with pytest.raises(ValueError):
        MPClient(api_key="", cache_path=cache_path)


def test_from_env_requires_key(monkeypatch: pytest.MonkeyPatch, cache_path: Path) -> None:
    monkeypatch.delenv("MP_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        MPClient.from_env(cache_path=cache_path)


def test_from_env_uses_env_var(monkeypatch: pytest.MonkeyPatch, cache_path: Path) -> None:
    monkeypatch.setenv("MP_API_KEY", "test-key-xyz")
    client = MPClient.from_env(cache_path=cache_path)
    assert client._api_key == "test-key-xyz"


# --------------------------------------------------------------------------
# get_structures_by_formula — caching behavior
# --------------------------------------------------------------------------


def test_get_structures_by_formula_calls_mp_once_then_caches(cache_path: Path) -> None:
    fake = FakeRester({"NaCl": [_nacl()]})
    with patch.object(MPClient, "_open_rester", return_value=fake):
        client = MPClient(api_key="x", cache_path=cache_path)

        first = client.get_structures_by_formula("NaCl")
        second = client.get_structures_by_formula("NaCl")

    assert fake.call_count == 1, "second call must be served from cache"
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].composition.reduced_formula == "NaCl"
    assert second[0].composition.reduced_formula == "NaCl"


def test_distinct_formulas_dont_share_cache(cache_path: Path) -> None:
    fake = FakeRester({"NaCl": [_nacl()], "KCl": [_kcl()]})
    with patch.object(MPClient, "_open_rester", return_value=fake):
        client = MPClient(api_key="x", cache_path=cache_path)
        nacl = client.get_structures_by_formula("NaCl")
        kcl = client.get_structures_by_formula("KCl")
    assert fake.call_count == 2
    assert nacl[0].composition.reduced_formula == "NaCl"
    assert kcl[0].composition.reduced_formula == "KCl"


def test_empty_results_are_also_cached(cache_path: Path) -> None:
    fake = FakeRester({})  # nothing matches
    with patch.object(MPClient, "_open_rester", return_value=fake):
        client = MPClient(api_key="x", cache_path=cache_path)
        first = client.get_structures_by_formula("Xx2Yy3")
        second = client.get_structures_by_formula("Xx2Yy3")
    assert first == [] and second == []
    assert fake.call_count == 1, "negative result must be cached too"


def test_cache_survives_new_client_instance(cache_path: Path) -> None:
    fake_a = FakeRester({"NaCl": [_nacl()]})
    with patch.object(MPClient, "_open_rester", return_value=fake_a):
        client_a = MPClient(api_key="x", cache_path=cache_path)
        client_a.get_structures_by_formula("NaCl")
    assert fake_a.call_count == 1

    # Brand new client, same cache file. Should not hit MP.
    fake_b = FakeRester({"NaCl": [_nacl()]})
    with patch.object(MPClient, "_open_rester", return_value=fake_b):
        client_b = MPClient(api_key="x", cache_path=cache_path)
        result = client_b.get_structures_by_formula("NaCl")
    assert fake_b.call_count == 0, "second client must read from disk"
    assert len(result) == 1


# --------------------------------------------------------------------------
# get_structure_by_mp_id
# --------------------------------------------------------------------------


def test_get_structure_by_mp_id_hit(cache_path: Path) -> None:
    fake = FakeRester({"mp-22862": [_nacl()]})
    with patch.object(MPClient, "_open_rester", return_value=fake):
        client = MPClient(api_key="x", cache_path=cache_path)
        s = client.get_structure_by_mp_id("mp-22862")
    assert s is not None
    assert s.composition.reduced_formula == "NaCl"


def test_get_structure_by_mp_id_miss(cache_path: Path) -> None:
    fake = FakeRester({})
    with patch.object(MPClient, "_open_rester", return_value=fake):
        client = MPClient(api_key="x", cache_path=cache_path)
        s = client.get_structure_by_mp_id("mp-does-not-exist")
        again = client.get_structure_by_mp_id("mp-does-not-exist")
    assert s is None and again is None
    assert fake.call_count == 1, "miss must also be cached"
