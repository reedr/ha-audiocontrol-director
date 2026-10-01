"""Base entities for AudioControl Director."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, DOMAIN, MANUFACTURER
from .coordinator import DirectorCoordinator
from .director import DirectorError, Output


def amp_device_info(coordinator: DirectorCoordinator) -> DeviceInfo:
    """The amplifier's device; every entity belongs to it."""
    status = coordinator.data
    zones = len(status.zones)
    digital = sum(1 for s in coordinator.sources if s.code.startswith("DX"))
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.base_id)},
        manufacturer=MANUFACTURER,
        model=f"Director ({zones} zones, {digital} digital inputs)",
        name=status.name or f"AudioControl {coordinator.director.host}",
        configuration_url=f"http://{coordinator.director.host}",
    )
    if mac := coordinator.config_entry.data.get(CONF_MAC):
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return info


def zone_label(coordinator: DirectorCoordinator, code: str) -> str:
    """The output's name, plus its number if another output has the same name."""
    outputs = coordinator.data.outputs
    out = outputs[code]
    same = [o for o in outputs.values() if o.name.casefold() == out.name.casefold()]
    return f"{out.name} {out.number}" if len(same) > 1 else out.name


class DirectorEntity(CoordinatorEntity[DirectorCoordinator]):
    """An entity of one amplifier; unique IDs are ``<entry unique ID>_<key>``."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DirectorCoordinator, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.base_id}_{key}"
        self._attr_device_info = amp_device_info(coordinator)
        # The platform module's name is the entity domain (media_player, sensor, ...).
        coordinator.unique_ids.add((type(self).__module__.rsplit(".", 1)[-1], self._attr_unique_id))

    async def _async_run(self, command: Awaitable[None]) -> None:
        """Run a command, then poll soon to pick up the result."""
        try:
            await command
        except DirectorError as err:
            raise HomeAssistantError(
                f"AudioControl {self.coordinator.director.host}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()


class DirectorOutputEntity(DirectorEntity):
    """An entity of one zone or digital output, named after it."""

    def __init__(self, coordinator: DirectorCoordinator, key: str, code: str) -> None:
        """Set up the entity; ``key`` is appended to the output's code."""
        super().__init__(coordinator, f"{code}_{key}")
        self._code = code
        self._attr_translation_placeholders = {"zone": zone_label(coordinator, code)}

    @property
    def output(self) -> Output:
        """The output's latest status."""
        return self.coordinator.data.outputs[self._code]

    @property
    def available(self) -> bool:
        """Unavailable if the output has disappeared (a reload follows)."""
        return super().available and self._code in self.coordinator.data.outputs
