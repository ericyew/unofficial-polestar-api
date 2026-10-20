"""Icons that follow a binary sensor's state."""

from __future__ import annotations

import sys

from .test_unsupported_entities import FakeRegistry, _load


def _state_icon(monkeypatch):
    _load(monkeypatch, FakeRegistry())
    return sys.modules["_polestar_unsupported_under_test.utils"].state_icon


def test_icon_follows_the_state(monkeypatch):
    state_icon = _state_icon(monkeypatch)

    assert state_icon(True, "mdi:open", "mdi:closed", "mdi:default") == "mdi:open"
    assert state_icon(False, "mdi:open", "mdi:closed", "mdi:default") == "mdi:closed"


def test_unknown_state_shows_the_off_icon(monkeypatch):
    state_icon = _state_icon(monkeypatch)

    assert state_icon(None, "mdi:open", "mdi:closed", "mdi:default") == "mdi:closed"


def test_entities_without_state_icons_keep_their_normal_icon(monkeypatch):
    state_icon = _state_icon(monkeypatch)

    assert state_icon(True, None, None, "mdi:default") == "mdi:default"
    assert state_icon(False, None, None, None) is None
