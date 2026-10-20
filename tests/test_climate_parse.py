"""Parking climatization status: seat positions and the climate end time."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from polestar_api.codec import encode, encode_message
from polestar_api.models.climatization import HeatingIntensity
from polestar_api.services.climate import ClimateServiceClient

from .test_unsupported_entities import FakeRegistry, _load

SCHEMA = {
    "status": (2, "int32"),
    "left": (3, "int32"),
    "front_left": (9, "int32"),
    "front_right": (10, "int32"),
    "rear_left": (11, "int32"),
    "rear_right": (12, "int32"),
}
TIMESTAMP = {"seconds": (1, "int64")}


def _status(**values: int) -> bytes:
    return encode(SCHEMA, values)


def _timestamp(field: int, seconds: int) -> bytes:
    return encode_message(field, encode(TIMESTAMP, {"seconds": seconds}))


def test_rear_seats_are_left_then_right():
    info = ClimateServiceClient._parse_digital_twin(
        _status(status=5, front_left=2, front_right=3, rear_left=4, rear_right=1)
    )

    assert info.front_left_seat == HeatingIntensity.LEVEL1
    assert info.front_right_seat == HeatingIntensity.LEVEL2
    assert info.rear_left_seat == HeatingIntensity.LEVEL3
    assert info.rear_right_seat == HeatingIntensity.OFF


def test_start_and_end_time_are_read():
    info = ClimateServiceClient._parse_digital_twin(
        _status(status=5, left=30) + _timestamp(14, 1_800_000_000) + _timestamp(16, 1_800_001_800)
    )

    assert info.started_at == 1_800_000_000
    assert info.ending_at == 1_800_001_800
    assert info.time_remaining == 30


def test_missing_times_are_none():
    info = ClimateServiceClient._parse_digital_twin(_status(status=1, left=30))

    assert info.started_at is None
    assert info.ending_at is None


def _utils(monkeypatch):
    _load(monkeypatch, FakeRegistry())
    return sys.modules["_polestar_unsupported_under_test.utils"]


def _climate(*, active=True, ending_at=None, time_remaining=30):
    return SimpleNamespace(is_active=active, ending_at=ending_at, time_remaining=time_remaining)


def test_remaining_minutes_count_down_from_the_end_time(monkeypatch):
    utils = _utils(monkeypatch)
    end = 10_000.0

    assert utils.climate_minutes_remaining(_climate(ending_at=10_000), end - 1800) == 30
    assert utils.climate_minutes_remaining(_climate(ending_at=10_000), end - 90) == 2
    assert utils.climate_minutes_remaining(_climate(ending_at=10_000), end - 30) == 1
    assert utils.climate_minutes_remaining(_climate(ending_at=10_000), end + 5) == 0


def test_remaining_minutes_fall_back_to_the_cars_runtime(monkeypatch):
    utils = _utils(monkeypatch)

    assert utils.climate_minutes_remaining(_climate(ending_at=None, time_remaining=30), 0.0) == 30
    assert utils.climate_minutes_remaining(_climate(active=False, ending_at=10_000, time_remaining=30), 0.0) == 30
    assert utils.climate_minutes_remaining(None, 0.0) is None


def test_end_time_only_while_the_climate_runs(monkeypatch):
    utils = _utils(monkeypatch)

    assert utils.climate_end_time(_climate(ending_at=10_000)) == 10_000.0
    assert utils.climate_end_time(_climate(active=False, ending_at=10_000)) is None
    assert utils.climate_end_time(_climate(ending_at=None)) is None
    assert utils.climate_end_time(None) is None


def test_a_single_climate_timer_has_no_number(monkeypatch):
    utils = _utils(monkeypatch)

    assert utils.climate_timer_label(0, 1, "Parking climate timer") == "Parking climate timer"
    assert utils.climate_timer_label(0, 1, "Timer") == "Timer"


def test_several_or_unknown_climate_timers_keep_their_numbers(monkeypatch):
    utils = _utils(monkeypatch)

    assert utils.climate_timer_label(0, 3, "Parking climate timer") == "Parking climate timer 1"
    assert utils.climate_timer_label(2, 3, "Timer") == "Timer 3"
    assert utils.climate_timer_label(1, None, "Timer") == "Timer 2"
