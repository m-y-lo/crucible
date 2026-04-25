"""Tests for `crucible.core.registry` — entry-point loader."""

from __future__ import annotations

import pytest

from crucible.core.protocols import Ranker
from crucible.core.registry import GROUPS, list_plugins, load


class _FakeRanker:
    """Minimal class that satisfies the Ranker Protocol."""

    name = "fake_ranker"
    target = "demo"

    def criteria(self, props: dict[str, float]) -> bool:
        return True

    def score(self, props: dict[str, float]) -> float:
        return 1.0


class _FakeEntryPoint:
    """Stand-in for `importlib.metadata.EntryPoint`. Only `.name` and `.load()` are needed."""

    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


def _patch_eps(monkeypatch, mapping: dict[str, dict[str, _FakeEntryPoint]]) -> None:
    """Replace registry._eps so it returns `mapping[kind]` for known kinds."""

    def fake_eps(kind: str) -> dict[str, _FakeEntryPoint]:
        if kind not in GROUPS:
            raise KeyError(f"Unknown plugin kind {kind!r}; have {sorted(GROUPS)}")
        return mapping.get(kind, {})

    monkeypatch.setattr("crucible.core.registry._eps", fake_eps)


def test_list_plugins_returns_sorted(monkeypatch) -> None:
    """list_plugins returns plugin names in sorted order regardless of registration order."""
    _patch_eps(monkeypatch, {
        "ranker": {
            "z_late": _FakeEntryPoint("z_late", _FakeRanker),
            "a_early": _FakeEntryPoint("a_early", _FakeRanker),
            "m_middle": _FakeEntryPoint("m_middle", _FakeRanker),
        },
    })
    assert list_plugins("ranker") == ["a_early", "m_middle", "z_late"]


def test_list_plugins_empty_when_no_plugins_registered(monkeypatch) -> None:
    """A plugin kind with no entries returns an empty list, not an error."""
    _patch_eps(monkeypatch, {})
    assert list_plugins("predictor") == []


def test_list_plugins_unknown_kind_raises_keyerror() -> None:
    """Querying an unknown plugin kind is a KeyError mentioning the bad kind."""
    with pytest.raises(KeyError) as exc_info:
        list_plugins("not_a_kind")
    assert "not_a_kind" in str(exc_info.value)


def test_load_returns_instance_satisfying_protocol(monkeypatch) -> None:
    """load returns a plugin instance and it satisfies the relevant Protocol."""
    _patch_eps(monkeypatch, {
        "ranker": {"fake_ranker": _FakeEntryPoint("fake_ranker", _FakeRanker)},
    })
    obj = load("ranker", "fake_ranker")
    assert isinstance(obj, _FakeRanker)
    assert isinstance(obj, Ranker)
    assert obj.name == "fake_ranker"
    assert obj.criteria({}) is True
    assert obj.score({}) == 1.0


def test_load_passes_kwargs_to_constructor(monkeypatch) -> None:
    """load(kind, name, **kwargs) forwards kwargs to the plugin's __init__."""
    captured: dict = {}

    class _PluginWithInit:
        name = "with_init"
        target = "demo"

        def __init__(self, **opts) -> None:
            captured.update(opts)

        def criteria(self, props: dict) -> bool:
            return True

        def score(self, props: dict) -> float:
            return 1.0

    _patch_eps(monkeypatch, {
        "ranker": {"with_init": _FakeEntryPoint("with_init", _PluginWithInit)},
    })
    load("ranker", "with_init", threshold=0.5, mode="strict")
    assert captured == {"threshold": 0.5, "mode": "strict"}


def test_load_unknown_name_raises_keyerror_with_available_names(monkeypatch) -> None:
    """A typo'd plugin name should KeyError, with the list of valid names in the message."""
    _patch_eps(monkeypatch, {
        "ranker": {"fake_ranker": _FakeEntryPoint("fake_ranker", _FakeRanker)},
    })
    with pytest.raises(KeyError) as exc_info:
        load("ranker", "fke_rnker")
    msg = str(exc_info.value)
    assert "fke_rnker" in msg
    assert "fake_ranker" in msg


def test_load_unknown_kind_raises_keyerror() -> None:
    """load() with an unknown kind also surfaces KeyError, not a confusing AttributeError."""
    with pytest.raises(KeyError):
        load("not_a_kind", "anything")
