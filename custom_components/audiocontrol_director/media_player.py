"""Media players: one per group, one per ungrouped zone, one per digital output."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .director import Output
from .entity import DirectorEntity, zone_label

PARALLEL_UPDATES = 0

# Unmuting restores this when nothing was remembered (e.g. after a restart).
_UNMUTE_DEFAULT = 50


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DirectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the players."""
    coord = entry.runtime_data
    status = coord.data
    entities: list[MediaPlayerEntity] = [
        GroupPlayer(coord, group) for group in sorted(status.groups())
    ]
    entities += [
        OutputPlayer(coord, out.code)
        for out in status.outputs.values()
        if out.is_digital or not out.group
    ]
    async_add_entities(entities)


class DirectorPlayer(DirectorEntity, MediaPlayerEntity):
    """Common player behaviour; ``_target`` is the protocol prefix (Z3, GRP1, DXOa)."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_volume_step = 0.05
    _target: str

    def __init__(self, coordinator: DirectorCoordinator, key: str) -> None:
        """Set up the player."""
        super().__init__(coordinator, key)
        self._unmute_volume = _UNMUTE_DEFAULT

    @property
    def _lead(self) -> Output:
        """The output whose settings the player shows."""
        raise NotImplementedError

    @property
    def _is_on(self) -> bool:
        return self._lead.is_on

    @property
    def state(self) -> MediaPlayerState:
        """On or off; the amplifier has no notion of playing."""
        return MediaPlayerState.ON if self._is_on else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float:
        """Volume, 0..1."""
        return self._lead.volume / 100

    @property
    def is_volume_muted(self) -> bool:
        """Muting sets the volume to 0."""
        return self._lead.volume == 0

    @property
    def source(self) -> str | None:
        """The input's display name."""
        return self.coordinator.source_name(self._lead.source)

    @property
    def source_list(self) -> list[str]:
        """Every input, by display name."""
        return [self.coordinator.source_name(s.code) or s.code for s in self.coordinator.sources]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The input's protocol code (MX1, DXa) and amplifier name."""
        code = self._lead.source
        amp_name = next((s.name for s in self.coordinator.sources if s.code == code), None)
        return {"source_id": code, "source_input": amp_name}

    async def async_turn_on(self) -> None:
        """Turn on."""
        await self._async_run(self.coordinator.director.async_set_power(self._target, True))

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self._async_run(self.coordinator.director.async_set_power(self._target, False))

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume, 0..1."""
        await self._async_set_volume(round(volume * 100))

    async def _async_set_volume(self, volume: int) -> None:
        await self._async_run(self.coordinator.director.async_set_volume(self._target, volume))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute by setting the volume to 0; unmute restores it."""
        if mute:
            if self._lead.volume:
                self._unmute_volume = self._lead.volume
            await self._async_set_volume(0)
        elif self._lead.volume == 0:
            await self._async_set_volume(self._unmute_volume)

    async def async_select_source(self, source: str) -> None:
        """Select an input by display name, amplifier name (Channel 1-2) or code (MX1)."""
        code = self.coordinator.source_code(source)
        if code is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": source},
            )
        await self._async_run(self.coordinator.director.async_set_source(self._target, code))


class OutputPlayer(DirectorPlayer):
    """An ungrouped zone or a digital output."""

    def __init__(self, coordinator: DirectorCoordinator, code: str) -> None:
        """Set up the player; the unique ID matches the old integration's."""
        super().__init__(coordinator, f"output_{code}")
        self._target = code
        self._attr_name = zone_label(coordinator, code)

    @property
    def _lead(self) -> Output:
        return self.coordinator.data.outputs[self._target]

    @property
    def available(self) -> bool:
        """Unavailable if the output has disappeared (a reload follows)."""
        return super().available and self._target in self.coordinator.data.outputs


class GroupPlayer(DirectorPlayer):
    """A group of zones, controlled together with GRP<n> commands."""

    def __init__(self, coordinator: DirectorCoordinator, group: int) -> None:
        """Set up the player, named after the group's first zone."""
        super().__init__(coordinator, f"group_{group}")
        self._group = group
        self._target = f"GRP{group}"
        self._attr_name = self._members[0].name

    @property
    def _members(self) -> list[Output]:
        return self.coordinator.data.groups().get(self._group, [])

    @property
    def available(self) -> bool:
        """Unavailable if the group has emptied (a reload follows)."""
        return super().available and bool(self._members)

    @property
    def _lead(self) -> Output:
        return self._members[0]

    @property
    def _is_on(self) -> bool:
        return any(zone.is_on for zone in self._members)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Also list the member zones."""
        return {
            **super().extra_state_attributes,
            "zones": [f"{z.code} {z.name}" for z in self._members],
        }
