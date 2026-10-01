"""Per-zone EQ preset."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Status
from .entity import DirectorOutputEntity

PARALLEL_UPDATES = 0

PRESETS = range(1, 7)


def preset_names(status: Status) -> dict[int, str]:
    """Preset names as seen in zone status; presets in no zone are "Preset <n>"."""
    names = {n: f"Preset {n}" for n in PRESETS}
    for zone in status.zones:
        if zone.eq_preset in names:
            names[zone.eq_preset] = zone.eq_name
    return names


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects."""
    coord = entry.runtime_data
    async_add_entities(EqSelect(coord, zone.code) for zone in coord.data.zones)


class EqSelect(DirectorOutputEntity, SelectEntity):
    """Recall one of the six EQ presets; unknown while the zone has unsaved changes."""

    _attr_translation_key = "eq"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the select."""
        super().__init__(coordinator, "eq", code)

    @property
    def _names(self) -> dict[int, str]:
        return preset_names(self.coordinator.data)

    @property
    def options(self) -> list[str]:
        """The six presets."""
        return list(self._names.values())

    @property
    def current_option(self) -> str | None:
        """The recalled preset, if the zone still matches it."""
        preset = self.output.eq_preset
        return self._names.get(preset) if preset else None

    async def async_select_option(self, option: str) -> None:
        """Recall a preset."""
        preset = next(n for n, name in self._names.items() if name == option)
        await self._async_run(self.coordinator.director.async_set_eq(self._code, preset))
