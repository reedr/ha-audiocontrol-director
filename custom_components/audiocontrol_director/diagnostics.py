"""Diagnostics for AudioControl Director."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import DirectorConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DirectorConfigEntry
) -> dict[str, Any]:
    """Return the entry, the inputs and the last status (nothing secret is stored)."""
    coord = entry.runtime_data
    return {
        "entry": entry.as_dict(),
        "sources": [asdict(s) for s in coord.sources],
        "status": asdict(coord.data) if coord.data else None,
    }
