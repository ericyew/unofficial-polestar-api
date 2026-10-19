"""Stream and command updates must not restart the coordinator's poll timer."""

from __future__ import annotations

import asyncio

import pytest

from .test_unsupported_entities import FakeRegistry, FakeVehicle, _coordinator, _load


def _push_coordinator(module):
    coordinator = _coordinator(module, FakeVehicle({}))
    coordinator.data = None
    coordinator.last_update_success = False
    coordinator.listener_calls = 0

    def update_listeners() -> None:
        coordinator.listener_calls += 1

    def set_updated_data(data) -> None:
        raise AssertionError("async_set_updated_data restarts the poll timer")

    coordinator.async_update_listeners = update_listeners
    coordinator.async_set_updated_data = set_updated_data
    return coordinator


def test_push_updates_data_and_listeners_without_resetting_timer(monkeypatch):
    module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _push_coordinator(module)
    data = module.PolestarVehicleData()

    coordinator._async_push_data(data)

    assert coordinator.data is data
    assert coordinator.last_update_success is True
    assert coordinator.listener_calls == 1


@pytest.mark.asyncio
async def test_stream_updates_do_not_reset_poll_timer(monkeypatch):
    module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _push_coordinator(module)

    async def stream():
        yield "battery-1"
        yield "battery-2"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(5):
            await coordinator._async_run_stream("battery", stream)

    assert coordinator.data.battery == "battery-2"
    assert coordinator.listener_calls == 2


@pytest.mark.asyncio
async def test_partial_refresh_after_command_does_not_reset_poll_timer(monkeypatch):
    module, _ = _load(monkeypatch, FakeRegistry())
    coordinator = _push_coordinator(module)

    await coordinator.async_request_attrs_refresh("battery")

    assert coordinator.data.battery == "battery"
    assert coordinator.listener_calls == 1
