"""Tests for auto-disabling entities whose data the car does not support."""

from __future__ import annotations

import enum
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from grpclib.const import Status
from grpclib.exceptions import GRPCError

from polestar_api.exceptions import is_unsupported_feature_error


def _stub(monkeypatch, name: str, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class RegistryEntryDisabler(enum.StrEnum):
    INTEGRATION = "integration"
    USER = "user"


class FakeRegistry:
    def __init__(self, entries: dict[str, SimpleNamespace] | None = None) -> None:
        self.entries = entries or {}
        self.updates: list[tuple[str, object]] = []
        self.removed: list[str] = []

    def async_get_entity_id(self, domain, platform, unique_id):
        for entity_id, entry in self.entries.items():
            if entity_id.startswith(f"{domain}.") and entry.unique_id == unique_id:
                return entity_id
        return None

    def async_get(self, entity_id):
        return self.entries.get(entity_id)

    def async_remove(self, entity_id):
        self.removed.append(entity_id)
        del self.entries[entity_id]

    def async_update_entity(self, entity_id, *, disabled_by):
        self.updates.append((entity_id, disabled_by))
        self.entries[entity_id].disabled_by = disabled_by


class FakeDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval, config_entry, always_update) -> None:
        self.hass = hass
        self.data = None


class FakeCoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.writes = 0

    def async_write_ha_state(self) -> None:
        self.writes += 1

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        return None


def _load(monkeypatch, registry: FakeRegistry):
    class ConfigEntryAuthFailed(Exception):
        pass

    class HomeAssistantError(Exception):
        pass

    class UpdateFailed(Exception):
        pass

    entity_registry = _stub(
        monkeypatch,
        "homeassistant.helpers.entity_registry",
        RegistryEntryDisabler=RegistryEntryDisabler,
        async_get=lambda hass: registry,
    )
    _stub(monkeypatch, "homeassistant")
    _stub(monkeypatch, "homeassistant.helpers", entity_registry=entity_registry)
    _stub(monkeypatch, "homeassistant.core", HomeAssistant=object, callback=lambda func: func)
    _stub(
        monkeypatch,
        "homeassistant.exceptions",
        ConfigEntryAuthFailed=ConfigEntryAuthFailed,
        HomeAssistantError=HomeAssistantError,
    )
    _stub(monkeypatch, "homeassistant.helpers.device_registry", DeviceInfo=dict)
    _stub(
        monkeypatch,
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=FakeDataUpdateCoordinator,
        UpdateFailed=UpdateFailed,
        CoordinatorEntity=FakeCoordinatorEntity,
    )
    notification_module = _stub(
        monkeypatch, "homeassistant.components.persistent_notification", async_create=lambda *args, **kwargs: None
    )
    _stub(monkeypatch, "homeassistant.components", persistent_notification=notification_module)
    _stub(monkeypatch, "homeassistant.helpers.event", async_call_later=lambda hass, delay, action: (lambda: None))
    dt_module = _stub(monkeypatch, "homeassistant.util.dt")
    _stub(monkeypatch, "homeassistant.util", dt=dt_module)

    package_name = "_polestar_unsupported_under_test"
    component_dir = Path(__file__).parents[1] / "custom_components" / "polestar"
    package = types.ModuleType(package_name)
    package.__path__ = [str(component_dir)]
    monkeypatch.setitem(sys.modules, package_name, package)

    def load(name: str):
        spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", component_dir / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, f"{package_name}.{name}", module)
        spec.loader.exec_module(module)
        return module

    load("const")
    load("utils")
    coordinator_module = load("coordinator")
    entity_module = load("entity")
    return coordinator_module, entity_module


def _unsupported(feature: str) -> GRPCError:
    return GRPCError(Status.UNIMPLEMENTED, f"Functionality not supported: {feature}")


def test_classifies_unsupported_feature_error():
    assert is_unsupported_feature_error(_unsupported("AMP_LIMIT"))
    assert is_unsupported_feature_error(
        GRPCError(Status.UNIMPLEMENTED, "Method not found: services.vehiclestates.dashboard.DashboardService/GetLatestDashboard")
    )
    assert not is_unsupported_feature_error(GRPCError(Status.UNIMPLEMENTED, "Something else"))
    assert not is_unsupported_feature_error(GRPCError(Status.INVALID_ARGUMENT, "Validation failed"))
    assert not is_unsupported_feature_error(TimeoutError())


class FakeVehicle:
    vin = "TESTVIN"

    def __init__(self, errors: dict[str, Exception]) -> None:
        self.errors = errors
        self.calls: list[str] = []

    async def get_amp_limit(self):
        self.calls.append("amp_limit")
        if "amp_limit" in self.errors:
            raise self.errors["amp_limit"]
        return "amp"

    async def get_climate_timer_settings(self):
        self.calls.append("climate_timer_settings")
        if "climate_timer_settings" in self.errors:
            raise self.errors["climate_timer_settings"]
        return "timer"

    async def get_battery(self):
        self.calls.append("battery")
        return "battery"


