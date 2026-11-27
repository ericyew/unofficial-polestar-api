"""Steering wheel heat options follow the number of levels the car reports."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE = "_polestar_steering_under_test"


class FakeEntity:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self._vehicle = coordinator.vehicle

    @property
    def options(self):
        return getattr(self, "_attr_options", self.entity_description.options)


def _stub(monkeypatch, name: str, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_select(monkeypatch):
    @dataclass(frozen=True, kw_only=True)
    class SelectEntityDescription:
        key: str = ""
        name: str = ""
        icon: str | None = None
        entity_category: str | None = None
        options: list[str] | None = None

    _stub(monkeypatch, "homeassistant")
    _stub(monkeypatch, "homeassistant.components")
    _stub(
        monkeypatch,
        "homeassistant.components.select",
        SelectEntity=object,
        SelectEntityDescription=SelectEntityDescription,
    )
    _stub(monkeypatch, "homeassistant.config_entries", ConfigEntry=object)
    _stub(monkeypatch, "homeassistant.core", HomeAssistant=object)
    _stub(monkeypatch, "homeassistant.helpers")
    _stub(monkeypatch, "homeassistant.helpers.entity", EntityCategory=SimpleNamespace(CONFIG="config"))
    _stub(monkeypatch, "homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _stub(monkeypatch, "homeassistant.helpers.restore_state", RestoreEntity=type("RestoreEntity", (), {}))
    _stub(monkeypatch, "homeassistant.util", dt=SimpleNamespace())

    component = Path(__file__).parents[1] / "custom_components" / "polestar"
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(component)]
    monkeypatch.setitem(sys.modules, PACKAGE, package)
    _stub(monkeypatch, f"{PACKAGE}.const", DOMAIN="polestar")
    _stub(monkeypatch, f"{PACKAGE}.coordinator", PolestarCoordinator=object)
    _stub(
        monkeypatch,
        f"{PACKAGE}.entity",
        OptimisticStateMixin=type("OptimisticStateMixin", (), {}),
        PolestarEntity=FakeEntity,
        async_filter_supported_entities=None,
    )

    for name in ("utils", "select"):
        spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", component / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, f"{PACKAGE}.{name}", module)
        spec.loader.exec_module(module)
    return module


def _select(module, key: str, levels: int | None):
    vehicle = SimpleNamespace(vin="TESTVIN123", model_name="Polestar 4", steering_wheel_heat_levels=levels)
    description = next(item for item in module.SELECTS if item.key == key)
    return module.PolestarSelect(SimpleNamespace(vehicle=vehicle), description)


def test_one_level_offers_only_off_and_level3(monkeypatch):
    module = _load_select(monkeypatch)

    assert _select(module, "climate_steering_wheel", 1).options == ["unspecified", "off", "level3"]


@pytest.mark.parametrize("levels", [None, 3])
def test_other_cars_keep_every_level(monkeypatch, levels):
    module = _load_select(monkeypatch)

    assert "level1" in _select(module, "climate_steering_wheel", levels).options


def test_seat_selects_are_not_limited(monkeypatch):
    module = _load_select(monkeypatch)

    assert "level1" in _select(module, "climate_front_left_seat", 1).options
