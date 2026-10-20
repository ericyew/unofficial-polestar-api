"""Car information — model name, model year, market and registration from the MyCars service."""

from __future__ import annotations

from dataclasses import dataclass

from ..wire import ProtoMessage


@dataclass(frozen=True)
class CarDetails(ProtoMessage, schema={
    1: "vin",
    5: "vehicle_type_code",
    6: "vehicle_type_name",
    7: "model_year",
    9: "consumer_software_version",
    10: "market",
}):
    """Identity of a car. ``vehicle_type_name`` is the model name, e.g. ``Polestar 4``."""

    vin: str = ""
    vehicle_type_code: str = ""
    vehicle_type_name: str = ""
    model_year: str = ""
    consumer_software_version: str = ""
    market: str = ""


@dataclass(frozen=True)
class MyCar(ProtoMessage, schema={
    1: "car",
    2: "user_is_linked",
    3: "user_is_owner",
    4: "registration_plate",
}):
    """One car on the account, as returned by ``car_information.CarInformation/GetMyCars``."""

    car: CarDetails | None = None
    user_is_linked: bool = False
    user_is_owner: bool = False
    registration_plate: str = ""
