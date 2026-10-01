"""All zones on/off, and amplifier power."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Director
from .entity import DirectorEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DirectorButtonDescription(ButtonEntityDescription):
    """A one-shot command."""

    press_fn: Callable[[Director], Awaitable[None]]


BUTTONS = (
    DirectorButtonDescription(
        key="all_zones_on",
        translation_key="all_zones_on",
        press_fn=lambda d: d.async_all_zones(True),
    ),
    DirectorButtonDescription(
        key="all_zones_off",
        translation_key="all_zones_off",
        press_fn=lambda d: d.async_all_zones(False),
    ),
    # The amplifier doesn't report its power state, so these are buttons, not a switch.
    DirectorButtonDescription(
        key="power_on",
        translation_key="power_on",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda d: d.async_amp_power(True),
    ),
    DirectorButtonDescription(
        key="standby",
        translation_key="standby",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda d: d.async_amp_power(False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons."""
    coord = entry.runtime_data
    async_add_entities(DirectorButton(coord, desc) for desc in BUTTONS)


class DirectorButton(DirectorEntity, ButtonEntity):
    """A one-shot command."""

    entity_description: DirectorButtonDescription

    def __init__(self, coordinator: DirectorCoordinator, desc: DirectorButtonDescription) -> None:
        """Set up the button."""
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    async def async_press(self) -> None:
        """Send the command."""
        await self._async_run(self.entity_description.press_fn(self.coordinator.director))