def _coordinator(module, vehicle):
    coordinator = module.PolestarCoordinator.__new__(module.PolestarCoordinator)
    coordinator.vehicle = vehicle
    coordinator._unsupported_fetches = set()
    coordinator._empty_fetches = set()
    coordinator._no_data_fetches = set()
    coordinator._merge_partial_update = lambda attr, previous, result: result
    return coordinator


@pytest.mark.asyncio
async def test_unsupported_fetch_is_recorded_and_not_polled_again(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    vehicle = FakeVehicle(
        {
            "amp_limit": _unsupported("AMP_LIMIT"),
            "climate_timer_settings": _unsupported("CLIMATE_TIMER_SETTING"),
        }
    )
    coordinator = _coordinator(coordinator_module, vehicle)
    previous = coordinator_module.PolestarVehicleData()
    attrs = ("amp_limit", "climate_timer_settings", "battery")

    values, successful = await coordinator._async_fetch_values(attrs, previous)

    assert successful == 1
    assert values["battery"] == "battery"
    assert not coordinator.is_fetch_supported("amp_limit")
    assert not coordinator.is_fetch_supported("climate_timer_settings")
    assert coordinator.is_fetch_supported("battery")

    vehicle.calls.clear()
    values, successful = await coordinator._async_fetch_values(attrs, previous)

    assert vehicle.calls == ["battery"]
    assert values["amp_limit"] is None
    assert values["climate_timer_settings"] is None


@pytest.mark.asyncio
async def test_other_errors_do_not_mark_fetch_unsupported(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    vehicle = FakeVehicle({"amp_limit": GRPCError(Status.INVALID_ARGUMENT, "Validation failed")})
    coordinator = _coordinator(coordinator_module, vehicle)

    await coordinator._async_fetch_values(("amp_limit", "battery"), coordinator_module.PolestarVehicleData())

    assert coordinator.is_fetch_supported("amp_limit")


class FakeEntity:
    def __init__(self, unique_id: str, required_fetch: str | None) -> None:
        self.unique_id = unique_id
        self.required_fetch = required_fetch


def _entry(unique_id: str, disabled_by=None) -> SimpleNamespace:
    return SimpleNamespace(unique_id=unique_id, disabled_by=disabled_by)


def test_unsupported_entities_are_dropped_and_disabled(monkeypatch):
    registry = FakeRegistry({"number.amp": _entry("v_amp_limit"), "number.soc": _entry("v_target_soc")})
    _, entity_module = _load(monkeypatch, registry)
    coordinator = SimpleNamespace(is_fetch_supported=lambda attr: attr != "amp_limit")
    entities = [FakeEntity("v_amp_limit", "amp_limit"), FakeEntity("v_target_soc", None)]

    result = entity_module.async_filter_supported_entities(None, coordinator, "number", entities)

    assert [e.unique_id for e in result] == ["v_target_soc"]
    assert registry.updates == [("number.amp", RegistryEntryDisabler.INTEGRATION)]


def test_unsupported_entity_not_in_registry_is_just_skipped(monkeypatch):
    registry = FakeRegistry()
    _, entity_module = _load(monkeypatch, registry)
    coordinator = SimpleNamespace(is_fetch_supported=lambda attr: False)

    result = entity_module.async_filter_supported_entities(
        None, coordinator, "number", [FakeEntity("v_amp_limit", "amp_limit")]
    )

    assert result == []
    assert registry.updates == []


def test_integration_disabled_entity_is_reenabled_when_supported(monkeypatch):
    registry = FakeRegistry({"number.amp": _entry("v_amp_limit", RegistryEntryDisabler.INTEGRATION)})
    _, entity_module = _load(monkeypatch, registry)
    coordinator = SimpleNamespace(is_fetch_supported=lambda attr: True)

    result = entity_module.async_filter_supported_entities(
        None, coordinator, "number", [FakeEntity("v_amp_limit", "amp_limit")]
    )

    assert len(result) == 1
    assert registry.updates == [("number.amp", None)]


def test_user_disabled_entity_is_left_alone(monkeypatch):
    registry = FakeRegistry({"number.amp": _entry("v_amp_limit", RegistryEntryDisabler.USER)})
    _, entity_module = _load(monkeypatch, registry)
    supported = SimpleNamespace(is_fetch_supported=lambda attr: True)
    unsupported = SimpleNamespace(is_fetch_supported=lambda attr: False)
    entity = FakeEntity("v_amp_limit", "amp_limit")

    entity_module.async_filter_supported_entities(None, supported, "number", [entity])
    entity_module.async_filter_supported_entities(None, unsupported, "number", [entity])

    assert registry.updates == []


def test_charge_location_data_is_unknown_until_fetched(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    data = coordinator_module.PolestarVehicleData()
    coordinator = _coordinator(coordinator_module, FakeVehicle({}))
    coordinator.data = data

    assert data.charge_locations is None
    assert data.current_charge_location is None
    assert coordinator.current_charge_location_details is None


class EmptyPrecleaningVehicle(FakeVehicle):
    def __init__(self, errors: dict[str, Exception], precleaning) -> None:
        super().__init__(errors)
        self._precleaning = precleaning

    async def get_precleaning(self):
        self.calls.append("precleaning")
        if isinstance(self._precleaning, Exception):
            raise self._precleaning
        return self._precleaning


@pytest.mark.asyncio
async def test_connectivity_endpoint_removed_is_unsupported(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())

    class Vehicle(FakeVehicle):
        async def get_connectivity(self):
            raise GRPCError(Status.UNIMPLEMENTED, "Method not found: DashboardService/GetLatestDashboard")

    coordinator = _coordinator(coordinator_module, Vehicle({}))

    await coordinator._async_fetch_values(("connectivity", "battery"), coordinator_module.PolestarVehicleData())

    assert not coordinator.is_fetch_supported("connectivity")


@pytest.mark.asyncio
async def test_precleaning_with_no_data_on_first_poll_is_disabled(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _coordinator(coordinator_module, EmptyPrecleaningVehicle({}, None))

    await coordinator._async_fetch_values(("precleaning", "battery"), coordinator_module.PolestarVehicleData())
    coordinator._record_no_data_fetches()

    assert not coordinator.is_fetch_supported("precleaning")
    assert coordinator.is_fetch_supported("battery")


@pytest.mark.asyncio
async def test_precleaning_with_data_stays_enabled(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _coordinator(coordinator_module, EmptyPrecleaningVehicle({}, "pre-cleaning data"))

    await coordinator._async_fetch_values(("precleaning",), coordinator_module.PolestarVehicleData())
    coordinator._record_no_data_fetches()

    assert coordinator.is_fetch_supported("precleaning")


@pytest.mark.asyncio
async def test_precleaning_fetch_failure_does_not_disable_entities(monkeypatch):
    coordinator_module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _coordinator(coordinator_module, EmptyPrecleaningVehicle({}, TimeoutError()))

    await coordinator._async_fetch_values(("precleaning",), coordinator_module.PolestarVehicleData())
    coordinator._record_no_data_fetches()

    assert coordinator.is_fetch_supported("precleaning")


def test_polestar_4_detection(monkeypatch):
    _load(monkeypatch, FakeRegistry())
    utils = sys.modules["_polestar_unsupported_under_test.utils"]

    assert utils.is_polestar_4("Polestar 4", "ANYVIN")
    assert utils.is_polestar_4("4", "ANYVIN")
    assert utils.is_polestar_4(None, "YSM4ZPBA1SF419419")
    assert not utils.is_polestar_4("Polestar 2", "YSM4ZPBA1SF419419")
    assert not utils.is_polestar_4(None, "YSMFD3KA0RL000001")
    assert not utils.is_polestar_4("", "LPSVSEDB4NL000001")


def test_steering_wheel_heating_is_on_off(monkeypatch):
    _load(monkeypatch, FakeRegistry())
    utils = sys.modules["_polestar_unsupported_under_test.utils"]

    assert utils.normalise_steering_wheel_option("level1") == "level3"
    assert utils.normalise_steering_wheel_option("level2") == "level3"
    assert utils.normalise_steering_wheel_option("level3") == "level3"
    assert utils.normalise_steering_wheel_option("off") == "off"
    assert utils.normalise_steering_wheel_option("unspecified") == "unspecified"


def _new_coordinator(module, supports_charge_locations):
    vehicle = FakeVehicle({})
    vehicle.supports_charge_locations = supports_charge_locations
    return module.PolestarCoordinator(None, vehicle, SimpleNamespace(options={}))


def test_car_without_charge_locations_is_not_polled_for_them(monkeypatch):
    module, _ = _load(monkeypatch, FakeRegistry())

    coordinator = _new_coordinator(module, False)

    assert not coordinator.is_fetch_supported("charge_locations")
    assert not coordinator.is_fetch_supported("current_charge_location")
    assert coordinator.is_fetch_supported("battery")


def test_charge_locations_stay_enabled_when_supported_or_unknown(monkeypatch):
    module, _ = _load(monkeypatch, FakeRegistry())

    assert _new_coordinator(module, True).is_fetch_supported("charge_locations")
    assert _new_coordinator(module, None).is_fetch_supported("charge_locations")


def test_entities_the_integration_no_longer_provides_are_removed_from_the_registry(monkeypatch):
    registry = FakeRegistry({"button.unlock": _entry("v_unlock_trunk"), "button.honk": _entry("v_honk")})
    _, entity_module = _load(monkeypatch, registry)

    entity_module.async_remove_registered_entities(None, "button", ["v_unlock_trunk", "v_never_existed"])

    assert registry.removed == ["button.unlock"]
    assert "button.honk" in registry.entries
