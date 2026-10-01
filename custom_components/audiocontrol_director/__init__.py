"""The AudioControl Director integration.

Based on Philip Flesher's audiocontrol-director-hass and
audiocontrol-director-telnet-py.
"""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Director
from .migration import async_prepare_registry, async_prune_entities

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: DirectorConfigEntry) -> bool:
    """Set up an amplifier from a config entry."""
    director = Director(entry.data[CONF_HOST])
    # Registered before the coordinator so it runs after the coordinator's shutdown.
    entry.async_on_unload(director.close)
    coord = DirectorCoordinator(hass, entry, director)
    await coord.async_config_entry_first_refresh()
    entry.runtime_data = coord

    async_prepare_registry(hass, entry, coord)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_prune_entities(hass, entry, coord)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: DirectorConfigEntry) -> None:
    """Source names changed; players read them on their next state write."""
    entry.runtime_data.async_update_listeners()


async def async_unload_entry(hass: HomeAssistant, entry: DirectorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
