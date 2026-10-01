"""Amplifier and zone temperature, line voltage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Status
from .entity import DirectorEntity, DirectorOutputEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AmpSensorDescription(SensorEntityDescription):
    """An amplifier-wide reading."""

    value_fn: Callable[[Status], int | None]


AMP_SENSORS = (
    AmpSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.temperature,
    ),
    AmpSensorDescription(
        key="voltage",
        translation_key="line_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.voltage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors."""
    coord = entry.runtime_data
    entities: list[SensorEntity] = [AmpSensor(coord, desc) for desc in AMP_SENSORS]
    entities += [ZoneTemperatureSensor(coord, zone.code) for zone in coord.data.zones]
    async_add_entities(entities)


class AmpSensor(DirectorEntity, SensorEntity):
    """An amplifier-wide reading."""

    entity_description: AmpSensorDescription

    def __init__(self, coordinator: DirectorCoordinator, desc: AmpSensorDescription) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> int | None:
        """The reading."""
        return self.entity_description.value_fn(self.coordinator.data)


class ZoneTemperatureSensor(DirectorOutputEntity, SensorEntity):
    """One zone's output stage temperature."""

    _attr_translation_key = "zone_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "temperature", code)

    @property
    def native_value(self) -> int | None:
        """The reading."""
        return self.output.temperature
