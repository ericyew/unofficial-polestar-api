from __future__ import annotations

from polestar_api.models.health import Health, ServiceWarning


def test_service_warning_overdue_is_known():
    assert ServiceWarning(9) is ServiceWarning.REGULAR_MAINTENANCE_OVERDUE


def test_unknown_enum_value_falls_back_to_unspecified():
    data = Health(service_warning=ServiceWarning.NO_WARNING, days_to_service=12).to_bytes()
    patched = data.replace(bytes([0x28, 0x01]), bytes([0x28, 0x7F]))
    assert patched != data

    health = Health.from_bytes(patched)

    assert health.service_warning == ServiceWarning.UNSPECIFIED
    assert health.days_to_service == 12
