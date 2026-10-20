"""Tests for the MyCars car information service and the vehicle details it fills in."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from polestar_api.codec import encode, encode_message
from polestar_api.models.car_information import MyCar
from polestar_api.services import car_information as service_module
from polestar_api.services.car_information import CarInformationServiceClient
from polestar_api.vehicle import Vehicle

CAR_SCHEMA = {
    "vin": (1, "string"),
    "code": (5, "string"),
    "name": (6, "string"),
    "year": (7, "string"),
    "software": (9, "string"),
    "market": (10, "string"),
}
MY_CAR_SCHEMA = {"linked": (2, "bool"), "owner": (3, "bool"), "plate": (4, "string")}


def _my_car(vin: str, name: str, *, plate: str | None = None, year: str = "2025") -> bytes:
    car = encode(
        CAR_SCHEMA,
        {"vin": vin, "code": "814", "name": name, "year": year, "software": "4.2.11", "market": "AU"},
    )
    values = {"linked": True, "owner": True}
    if plate is not None:
        values["plate"] = plate
    return encode_message(1, car) + encode(MY_CAR_SCHEMA, values)


def _response(*my_cars: bytes) -> bytes:
    return b"".join(encode_message(1, my_car) for my_car in my_cars)


class FakeConnection:
    channel = object()
    backend = SimpleNamespace(car_information_svc="/car_information.CarInformation")

    async def get_metadata(self, vin=None):
        return {}


def _client(monkeypatch, response: bytes, calls: list | None = None) -> CarInformationServiceClient:
    async def fake_unary_unary(channel, method, request, **kwargs):
        if calls is not None:
            calls.append((method, request))
        return response

    monkeypatch.setattr(service_module.grpc_call, "unary_unary", fake_unary_unary)
    return CarInformationServiceClient(FakeConnection(), "VIN0000000000001")


@pytest.mark.asyncio
async def test_decodes_a_single_car(monkeypatch):
    calls: list = []
    client = _client(monkeypatch, _response(_my_car("VIN0000000000001", "Polestar 4", plate="ABC123")), calls)

    cars = await client.get_my_cars()

    assert calls == [("/car_information.CarInformation/GetMyCars", b"")]
    assert len(cars) == 1
    assert isinstance(cars[0], MyCar)
    assert cars[0].car.vin == "VIN0000000000001"
    assert cars[0].car.vehicle_type_name == "Polestar 4"
    assert cars[0].car.vehicle_type_code == "814"
    assert cars[0].car.model_year == "2025"
    assert cars[0].car.market == "AU"
    assert cars[0].car.consumer_software_version == "4.2.11"
    assert cars[0].registration_plate == "ABC123"
    assert cars[0].user_is_owner


@pytest.mark.asyncio
async def test_decodes_several_cars_and_picks_ours_by_vin(monkeypatch):
    client = _client(
        monkeypatch,
        _response(_my_car("OTHERVIN000000001", "Polestar 2"), _my_car("VIN0000000000001", "Polestar 4")),
    )

    assert len(await client.get_my_cars()) == 2
    assert (await client.get_my_car()).car.vehicle_type_name == "Polestar 4"


@pytest.mark.asyncio
async def test_returns_none_when_the_vin_is_not_on_the_account(monkeypatch):
    client = _client(monkeypatch, _response(_my_car("OTHERVIN000000001", "Polestar 2")))

    assert await client.get_my_car() is None


@pytest.mark.asyncio
async def test_empty_response_means_no_cars(monkeypatch):
    client = _client(monkeypatch, b"")

    assert await client.get_my_cars() == []


def _vehicle(monkeypatch, response: bytes, **details) -> Vehicle:
    monkeypatch.setattr(service_module.grpc_call, "unary_unary", _fixed(response))
    return Vehicle(vin="VIN0000000000001", connection=FakeConnection(), **details)


def _fixed(response: bytes):
    async def fake_unary_unary(channel, method, request, **kwargs):
        return response

    return fake_unary_unary


@pytest.mark.asyncio
async def test_vehicle_without_details_gets_them_from_car_information(monkeypatch):
    vehicle = _vehicle(monkeypatch, _response(_my_car("VIN0000000000001", "Polestar 4", plate="ABC123")))

    await vehicle.async_load_car_information()

    assert vehicle.model_name == "Polestar 4"
    assert vehicle.model_year == 2025
    assert vehicle.registration_no == "ABC123"


@pytest.mark.asyncio
async def test_details_from_discovery_are_kept(monkeypatch):
    vehicle = _vehicle(
        monkeypatch,
        _response(_my_car("VIN0000000000001", "Polestar 4", plate="ABC123")),
        model_name="Discovery name",
        model_year=2024,
        registration_no="XYZ789",
    )

    await vehicle.async_load_car_information()

    assert vehicle.model_name == "Discovery name"
    assert vehicle.model_year == 2024
    assert vehicle.registration_no == "XYZ789"


@pytest.mark.asyncio
async def test_a_missing_registration_stays_none(monkeypatch):
    vehicle = _vehicle(monkeypatch, _response(_my_car("VIN0000000000001", "Polestar 4")))

    await vehicle.async_load_car_information()

    assert vehicle.model_name == "Polestar 4"
    assert vehicle.registration_no is None


@pytest.mark.asyncio
async def test_failure_leaves_the_vehicle_unchanged(monkeypatch):
    async def failing(channel, method, request, **kwargs):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(service_module.grpc_call, "unary_unary", failing)
    vehicle = Vehicle(vin="VIN0000000000001", connection=FakeConnection())

    await vehicle.async_load_car_information()

    assert vehicle.model_name is None
    assert vehicle.model_year is None
    assert vehicle.registration_no is None
