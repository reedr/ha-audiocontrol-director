"""Per-zone signal sense and loudness."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .entity import DirectorOutputEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches."""
    coord = entry.runtime_data
    entities: list[SwitchEntity] = []
    for zone in coord.data.zones:
        entities += [SignalSenseSwitch(coord, zone.code), LoudnessSwitch(coord, zone.code)]
    async_add_entities(entities)


class SignalSenseSwitch(DirectorOutputEntity, SwitchEntity):
    """The zone turns itself on when its input carries a signal."""

    _attr_translation_key = "signal_sense"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the switch."""
        super().__init__(coordinator, "signal_sense", code)

    @property
    def is_on(self) -> bool:
        """Whether signal sense is on."""
        return self.output.signal_sense

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn signal sense on."""
        await self._async_run(self.coordinator.director.async_set_signal_sense(self._code, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn signal sense off."""
        await self._async_run(self.coordinator.director.async_set_signal_sense(self._code, False))


class LoudnessSwitch(DirectorOutputEntity, SwitchEntity):
    """Loudness compensation; read once a minute while any of these is enabled."""

    _attr_translation_key = "loudness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the switch."""
        super().__init__(coordinator, "loudness", code)

    async def async_added_to_hass(self) -> None:
        """Start reading loudness."""
        await super().async_added_to_hass()
        if not self.coordinator.want_loudness:
            self.coordinator.want_loudness = True
            self.coordinator.loudness_changed()
            await self.coordinator.async_request_refresh()

    @property
    def is_on(self) -> bool | None:
        """Whether loudness is on, once read."""
        return self.coordinator.data.loudness.get(self._code)

    async def _async_set(self, on: bool) -> None:
        try:
            await self._async_run(self.coordinator.director.async_set_loudness(self._code, on))
        finally:
            self.coordinator.loudness_changed()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn loudness on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn loudness off."""
        await self._async_set(False)
