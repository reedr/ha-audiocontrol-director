"""Coordinator for one AudioControl Director amplifier."""

from __future__ import annotations

import logging
import time
from dataclasses import replace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SOURCE_NAMES, LOUDNESS_INTERVAL, UPDATE_INTERVAL
from .director import Director, DirectorError, Source, Status

_LOGGER = logging.getLogger(__name__)

type DirectorConfigEntry = ConfigEntry[DirectorCoordinator]


def topology(status: Status) -> tuple:
    """What the entity layout depends on: outputs and group membership."""
    return tuple((o.code, o.group) for o in status.outputs.values())


class DirectorCoordinator(DataUpdateCoordinator[Status]):
    """Polls SYSTEMstat? and relays commands."""

    config_entry: DirectorConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: DirectorConfigEntry, director: Director
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"AudioControl {director.host}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=0.3, immediate=False),
        )
        self.director = director
        self.base_id: str = config_entry.unique_id or config_entry.entry_id
        self.want_loudness = False
        self._loudness_at = 0.0
        self._loudness_gen = 0
        self._layout: tuple | None = None
        self._pending_layout: tuple | None = None

    @property
    def sources(self) -> list[Source]:
        """The amplifier's inputs."""
        return self.director.sources

    def source_name(self, code: str | None) -> str | None:
        """Display name of an input: the user's name or the amplifier's."""
        if code is None:
            return None
        names: dict[str, str] = self.config_entry.options.get(CONF_SOURCE_NAMES, {})
        if names.get(code):
            return names[code]
        for source in self.sources:
            if source.code == code:
                return source.name
        return code

    def source_code(self, name: str) -> str | None:
        """Resolve a display name, the amplifier's name or a code (MX1, DXa)."""
        names: dict[str, str] = self.config_entry.options.get(CONF_SOURCE_NAMES, {})
        for source in self.sources:
            if name in (names.get(source.code), source.name, source.code):
                return source.code
        return None

    def loudness_changed(self) -> None:
        """Re-read loudness on the next poll, even if one is under way."""
        self._loudness_at = 0.0
        self._loudness_gen += 1

    async def _async_setup(self) -> None:
        try:
            await self.director.async_get_sources()
        except DirectorError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> Status:
        loud = self.want_loudness and time.monotonic() - self._loudness_at >= (
            LOUDNESS_INTERVAL.total_seconds()
        )
        gen = self._loudness_gen
        try:
            status = await self.director.async_get_status(loudness=loud)
        except DirectorError as err:
            raise UpdateFailed(str(err)) from err
        if loud and gen == self._loudness_gen:
            self._loudness_at = time.monotonic()
        elif self.data is not None:
            status = replace(status, loudness=self.data.loudness)

        layout = topology(status)
        if self._layout is None:
            self._layout = layout
        elif layout != self._layout:
            # A reply cut short would look like a change too, so act only once
            # two polls in a row agree.
            if layout != self._pending_layout:
                self._pending_layout = layout
                raise UpdateFailed(f"{self.director.host}: zones or groups changed; rechecking")
            _LOGGER.info("%s: zones or groups changed; reloading", self.director.host)
            self._layout = layout
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        self._pending_layout = None
        return status
