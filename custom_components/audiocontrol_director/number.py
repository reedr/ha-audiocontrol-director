"""Per-zone volume (grouped zones), bass and treble."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Director, Output
from .entity import DirectorOutputEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZoneNumberDescription(NumberEntityDescription):
    """A per-zone setting."""

    value_fn: Callable[[Output], int]
    set_fn: Callable[[Director, str, int], Awaitable[None]]


VOLUME = ZoneNumberDescription(
    key="volume",
    translation_key="zone_volume",
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=PERCENTAGE,
    mode=NumberMode.SLIDER,
    value_fn=lambda o: o.volume,
    set_fn=lambda d, z, v: d.async_set_volume(z, v),
)
TONE = (
    ZoneNumberDescription(
        key="bass",
        translation_key="bass",
        native_min_value=-10,
        native_max_value=10,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.bass,
        set_fn=lambda d, z, v: d.async_set_bass(z, v),
    ),
    ZoneNumberDescription(
        key="treble",
        translation_key="treble",
        native_min_value=-10,
        native_max_value=10,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.treble,
        set_fn=lambda d, z, v: d.async_set_treble(z, v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the numbers. Ungrouped zones' volume is on their media player."""
    coord = entry.runtime_data
    entities: list[NumberEntity] = []
    for zone in coord.data.zones:
        if zone.group:
            entities.append(ZoneNumber(coord, VOLUME, zone.code))
        entities += [ZoneNumber(coord, desc, zone.code) for desc in TONE]
    async_add_entities(entities)


class ZoneNumber(DirectorOutputEntity, NumberEntity):
    """A per-zone setting."""

    entity_description: ZoneNumberDescription

    def __init__(
        self, coordinator: DirectorCoordinator, desc: ZoneNumberDescription, code: str
    ) -> None:
        """Set up the number."""
        super().__init__(coordinator, desc.key, code)
        self.entity_description = desc

    @property
    def native_value(self) -> int:
        """The setting."""
        return self.entity_description.value_fn(self.output)

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self._async_run(
            self.entity_description.set_fn(self.coordinator.director, self._code, int(value))
        )
