"""Protection, overheating, line voltage and short-circuit alarms."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Status
from .entity import DirectorEntity, DirectorOutputEntity

PARALLEL_UPDATES = 0

NORMAL = "normal"


def _abnormal(value: str | None) -> bool:
    return bool(value) and value.strip().lower() != NORMAL


def _overheating_zones(status: Status) -> list[str]:
    return [z.name for z in status.zones if _abnormal(z.temperature_status)]


def _shorted_zones(status: Status) -> list[str]:
    zones = status.zones
    return [zones[i].name for i, short in enumerate(status.shorts) if short and i < len(zones)]


@dataclass(frozen=True, kw_only=True)
class AmpBinaryDescription(BinarySensorEntityDescription):
    """An amplifier-wide alarm, with the raw status as attributes."""

    is_on_fn: Callable[[Status], bool]
    attrs_fn: Callable[[Status], dict[str, Any]]


AMP_BINARY_SENSORS = (
    AmpBinaryDescription(
        key="protection",
        translation_key="protection",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: _abnormal(s.protection) or bool(s.zone_protect.strip()),
        attrs_fn=lambda s: {"status": s.protection, "zones": s.zone_protect.strip()},
    ),
    AmpBinaryDescription(
        key="overheating",
        translation_key="overheating",
        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: (
            _abnormal(s.thermal_protection)
            or _abnormal(s.temperature_status)
            or bool(_overheating_zones(s))
        ),
        attrs_fn=lambda s: {
            "status": s.temperature_status,
            "thermal_protection": s.thermal_protection,
            "zones": _overheating_zones(s),
        },
    ),
    AmpBinaryDescription(
        key="line_voltage",
        translation_key="line_voltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: _abnormal(s.voltage_status),
        attrs_fn=lambda s: {"status": s.voltage_status},
    ),
    AmpBinaryDescription(
        key="short_circuit",
        translation_key="short_circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: any(s.shorts),
        attrs_fn=lambda s: {"zones": _shorted_zones(s)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the alarms."""
    coord = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        AmpBinarySensor(coord, desc) for desc in AMP_BINARY_SENSORS
    ]
    entities += [ZoneOverheatingSensor(coord, zone.code) for zone in coord.data.zones]
    async_add_entities(entities)


class AmpBinarySensor(DirectorEntity, BinarySensorEntity):
    """An amplifier-wide alarm."""

    entity_description: AmpBinaryDescription

    def __init__(self, coordinator: DirectorCoordinator, desc: AmpBinaryDescription) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def is_on(self) -> bool:
        """Whether the alarm is raised."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The amplifier's own wording."""
        return self.entity_description.attrs_fn(self.coordinator.data)


class ZoneOverheatingSensor(DirectorOutputEntity, BinarySensorEntity):
    """A zone's output stage reports anything but Normal (e.g. OverTemp)."""

    _attr_translation_key = "zone_overheating"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "overheating", code)

    @property
    def is_on(self) -> bool:
        """Whether the zone is too hot."""
        return _abnormal(self.output.temperature_status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Temperature and the amplifier's wording."""
        return {"temperature": self.output.temperature, "status": self.output.temperature_status}
