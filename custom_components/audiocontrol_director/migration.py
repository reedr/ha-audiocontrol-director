"""Registry clean-up: one device per amplifier, players per group.

The old integration made a device per zone and a player per zone. Here every
entity belongs to the amplifier's device, and zones in a group share one
player. Each setup:

* moves entities off any other device of the entry onto the amplifier's,
  keeping the zone device's area on the entity, then removes those devices;
* creates a missing group player's registry entry, named after its zones' old
  players (``music_room_amp_1`` -> ``media_player.music_room_amp``) in their area;
* after the platforms are set up, removes entities no longer provided, such as
  the players of zones that are now grouped.
"""

from __future__ import annotations

import logging
import re

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_LEGACY_UNIQUE_ID, DOMAIN
from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .entity import amp_device_info

_LOGGER = logging.getLogger(__name__)

_MEMBER_ID_SUFFIX = re.compile(r"_(?:\d+|sub(?:_\d+)?)$")
_MEMBER_NAME_SUFFIX = re.compile(r" (?:\d+|sub(?: \d+)?)$", re.IGNORECASE)


@callback
def async_prepare_registry(
    hass: HomeAssistant, entry: DirectorConfigEntry, coord: DirectorCoordinator
) -> None:
    """Collapse zone devices and seed group players (see module docstring)."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    amp = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, **amp_device_info(coord))

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if device.id == amp.id:
            continue
        for entity in er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        ):
            if entity.config_entry_id != entry.entry_id:
                continue
            ent_reg.async_update_entity(
                entity.entity_id,
                device_id=amp.id,
                area_id=entity.area_id or device.area_id,
            )
        _LOGGER.info("Removing per-zone device %s; its entities are on %s", device.name, amp.name)
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)

    base = coord.base_id
    for group, zones in coord.data.groups().items():
        unique_id = f"{base}_group_{group}"
        if ent_reg.async_get_entity_id(Platform.MEDIA_PLAYER, DOMAIN, unique_id):
            continue
        members = [
            ent_reg.async_get(entity_id)
            for zone in zones
            if (
                entity_id := ent_reg.async_get_entity_id(
                    Platform.MEDIA_PLAYER, DOMAIN, f"{base}_output_{zone.code}"
                )
            )
        ]
        if not (members := [m for m in members if m is not None]):
            continue
        first = members[0]
        object_id = _MEMBER_ID_SUFFIX.sub("", first.entity_id.split(".", 1)[1])
        created = ent_reg.async_get_or_create(
            Platform.MEDIA_PLAYER,
            DOMAIN,
            unique_id,
            config_entry=entry,
            device_id=amp.id,
            suggested_object_id=object_id,
        )
        ent_reg.async_update_entity(
            created.entity_id,
            name=_MEMBER_NAME_SUFFIX.sub("", first.name) if first.name else None,
            area_id=first.area_id,
            labels=set().union(*(m.labels for m in members)),
        )
        _LOGGER.info(
            "Group %s player is %s, replacing %s",
            group,
            created.entity_id,
            ", ".join(m.entity_id for m in members),
        )

    if entry.title == entry.data.get(CONF_LEGACY_UNIQUE_ID) and coord.data.name:
        hass.config_entries.async_update_entry(entry, title=coord.data.name)


@callback
def async_prune_entities(
    hass: HomeAssistant, entry: DirectorConfigEntry, coord: DirectorCoordinator
) -> None:
    """Remove registry entries of platforms that no longer provide them."""
    ent_reg = er.async_get(hass)
    domains = {domain for domain, _ in coord.unique_ids}
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.domain in domains and (entity.domain, entity.unique_id) not in coord.unique_ids:
            _LOGGER.info("Removing %s, which %s no longer has", entity.entity_id, entry.title)
            ent_reg.async_remove(entity.entity_id)
