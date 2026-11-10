"""Zone activity from the amplifier's web page.

``GET http://<amp>/json/operation.json`` is what the amplifier's own web UI reads for
its operation page. Each entry of ``outputZones`` has a ``status``: ``Active`` while
the zone's output stage is on, ``Off`` while Signal Sense has it idle for lack of
input signal. So with Signal Sense on, ``Active`` means the zone is getting audio
(the amplifier keeps it on for its own hold time after the signal stops). Digital
outputs always read ``Active`` and are left out.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SIGNAL_INTERVAL, DEFAULT_SIGNAL_INTERVAL, MAX_MISSED_POLLS

_LOGGER = logging.getLogger(__name__)

PATH = "/json/operation.json"
TIMEOUT = 5
ACTIVE = "active"


def parse_activity(data: dict[str, Any]) -> dict[str, str]:
    """Each amplified zone's status by code (``Z<n>``), as the amplifier words it."""
    out: dict[str, str] = {}
    for zone in data.get("outputZones") or []:
        if not isinstance(zone, dict) or zone.get("isDigital"):
            continue
        number, status = zone.get("zoneNumber"), zone.get("status")
        if isinstance(number, int) and number > 0 and isinstance(status, str):
            out[f"Z{number}"] = status
    if not out:
        raise ValueError("no zones in reply")
    return out


def signal_interval(options: dict[str, Any]) -> timedelta:
    """The poll interval chosen in the options (default 10 s)."""
    return timedelta(seconds=int(options.get(CONF_SIGNAL_INTERVAL, DEFAULT_SIGNAL_INTERVAL)))


class ActivityCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Polls the zones' Signal Sense status every few seconds."""

    def __init__(self, hass: HomeAssistant, config_entry, host: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"AudioControl {host} activity",
            update_interval=signal_interval(config_entry.options),
            always_update=False,
        )
        self.host = host
        self._session = async_get_clientsession(hass)
        self._missed = 0

    def is_active(self, code: str) -> bool | None:
        """Whether the zone is on (None if the amplifier didn't list it)."""
        status = (self.data or {}).get(code)
        return None if status is None else status.strip().lower() == ACTIVE

    async def _async_update_data(self) -> dict[str, str]:
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.get(f"http://{self.host}{PATH}")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            status = parse_activity(data)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._missed += 1
            if self.data is None or self._missed > MAX_MISSED_POLLS:
                raise UpdateFailed(f"{self.host}: zone activity unavailable: {err}") from err
            _LOGGER.debug(
                "%s: activity poll failed (%d), keeping last: %s", self.host, self._missed, err
            )
            return self.data
        self._missed = 0
        return status
